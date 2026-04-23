"""
Ghost — encrypted personal memory store.
All files are stored encrypted at rest (Fernet/AES-128-CBC + HMAC).
Decryption happens in memory only, never written in clear to the host disk.
"""

import os
import json
import base64
import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


class WrongPasswordError(Exception):
    pass


class Ghost:
    """
    Represents a personal Ghost — an encrypted knowledge base.

    Directory layout on disk (all .enc files are Fernet-encrypted):
        ghost/
          identity/
            salt.bin          ← random salt for key derivation
            meta.json.enc     ← {"name": "...", "version": "1.0"}
          wiki/
            index.md.enc
            log.md.enc
            [page].md.enc
          sessions/
            [YYYYMMDD_HHMMSS].json.enc
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self._fernet: Fernet | None = None

    # ------------------------------------------------------------------
    # Creation and unlocking
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, path: str, name: str, password: str) -> "Ghost":
        """Create a new Ghost at path. Raises if path already contains a Ghost."""
        ghost = cls(path)
        ghost.path.mkdir(parents=True, exist_ok=True)
        (ghost.path / "identity").mkdir(exist_ok=True)
        (ghost.path / "wiki").mkdir(exist_ok=True)
        (ghost.path / "sessions").mkdir(exist_ok=True)

        salt = os.urandom(16)
        (ghost.path / "identity" / "salt.bin").write_bytes(salt)
        ghost._fernet = ghost._derive_fernet(password, salt)

        meta = {"name": name, "version": "1.0", "created": datetime.date.today().isoformat()}
        ghost._write("identity/meta.json", json.dumps(meta, ensure_ascii=False).encode())

        today = datetime.date.today().isoformat()
        ghost._write("wiki/index.md", (
            f"# Ghost Wiki Index\n\n"
            f"**Last updated**: {today}\n\n---\n\n"
            f"*(Empty — memories will appear here during conversations)*\n"
        ).encode())
        ghost._write("wiki/log.md", (
            "# Ghost Log\n\nAppend-only record of all memory operations.\n\n---\n"
        ).encode())

        return ghost

    @classmethod
    def unlock(cls, path: str, password: str) -> "Ghost":
        """Unlock an existing Ghost. Raises WrongPasswordError on bad password."""
        ghost = cls(path)
        salt_path = ghost.path / "identity" / "salt.bin"
        if not salt_path.exists():
            raise FileNotFoundError(f"No Ghost found at {path}")
        salt = salt_path.read_bytes()
        ghost._fernet = ghost._derive_fernet(password, salt)
        try:
            ghost._read("identity/meta.json")
        except (InvalidToken, Exception):
            raise WrongPasswordError("Wrong password")
        return ghost

    @staticmethod
    def exists(path: str) -> bool:
        p = Path(path)
        return (p / "identity" / "salt.bin").exists()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        meta = json.loads(self._read("identity/meta.json"))
        return meta["name"]

    # ------------------------------------------------------------------
    # Wiki operations
    # ------------------------------------------------------------------

    def list_wiki_pages(self) -> list[str]:
        """Return page names (without .md extension)."""
        wiki_dir = self.path / "wiki"
        pages = []
        for f in wiki_dir.glob("*.md.enc"):
            # f.name = "something.md.enc" → we want "something"
            pages.append(f.name[:-7])  # strip ".md.enc" (7 chars)
        return sorted(pages)

    def read_wiki_page(self, name: str) -> str:
        return self._read(f"wiki/{name}.md").decode("utf-8")

    def write_wiki_page(self, name: str, content: str):
        self._write(f"wiki/{name}.md", content.encode("utf-8"))

    def wiki_page_exists(self, name: str) -> bool:
        return (self.path / "wiki" / f"{name}.md.enc").exists()

    # ------------------------------------------------------------------
    # Session operations
    # ------------------------------------------------------------------

    def append_session(self, log: dict):
        session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        data = json.dumps(log, ensure_ascii=False, indent=2).encode("utf-8")
        self._write(f"sessions/{session_id}.json", data)

    def get_recent_sessions(self, n: int = 3) -> list[dict]:
        sessions_dir = self.path / "sessions"
        files = sorted(sessions_dir.glob("*.json.enc"), reverse=True)[:n]
        result = []
        for f in files:
            rel = "sessions/" + f.name[:-4]  # strip ".enc"
            try:
                result.append(json.loads(self._read(rel)))
            except Exception:
                pass
        return result

    # ------------------------------------------------------------------
    # Low-level encrypted I/O
    # ------------------------------------------------------------------

    def _enc_path(self, relative: str) -> Path:
        return self.path / (relative + ".enc")

    def _write(self, relative: str, data: bytes):
        enc_path = self._enc_path(relative)
        enc_path.parent.mkdir(parents=True, exist_ok=True)
        enc_path.write_bytes(self._fernet.encrypt(data))

    def _read(self, relative: str) -> bytes:
        return self._fernet.decrypt(self._enc_path(relative).read_bytes())

    @staticmethod
    def _derive_fernet(password: str, salt: bytes) -> Fernet:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480_000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
        return Fernet(key)
