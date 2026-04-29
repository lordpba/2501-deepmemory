import pytest
from unittest.mock import AsyncMock, patch
from core.agent import search_web, read_webpage

@pytest.mark.asyncio
async def test_search_web_duckduckgo():
    mock_html = """
    <html>
        <body>
            <a class="result__snippet">Test result 1</a>
            <a class="result__snippet">Test result 2</a>
        </body>
    </html>
    """
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.text = mock_html
        mock_resp.raise_for_status = AsyncMock()
        mock_get.return_value = mock_resp
        
        result = await search_web("test query")
        assert "Test result 1" in result
        assert "Test result 2" in result

@pytest.mark.asyncio
async def test_read_webpage():
    mock_html = """
    <html>
        <head><script>ignore me</script></head>
        <body>
            <nav>Menu</nav>
            <main>
                <h1>Article Title</h1>
                <p>This is the main text.</p>
            </main>
            <footer>Copyright</footer>
        </body>
    </html>
    """
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.text = mock_html
        mock_resp.raise_for_status = AsyncMock()
        mock_get.return_value = mock_resp
        
        result = await read_webpage("https://example.com")
        assert "Article Title" in result
        assert "This is the main text." in result
        assert "ignore me" not in result
        assert "Menu" not in result
        assert "Copyright" not in result
