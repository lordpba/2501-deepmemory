"""
LLM interface — Ollama-first, designed to be LLM-agnostic.
Supports local/remote Ollama, OpenAI, Google Gemini, and Anthropic Claude.
"""

import base64
import datetime
import os
import json
from pathlib import Path

import httpx

TIMEOUT = 120.0

# Known multimodal model name patterns
MULTIMODAL_PATTERNS = [
    "llava", "bakllava", "moondream", "llama3.2-vision",
    "gemma3", "minicpm-v", "llava-llama3", "llava-phi3",
    "vision", "-vl", "cogvlm", "gpt-4o", "gemini", "claude-3-5"
]


async def detect_models(config: dict = None) -> list[str]:
    """Return list of available models for the configured provider."""
    config = config or {}
    provider = config.get("provider", "ollama")
    
    if provider == "ollama":
        base_url = config.get("ollama_base", "http://localhost:11434")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{base_url}/api/tags")
                r.raise_for_status()
                return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []
    
    elif provider == "openai":
        return ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]
    
    elif provider == "gemini":
        return ["gemini-1.5-pro", "gemini-1.5-flash"]
    
    elif provider == "claude":
        return ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-haiku-20240307"]
    
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
    config: dict = None,
) -> str:
    """
    Send messages to the selected LLM and return the reply.
    """
    if model == "none":
        return "⚠ No LLM configured. Please check your settings."

    config = config or {}
    provider = config.get("provider", "ollama")

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

    if provider == "openai":
        return await _chat_openai(model, full_messages, images, config.get("api_key"))
    elif provider == "gemini":
        return await _chat_gemini(model, full_messages, images, config.get("api_key"))
    elif provider == "claude":
        return await _chat_claude(model, full_messages, images, config.get("api_key"))
    else:
        # Default to Ollama
        base_url = config.get("ollama_base", "http://localhost:11434")
        return await _chat_ollama(model, full_messages, images, base_url)


async def _chat_ollama(model: str, messages: list[dict], images: list[str] | None, base_url: str) -> str:
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
        r = await client.post(f"{base_url}/api/chat", json=payload)
        r.raise_for_status()
        return r.json()["message"]["content"]


async def _chat_openai(model: str, messages: list[dict], images: list[str] | None, api_key: str) -> str:
    if not api_key:
        return "⚠ OpenAI API key not found."

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


async def _chat_gemini(model: str, messages: list[dict], images: list[str] | None, api_key: str) -> str:
    if not api_key:
        return "⚠ Gemini API key not found."

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


async def _chat_claude(model: str, messages: list[dict], images: list[str] | None, api_key: str) -> str:
    if not api_key:
        return "⚠ Anthropic API key not found."

    # Claude format: 'system' is a top-level param, 'messages' contains only user/assistant
    system_msg = ""
    claude_messages = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            content = m["content"]
            if m["role"] == "user" and images:
                content = [{"type": "text", "text": m["content"]}]
                for img_path in images:
                    with open(img_path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                        content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64
                            }
                        })
            claude_messages.append({"role": m["role"], "content": content})

    payload = {
        "model": model,
        "max_tokens": 4096,
        "messages": claude_messages,
    }
    if system_msg:
        payload["system"] = system_msg

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json=payload
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


async def extract_memories(
    model: str,
    conversation: list[dict],
    instructions: str,
    existing_pages: list[str] | None = None,
    config: dict = None,
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

    response = await chat(model, [{"role": "user", "content": prompt}], config=config)

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
