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
        self.config = {}

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
            self.model, conversation, self.instructions, existing_pages=existing, config=self.config
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

    async def process_raw_files(self, on_progress: ProgressCallback | None = None) -> list[str]:
        """Scan the raw directory and process any new files into the wiki."""
        raw_files = self.ghost.list_raw_files()
        existing_pages = self.ghost.list_wiki_pages()
        written = []

        async def emit(msg: str):
            if on_progress: await on_progress(msg)

        for raw_file in raw_files:
            # Create a safe page name for the source
            safe_name = "sources/" + "".join(c if c.isalnum() else "-" for c in raw_file).lower()
            if safe_name in existing_pages:
                continue # Already processed

            await emit(f"Processing new raw file: {raw_file}...")
            try:
                content = self.ghost.read_raw_file(raw_file)
                # Try to extract text depending on type, or just pass as generic if possible.
                # For simplicity, if it's pdf/docx we should ideally use our extractors, but we can just use the ui/server ones if we move them, 
                # or just pass it as text if it's txt/md.
                
                # To keep it robust without duplicating pdf logic, let's build a special LLM prompt
                ext = Path(raw_file).suffix.lower()
                text_content = ""
                images = []

                if ext in [".txt", ".md", ".csv"]:
                    text_content = content.decode("utf-8", errors="replace")
                elif ext == ".pdf":
                    try:
                        import fitz
                        doc = fitz.open(stream=content, filetype="pdf")
                        text_content = "\n\n".join(page.get_text() for page in doc)
                    except:
                        await emit(f"⚠ Failed to read PDF: {raw_file}")
                        continue
                elif ext in [".png", ".jpg", ".jpeg"]:
                    if llm.is_multimodal(self.model):
                        import tempfile
                        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                        tmp.write(content)
                        tmp.close()
                        images.append(tmp.name)
                        text_content = "Attached image document."
                    else:
                        await emit(f"⚠ Multimodal model required for image: {raw_file}")
                        continue
                else:
                    await emit(f"⚠ Unsupported raw file type for auto-ingestion: {raw_file}")
                    continue
                    
                # Build the prompt
                prompt = [
                    {"role": "system", "content": self.instructions},
                    {"role": "user", "content": f"I am adding a new raw source file to my knowledge base. The file is named '{raw_file}'.\n\nHere is the content:\n\n{text_content}\n\nPlease extract the key information, summarize this source, and update any relevant entity/concept pages in my wiki. Return the updates in the standard JSON array format."}
                ]
                
                pages = await llm.extract_memories(
                    self.model, prompt, self.instructions, existing_pages=existing_pages, config=self.config, images=images
                )
                
                if not pages:
                    # Create a basic stub so we don't re-process it
                    pages = [(safe_name, f"# {raw_file}\n\nNo significant information extracted.")]
                
                # Ensure the source page itself is created if the LLM didn't explicitly create it
                if not any(p[0] == safe_name for p in pages):
                    pages.append((safe_name, f"# Source: {raw_file}\n\nInformation from this source has been integrated into other wiki pages."))

                for page_name, page_content in pages:
                    await emit(f"Writing {page_name}.md ...")
                    self.ghost.write_wiki_page(page_name, page_content)
                    written.append(page_name)
                    if page_name not in existing_pages:
                        existing_pages.append(page_name)

                # Clean up temp image
                for img in images:
                    Path(img).unlink(missing_ok=True)

            except Exception as e:
                await emit(f"⚠ Error processing {raw_file}: {str(e)}")

        if written:
            self._update_index(written)
            self._update_log(written)
            await emit(f"Done processing raw files — {len(written)} page(s) updated.")

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
