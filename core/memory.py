"""
Memory extractor — distills conversations into Ghost wiki pages.
Called automatically during conversation pauses (wake cycle).
"""

import datetime
from typing import Callable, Awaitable

from core.ghost import Ghost
from core import llm


ProgressCallback = Callable[[str], Awaitable[None]]


class MemoryExtractor:
    def __init__(self, ghost: Ghost, model: str, instructions: str):
        self.ghost = ghost
        self.model = model
        self.instructions = instructions

    async def extract(
        self,
        conversation: list[dict],
        on_progress: ProgressCallback | None = None,
    ) -> list[str]:
        """
        Extract memories from conversation and write to Ghost wiki.
        Returns list of page names written/updated.
        """
        if not conversation:
            return []

        async def emit(msg: str):
            if on_progress:
                await on_progress(msg)

        await emit("Analyzing conversation...")

        existing = self.ghost.list_wiki_pages()
        pages = await llm.extract_memories(
            self.model, conversation, self.instructions, existing_pages=existing
        )

        if not pages:
            await emit("Nothing new to remember.")
            return []

        written: list[str] = []
        for page_name, content in pages:
            await emit(f"Writing {page_name}.md ...")
            self.ghost.write_wiki_page(page_name, content)
            written.append(page_name)

        if written:
            self._update_index(written)
            self._update_log(written)
            await emit(f"Done — {len(written)} page(s) updated.")

        return written

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_index(self, new_pages: list[str]):
        try:
            index = self.ghost.read_wiki_page("index")
        except Exception:
            index = "# Ghost Wiki Index\n\n**Last updated**: -\n\n---\n\n"

        lines = index.split("\n")

        # Update last-updated date
        today = datetime.date.today().isoformat()
        updated = False
        for i, line in enumerate(lines):
            if line.startswith("**Last updated**"):
                lines[i] = f"**Last updated**: {today}"
                updated = True
                break
        if not updated:
            lines.insert(2, f"**Last updated**: {today}")

        # Remove the "Empty" placeholder if present
        lines = [l for l in lines if "*(Empty" not in l]

        # Add new page links if not already present
        for name in new_pages:
            link = f"- [[{name}]]"
            if link not in index:
                lines.append(link)

        self.ghost.write_wiki_page("index", "\n".join(lines))

    def _update_log(self, pages: list[str]):
        try:
            log = self.ghost.read_wiki_page("log")
        except Exception:
            log = "# Ghost Log\n\nAppend-only record of all memory operations.\n\n---\n"

        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n## {ts}\n\nPages updated: {', '.join(pages)}\n"
        log += entry
        self.ghost.write_wiki_page("log", log)
