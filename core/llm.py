"""
LLM interface — Ollama-first, designed to be LLM-agnostic.
Swap the base URL and you can point at any OpenAI-compatible endpoint.
"""

import base64
import datetime
from pathlib import Path

import httpx

OLLAMA_BASE = "http://localhost:11434"
TIMEOUT = 120.0

# Known multimodal model name patterns
MULTIMODAL_PATTERNS = [
    "llava", "bakllava", "moondream", "llama3.2-vision",
    "gemma3", "minicpm-v", "llava-llama3", "llava-phi3",
    "vision", "-vl", "cogvlm",
]


async def detect_models() -> list[str]:
    """Return list of locally available Ollama model names."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{OLLAMA_BASE}/api/tags")
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]


def is_multimodal(model: str) -> bool:
    """Heuristic: check if model name suggests vision/multimodal capability."""
    m = model.lower()
    return any(p in m for p in MULTIMODAL_PATTERNS)


async def chat(
    model: str,
    messages: list[dict],
    context: str = "",
    images: list[str] | None = None,
) -> str:
    """
    Send messages to Ollama and return the assistant's reply.

    Args:
        model: Ollama model name
        messages: list of {"role": "user"/"assistant", "content": "..."}
        context: Ghost memory context to prepend as system message
        images: list of local file paths to images (multimodal only)
    """
    full_messages = []

    if context:
        system = (
            "You are 2501, a personal AI with persistent memory.\n\n"
            "Here is what your Ghost remembers about the user:\n\n"
            f"{context}\n\n"
            "Use this memory to give personalized, contextual responses. "
            "If the Ghost is empty, just be helpful and introduce yourself."
        )
        full_messages.append({"role": "system", "content": system})

    full_messages.extend(messages)

    # Attach images to the last user message if model supports it
    if images and is_multimodal(model):
        encoded = []
        for img_path in images:
            with open(img_path, "rb") as f:
                encoded.append(base64.b64encode(f.read()).decode())
        # Find last user message
        for i in range(len(full_messages) - 1, -1, -1):
            if full_messages[i]["role"] == "user":
                full_messages[i] = dict(full_messages[i])  # copy
                full_messages[i]["images"] = encoded
                break

    payload = {
        "model": model,
        "messages": full_messages,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{OLLAMA_BASE}/api/chat", json=payload)
        r.raise_for_status()
        return r.json()["message"]["content"]


async def extract_memories(
    model: str,
    conversation: list[dict],
    instructions: str,
    existing_pages: list[str] | None = None,
) -> list[tuple[str, str]]:
    """
    Ask the LLM to extract memories from a conversation.
    Returns list of (page_name, markdown_content) tuples.
    """
    if not conversation:
        return []

    today = datetime.date.today().isoformat()
    conv_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in conversation
    )

    existing_note = ""
    if existing_pages:
        existing_note = (
            f"\nExisting Ghost pages (update these if relevant, don't duplicate): "
            f"{', '.join(existing_pages)}\n"
        )

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
