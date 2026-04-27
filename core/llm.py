"""
LLM interface — Ollama-first, designed to be LLM-agnostic.
Supports local Ollama, OpenAI, and Google Gemini.
"""

import base64
import datetime
import os
from pathlib import Path

import httpx

OLLAMA_BASE = "http://localhost:11434"
TIMEOUT = 120.0

# Known multimodal model name patterns
MULTIMODAL_PATTERNS = [
    "llava", "bakllava", "moondream", "llama3.2-vision",
    "gemma3", "minicpm-v", "llava-llama3", "llava-phi3",
    "vision", "-vl", "cogvlm", "gpt-4o", "gemini"
]


async def detect_models() -> list[str]:
    """Return list of locally available Ollama model names."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def is_multimodal(model: str) -> bool:
    """Heuristic: check if model name suggests vision/multimodal capability."""
    if not model: return False
    m = model.lower()
    return any(p in m for p in MULTIMODAL_PATTERNS)


async def chat(
    model: str,
    messages: list[dict],
    context: str = "",
    images: list[str] | None = None,
) -> str:
    """
    Send messages to the selected LLM and return the reply.
    """
    if model == "none":
        return "⚠ No LLM configured. Please install Ollama or set up an API key."

    full_messages = []
    if context:
        system = (
            "You are 2501, a personal AI with persistent memory.\n\n"
            "Here is what your Ghost remembers about the user:\n\n"
            f"{context}\n\n"
            "Use this memory to give personalized, contextual responses."
        )
        full_messages.append({"role": "system", "content": system})

    full_messages.extend(messages)

    # Handle Providers
    if model.startswith("gpt-"):
        return await _chat_openai(model, full_messages, images)
    elif "gemini" in model.lower():
        return await _chat_gemini(model, full_messages, images)
    else:
        return await _chat_ollama(model, full_messages, images)


async def _chat_ollama(model: str, messages: list[dict], images: list[str] | None) -> str:
    # Attach images to the last user message if model supports it
    if images and is_multimodal(model):
        encoded = []
        for img_path in images:
            with open(img_path, "rb") as f:
                encoded.append(base64.b64encode(f.read()).decode())
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user":
                messages[i] = dict(messages[i])
                messages[i]["images"] = encoded
                break

    payload = {"model": model, "messages": messages, "stream": False}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{OLLAMA_BASE}/api/chat", json=payload)
        r.raise_for_status()
        return r.json()["message"]["content"]


async def _chat_openai(model: str, messages: list[dict], images: list[str] | None) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "⚠ OpenAI API key not found in environment."

    # Convert messages for OpenAI (especially images)
    openai_messages = []
    for msg in messages:
        content = msg["content"]
        if msg["role"] == "user" and images:
            content = [{"type": "text", "text": msg["content"]}]
            for img_path in images:
                with open(img_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                    })
        openai_messages.append({"role": msg["role"], "content": content})

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": openai_messages}
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def _chat_gemini(model: str, messages: list[dict], images: list[str] | None) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "⚠ Gemini API key not found in environment."

    # Gemini uses a different format, but we can use their OpenAI-compatible endpoint if available
    # or just use the standard one. Let's use the OpenAI-compatible one for simplicity if possible,
    # but Gemini's native API is better.
    # For now, let's use the OpenAI-compatible bridge if it works, or a simple native call.
    
    # Native Gemini API call (simplified)
    # We'll need to transform messages to Gemini's format: {"contents": [{"role": "user", "parts": [...]}]}
    contents = []
    for msg in messages:
        role = "user" if msg["role"] in ["user", "system"] else "model"
        parts = [{"text": msg["content"]}]
        if msg["role"] == "user" and images:
            for img_path in images:
                with open(img_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                    parts.append({
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": b64
                        }
                    })
        contents.append({"role": role, "parts": parts})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(url, json={"contents": contents})
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]


async def extract_memories(
    model: str,
    conversation: list[dict],
    instructions: str,
    existing_pages: list[str] | None = None,
) -> list[tuple[str, str]]:
    """
    Ask the LLM to extract memories from a conversation.
    """
    if not conversation or model == "none":
        return []

    today = datetime.date.today().isoformat()
    conv_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in conversation)

    existing_note = ""
    if existing_pages:
        existing_note = f"\nExisting Ghost pages: {', '.join(existing_pages)}\n"

    prompt = (
        f"{instructions}\n\n"
        f"Today's date: {today}\n"
        f"{existing_note}\n"
        f"## Conversation to process:\n\n{conv_text}\n\n"
        f"## Extract memories now:"
    )

    response = await chat(model, [{"role": "user", "content": prompt}])

    if "NOTHING_TO_REMEMBER" in response:
        return []

    pages = []
    parts = response.split("<<<PAGE:")
    for part in parts[1:]:
        if "<<<ENDPAGE>>>" in part:
            header, rest = part.split(">>>", 1)
            page_name = header.strip().lower().replace(" ", "-")
            content = rest.split("<<<ENDPAGE>>>")[0].strip()
            if page_name and content:
                pages.append((page_name, content))

    return pages
