"""
Session — in-memory conversation log for the current chat session.
Saved to Ghost on shutdown.
"""

import datetime
from core.ghost import Ghost


class Session:
    def __init__(self, ghost: Ghost):
        self.ghost = ghost
        self.messages: list[dict] = []
        self.started_at = datetime.datetime.now()
        self._last_extracted_idx = 0

    def add(self, role: str, content: str):
        self.messages.append({
            "role": role,
            "content": content,
            "ts": datetime.datetime.now().isoformat(),
        })

    def get_unextracted(self) -> list[dict]:
        """Messages since the last memory extraction."""
        return self.messages[self._last_extracted_idx:]

    def mark_extracted(self):
        self._last_extracted_idx = len(self.messages)

    def to_llm_format(self) -> list[dict]:
        """Strip timestamps for LLM API calls."""
        return [{"role": m["role"], "content": m["content"]} for m in self.messages]

    def save(self):
        """Persist session log to Ghost."""
        if not self.messages:
            return
        self.ghost.append_session({
            "started_at": self.started_at.isoformat(),
            "ended_at": datetime.datetime.now().isoformat(),
            "message_count": len(self.messages),
            "messages": self.messages,
        })
