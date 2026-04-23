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
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from core.ghost import Ghost
from core.session import Session
from core.memory import MemoryExtractor
from core import context as ctx
from core import llm

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


@app.get("/api/models")
async def get_models():
    try:
        models = await llm.detect_models()
        return {"models": models, "current": _state["model"]}
    except httpx.ConnectError:
        return {"models": [], "error": "Ollama not reachable at localhost:11434"}


@app.post("/api/model")
async def set_model(data: dict):
    _state["model"] = data["model"]
    extractor: MemoryExtractor = _state["extractor"]
    if extractor:
        extractor.model = data["model"]
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

    # Call LLM
    try:
        reply = await llm.chat(
            model,
            session.to_llm_format(),
            context=context,
            images=images if images else None,
        )
    except httpx.ConnectError:
        reply = "⚠ Cannot reach Ollama. Is it running? (`ollama serve`)"
    except Exception as e:
        reply = f"⚠ LLM error: {e}"

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
    if not unextracted:
        return {"status": "nothing_to_extract"}

    _state["extracting"] = True

    async def progress(msg: str):
        await broadcast({"type": "activity", "message": msg})

    try:
        written = await extractor.extract(unextracted, on_progress=progress)
        session.mark_extracted()
        if written:
            await broadcast({"type": "ghost_updated", "pages": written})
        return {"status": "ok", "pages_written": written}
    finally:
        _state["extracting"] = False


@app.get("/api/ghost/pages")
async def list_pages():
    ghost: Ghost = _state["ghost"]
    pages = ghost.list_wiki_pages()
    return {"pages": pages}


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
    _state["session"] = Session(ghost)
    _state["extractor"] = MemoryExtractor(ghost, model, instructions)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
