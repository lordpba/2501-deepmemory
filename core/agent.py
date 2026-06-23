import httpx
from bs4 import BeautifulSoup
import re

# In-memory caches for the session duration
_SEARCH_CACHE = {}
_WEBPAGE_CACHE = {}

async def search_web(query: str, serper_api_key: str = None) -> str:
    """Search the web for a query using Serper API, or fallback to simple DuckDuckGo HTML parsing."""
    cache_key = (query, bool(serper_api_key))
    if cache_key in _SEARCH_CACHE:
        print(f"  [Cache] Retrieval for search query: '{query}'")
        return _SEARCH_CACHE[cache_key]

    result = await _search_web_nocache(query, serper_api_key)
    # Cache successful results or non-critical error strings, but store it
    _SEARCH_CACHE[cache_key] = result
    return result

async def _search_web_nocache(query: str, serper_api_key: str = None) -> str:
    if serper_api_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://google.serper.dev/search",
                    headers={
                        "X-API-KEY": serper_api_key,
                        "Content-Type": "application/json"
                    },
                    json={"q": query}
                )
                response.raise_for_status()
                data = response.json()
                results = []
                if "answerBox" in data and "snippet" in data["answerBox"]:
                    results.append(f"Answer Box: {data['answerBox']['snippet']}")
                for res in data.get("organic", [])[:5]:
                    results.append(f"Title: {res.get('title')}\nURL: {res.get('link')}\nSnippet: {res.get('snippet')}\n")
                return "\n".join(results)
        except Exception as e:
            return f"Search failed via Serper API: {e}"
    
    # Fallback: simple DuckDuckGo HTML scraping
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            r = await client.get(f"https://html.duckduckgo.com/html/?q={query}", headers=headers)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for a in soup.find_all("a", class_="result__snippet", limit=5):
                results.append(a.get_text(strip=True))
            if not results:
                return "No results found or blocked by search engine. Please provide a Serper API key for reliable search."
            return "\n".join(results)
    except Exception as e:
        return f"Fallback search failed: {e}"


async def read_webpage(url: str) -> str:
    """Read and extract main text from a webpage."""
    if not url.startswith("http"):
        url = "https://" + url
        
    if url in _WEBPAGE_CACHE:
        print(f"  [Cache] Retrieval for webpage content: '{url}'")
        return _WEBPAGE_CACHE[url]

    result = await _read_webpage_nocache(url)
    _WEBPAGE_CACHE[url] = result
    return result

async def _read_webpage_nocache(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            
            soup = BeautifulSoup(r.text, "html.parser")
            
            # Remove scripts, styles, nav, headers, footers
            for elem in soup(["script", "style", "nav", "footer", "header", "aside"]):
                elem.extract()
                
            text = soup.get_text(separator="\n")
            # Clean up empty lines
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            text = "\n".join(lines)
            
            # Truncate if too long (e.g. 15000 chars) to avoid blowing up the context window
            if len(text) > 15000:
                text = text[:15000] + "\n...[Content truncated due to length]..."
                
            return text
    except Exception as e:
        return f"Failed to read webpage {url}: {e}"

