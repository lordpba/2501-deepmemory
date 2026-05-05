"""
2501 web server — FastAPI + WebSocket.
Serves the UI on http://localhost:2501
"""

import asyncio
import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import re
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from core.ghost import Ghost
from core.session import Session
from core.memory import MemoryExtractor
from core import context as ctx
from core import llm
from core.agent import search_web, read_webpage

# ------------------------------------------------------------------
# Global app state (simple for v1 — single user, single session)
# ------------------------------------------------------------------

_state: dict = {
    "ghost": None,
    "session": None,
    "model": None,
    "instructions": "",
    "extractor": None,
    "ws_clients": set(),
    "extracting": False,
    "llm_config": {},  # provider, ollama_base, api_key
}


# ------------------------------------------------------------------
# Lifespan: save session on shutdown
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    session: Session | None = _state["session"]
    if session:
        session.save()


app = FastAPI(lifespan=lifespan)


# ------------------------------------------------------------------
# WebSocket — real-time activity bar
# ------------------------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _state["ws_clients"].add(ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive ping
    except WebSocketDisconnect:
        _state["ws_clients"].discard(ws)


async def broadcast(message: dict):
    dead = set()
    for ws in _state["ws_clients"]:
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.add(ws)
    _state["ws_clients"] -= dead


# ------------------------------------------------------------------
# REST endpoints
# ------------------------------------------------------------------

@app.get("/api/status")
async def status():
    ghost: Ghost = _state["ghost"]
    return {
        "ghost_name": ghost.name if ghost else None,
        "model": _state["model"],
        "multimodal": llm.is_multimodal(_state["model"]) if _state["model"] else False,
        "page_count": len(ghost.list_wiki_pages()) if ghost else 0,
    }


@app.get("/api/config")
async def get_config():
    return _state["llm_config"]


@app.post("/api/config")
async def update_config(data: dict):
    _state["llm_config"] = data
    ghost: Ghost = _state["ghost"]
    if ghost:
        ghost.write_config({"llm_config": data})
    return {"status": "ok"}


@app.get("/api/models")
async def get_models():
    try:
        models = await llm.detect_models(_state["llm_config"])
        return {"models": models, "current": _state["model"]}
    except Exception as e:
        return {"models": [], "error": str(e)}


@app.post("/api/model")
async def set_model(data: dict):
    _state["model"] = data["model"]
    return {"model": _state["model"]}


@app.post("/api/chat")
async def chat_endpoint(data: dict):
    ghost: Ghost = _state["ghost"]
    session: Session = _state["session"]
    model: str = _state["model"]

    user_message: str = data.get("message", "").strip()
    images: list[str] = data.get("images", [])
    injected_text: str = data.get("injected_text", "")  # text from uploaded files

    if not user_message and not injected_text and not images:
        return JSONResponse(status_code=400, content={"error": "Empty message"})

    # Build the full user content
    full_content = user_message
    if injected_text:
        full_content = f"{user_message}\n\n---\n{injected_text}" if user_message else injected_text

    session.add("user", full_content)

    # Assemble Ghost context
    context = ctx.assemble(ghost, user_message)

    agent_instructions = (
        "\n\n--- WEB TOOLS ---\n"
        "You have access to the Internet. Use these tools whenever you need current information, "
        "technical details, or any facts not present in your internal memory.\n"
        "CRITICAL: Do NOT search the web for the user's private projects or personal identity (e.g. 'my projects'), "
        "as that information exists ONLY in your internal memory context above.\n"
        "To use a tool, you MUST reply with exactly one of these commands on its own line:\n"
        "ACTION: SEARCH [your search query here]\n"
        "ACTION: READ [url here]\n"
        "Wait for the OBSERVATION before providing your final answer. Do not include the final answer in the same message as the ACTION."
    )
    context += agent_instructions

    # Agent Loop
    max_steps = 3
    for step in range(max_steps):
        try:
            reply = await llm.chat(
                model,
                session.to_llm_format(),
                context=context,
                images=images if (images and step == 0) else None,
                config=_state["llm_config"]
            )
        except Exception as e:
            reply = f"⚠ LLM error: {e}"
            break

        # Check for ACTION
        action_match = re.search(r"ACTION:\s*(SEARCH|READ)\s+\[(.*?)\]", reply, re.IGNORECASE)
        if not action_match:
            action_match = re.search(r"ACTION:\s*(SEARCH|READ)\s+(.*)", reply, re.IGNORECASE)

        if action_match:
            action_type = action_match.group(1).upper()
            action_arg = action_match.group(2).strip("[] ")
            
            session.add("assistant", reply)
            
            if action_type == "SEARCH":
                await broadcast({"type": "activity", "message": f"🔍 Searching web for '{action_arg}'..."})
                config = ghost.read_config() or {}
                serper_key = config.get("serper_api_key")
                observation = await search_web(action_arg, serper_key)
                session.add("user", f"OBSERVATION from search '{action_arg}':\n{observation}")
                
            elif action_type == "READ":
                await broadcast({"type": "activity", "message": f"📄 Reading webpage '{action_arg[:30]}...'..."})
                observation = await read_webpage(action_arg)
                session.add("user", f"OBSERVATION from reading {action_arg}:\n{observation}")
                
            continue # Next step in ReAct loop
        else:
            break # No action found, this is the final answer

    session.add("assistant", reply)

    # Clean up temp image files
    for img_path in images:
        try:
            Path(img_path).unlink(missing_ok=True)
        except Exception:
            pass

    return {"reply": reply}


