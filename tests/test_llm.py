import pytest
import httpx
from core import llm

@pytest.mark.asyncio
async def test_detect_models_ollama(respx_mock):
    # Mock Ollama tags API
    respx_mock.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json={
            "models": [
                {"name": "llama3:latest"},
                {"name": "llava:latest"}
            ]
        })
    )
    
    config = {"provider": "ollama", "ollama_base": "http://localhost:11434"}
    models = await llm.detect_models(config)
    assert "llama3:latest" in models
    assert "llava:latest" in models
    assert len(models) == 2

@pytest.mark.asyncio
async def test_check_ollama_available(respx_mock):
    respx_mock.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json={
            "models": [{"name": "llama3"}]
        })
    )
    
    config = {"provider": "ollama", "ollama_base": "http://localhost:11434"}
    ok, msg, count = await llm.check_ollama_available(config)
    assert ok is True
    assert count == 1

def test_is_multimodal():
    # Test patterns
    assert llm.is_multimodal("llava") is True
    assert llm.is_multimodal("gpt-4o") is True
    assert llm.is_multimodal("llama3") is False
    assert llm.is_multimodal("claude-3-opus") is True
