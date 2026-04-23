"""
Context assembler — reads the Ghost wiki and builds a context string
to prepend to LLM calls, so the model "remembers" the user.
"""

from core.ghost import Ghost


def assemble(ghost: Ghost, user_message: str, max_pages: int = 6) -> str:
    """
    Build a context block from Ghost wiki pages relevant to the message.
    Always includes the index. Adds up to max_pages relevant pages.
    """
    parts: list[str] = []

    # Always include the index as a map of what the Ghost knows
    try:
        index = ghost.read_wiki_page("index")
        parts.append(index)
    except Exception:
        pass

    pages = ghost.list_wiki_pages()
    candidate_pages = [p for p in pages if p not in ("index", "log")]

    if not candidate_pages:
        return "\n\n---\n\n".join(parts) if parts else ""

    # Score pages by keyword overlap with user message
    message_words = set(user_message.lower().split())
    scored: list[tuple[int, str]] = []

    for name in candidate_pages:
        page_words = set(name.replace("-", " ").split())
        score = len(message_words & page_words)
        scored.append((score, name))

    scored.sort(reverse=True)

    # Always include the top pages regardless of score (recent memory)
    top_pages = [name for _, name in scored[:max_pages]]

    for name in top_pages:
        try:
            content = ghost.read_wiki_page(name)
            parts.append(content)
        except Exception:
            pass

    return "\n\n---\n\n".join(parts) if parts else ""