@app.post("/api/extract")
async def extract_memories():
    if _state["extracting"]:
        return {"status": "already_extracting"}

    session: Session = _state["session"]
    extractor: MemoryExtractor = _state["extractor"]

    unextracted = session.get_unextracted()
    raw_files = _state["ghost"].list_raw_files()
    
    if not unextracted and not raw_files:
        return {"status": "nothing_to_extract"}

    _state["extracting"] = True

    async def progress(msg: str):
        await broadcast({"type": "activity", "message": msg})

    try:
        # Update extractor with latest state
        extractor.model = _state["model"]
        extractor.config = _state["llm_config"]
        
        all_written = []
        
        if unextracted:
            written_chat = await extractor.extract(unextracted, on_progress=progress)
            if written_chat:
                all_written.extend(written_chat)
            session.mark_extracted()
            
        written_raw = await extractor.process_raw_files(on_progress=progress)
        if written_raw:
            all_written.extend(written_raw)
            
        if all_written:
            await broadcast({"type": "ghost_updated", "pages": all_written})
            
        return {"status": "ok", "pages_written": all_written}
    finally:
        _state["extracting"] = False


@app.get("/api/ghost/pages")
async def list_pages():
    ghost: Ghost = _state["ghost"]
    return {"pages": ghost.list_wiki_pages()}

@app.get("/api/ghost/raw")
async def list_raw():
    ghost: Ghost = _state["ghost"]
    return {"files": ghost.list_raw_files()}

@app.post("/api/ghost/raw/upload")
async def upload_raw(file: UploadFile = File(...)):
    ghost: Ghost = _state["ghost"]
    content = await file.read()
    raw_path = ghost.path / "raw" / file.filename
    raw_path.write_bytes(content)
    return {"status": "ok", "filename": file.filename}

@app.get("/api/ghost/raw/{name:path}")
async def get_raw_file(name: str):
    ghost: Ghost = _state["ghost"]
    try:
        content = ghost.read_raw_file(name)
        # Determine content type based on extension
        ext = Path(name).suffix.lower()
        content_type = "application/octet-stream"
        if ext in [".txt", ".md", ".csv"]: content_type = "text/plain"
        elif ext == ".pdf": content_type = "application/pdf"
        elif ext in [".png"]: content_type = "image/png"
        elif ext in [".jpg", ".jpeg"]: content_type = "image/jpeg"
        
        return Response(content=content, media_type=content_type)
    except Exception as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


@app.get("/api/ghost/page/{name:path}")
async def get_page(name: str):
    ghost: Ghost = _state["ghost"]
    try:
        content = ghost.read_wiki_page(name)
        return {"name": name, "content": content}
    except Exception as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


@app.put("/api/ghost/page/{name:path}")
async def update_page(name: str, data: dict):
    ghost: Ghost = _state["ghost"]
    ghost.write_wiki_page(name, data.get("content", ""))
    return {"status": "ok"}


@app.delete("/api/ghost/page/{name:path}")
async def delete_page(name: str):
    ghost: Ghost = _state["ghost"]
    try:
        ghost.delete_wiki_page(name)
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/ghost/graph")
async def get_graph():
    ghost: Ghost = _state["ghost"]
    pages = ghost.list_wiki_pages()
    
    nodes = []
    links = []
    
    import re
    link_pattern = re.compile(r"\[\[([^\]]+)\]\]")
    
    for page in pages:
        if page in ["index", "log"]:
            continue
            
        nodes.append({"id": page, "label": page})
        try:
            content = ghost.read_wiki_page(page)
            found_links = link_pattern.findall(content)
            for target in found_links:
                target_clean = target.strip().lower().replace(" ", "-")
                if target_clean in ["index", "log"]:
                    continue
                # We only add links to existing pages for now
                if target_clean in pages:
                    links.append({"source": page, "target": target_clean})
        except Exception:
            continue
            
    return {"nodes": nodes, "links": links}


@app.post("/api/ghost/organize")
async def organize_ghost():
    ghost: Ghost = _state["ghost"]
    try:
        pages = ghost.list_wiki_pages()
        migrations = {}
        for p in pages:
            if "/" in p:
                continue
            new_name = None
            if p.startswith("concept-"):
                new_name = "concepts/" + p[len("concept-"):]
            elif p.startswith("project-"):
                new_name = "projects/" + p[len("project-"):]
            elif p.startswith("preferences-"):
                new_name = "preferences/" + p[len("preferences-"):]
            elif p.startswith("user-"):
                new_name = "user/" + p[len("user-"):]
            if new_name:
                migrations[p] = new_name
                
        if not migrations:
            return {"status": "ok", "message": "All pages are already organized."}
            
        all_pages = ghost.list_wiki_pages()
        for p in all_pages:
            try:
                content = ghost.read_wiki_page(p)
                new_content = content
                for old_name, new_name in migrations.items():
                    old_link = f"[[{old_name}]]"
                    new_link = f"[[{new_name}]]"
                    if old_link in new_content:
                        new_content = new_content.replace(old_link, new_link)
                if new_content != content:
                    ghost.write_wiki_page(p, new_content)
            except Exception:
                pass
                
        wiki_dir = ghost.path / "wiki"
        for old_name, new_name in migrations.items():
            try:
                content = ghost.read_wiki_page(old_name)
                ghost.write_wiki_page(new_name, content)
                old_file_path = wiki_dir / f"{old_name}.md.enc"
                if old_file_path.exists():
                    old_file_path.unlink()
            except Exception:
                pass
                
        return {"status": "ok", "message": f"Organized {len(migrations)} pages into categories."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Process an uploaded file:
    - PDF / txt / md / docx → extract text, return as injected_text
    - Images → save to temp file, return path for multimodal use
    """
    filename = file.filename or ""
    name_lower = filename.lower()
    content = await file.read()

    if name_lower.endswith(".pdf"):
        try:
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            text = "\n\n".join(page.get_text() for page in doc)
            return {"type": "text", "content": text, "filename": filename}
        except Exception as e:
            return JSONResponse(status_code=422, content={"error": f"PDF error: {e}"})

    if name_lower.endswith((".txt", ".md")):
        return {"type": "text", "content": content.decode("utf-8", errors="replace"), "filename": filename}

    if name_lower.endswith(".docx"):
        try:
            from docx import Document
            tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
            tmp.write(content)
            tmp.flush()
            doc = Document(tmp.name)
            Path(tmp.name).unlink(missing_ok=True)
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return {"type": "text", "content": text, "filename": filename}
        except Exception as e:
            return JSONResponse(status_code=422, content={"error": f"DOCX error: {e}"})

    if name_lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        suffix = Path(name_lower).suffix
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.write(content)
        tmp.flush()
        tmp.close()
        is_mm = llm.is_multimodal(_state["model"] or "")
        return {
            "type": "image",
            "path": tmp.name,
            "multimodal_supported": is_mm,
            "filename": filename,
        }

    return JSONResponse(status_code=400, content={"error": f"Unsupported file type: {filename}"})


# ------------------------------------------------------------------
# Static files (must be last)
# ------------------------------------------------------------------

_static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")


# ------------------------------------------------------------------
# Entry point called from 2501.py
# ------------------------------------------------------------------

def start(ghost: Ghost, model: str, instructions: str, port: int = 2501):
    _state["ghost"] = ghost
    _state["model"] = model
    _state["instructions"] = instructions
    
    # Load config from Ghost if present
    stored = ghost.read_config()
    if stored and "llm_config" in stored:
        _state["llm_config"] = stored["llm_config"]
    else:
        # Default config
        _state["llm_config"] = {"provider": "ollama", "ollama_base": "http://localhost:11434"}

    _state["session"] = Session(ghost)
    _state["extractor"] = MemoryExtractor(ghost, model, instructions)
    _state["extractor"].config = _state["llm_config"]

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
