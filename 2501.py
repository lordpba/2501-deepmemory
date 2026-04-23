#!/usr/bin/env python3
"""
2501 DeepMemory — main launcher.

Usage:
    python 2501.py
    python 2501.py --port 2502
    python 2501.py --ghost /path/to/ghost
"""

import argparse
import asyncio
import sys
import threading
import time
import webbrowser
from getpass import getpass
from pathlib import Path

from core.ghost import Ghost, WrongPasswordError
from core import llm

BANNER = r"""
  ██████╗ ███████╗ ██████╗  ██╗
  ╚════██╗██╔════╝██╔═████╗███║
   █████╔╝███████╗██║██╔██║╚██║
  ██╔═══╝ ╚════██║████╔╝██║ ██║
  ███████╗███████║╚██████╔╝ ██║
  ╚══════╝╚══════╝ ╚═════╝  ╚═╝
  DeepMemory v1
"""


def parse_args():
    p = argparse.ArgumentParser(description="2501 DeepMemory")
    p.add_argument("--port", type=int, default=2501, help="UI port (default: 2501)")
    p.add_argument("--ghost", type=str, default=None, help="Path to Ghost directory")
    return p.parse_args()


def setup_ghost(ghost_dir: Path) -> Ghost:
    """Create or unlock the Ghost interactively."""
    if not Ghost.exists(str(ghost_dir)):
        print("  No Ghost found. Let's create yours.\n")
        name = input("  How do you want to call your Ghost? ").strip()
        if not name:
            name = "ghost"
        password = getpass("  Choose a password: ")
        confirm  = getpass("  Confirm password:  ")
        if password != confirm:
            print("\n  Passwords don't match. Exiting.")
            sys.exit(1)
        ghost = Ghost.create(str(ghost_dir), name, password)
        print(f"\n  Ghost '{name}' created.\n")
        return ghost
    else:
        password = getpass("  Ghost password: ")
        try:
            ghost = Ghost.unlock(str(ghost_dir), password)
            print(f"\n  Welcome back, {ghost.name}.\n")
            return ghost
        except WrongPasswordError:
            print("\n  Wrong password. Exiting.")
            sys.exit(1)
        except FileNotFoundError as e:
            print(f"\n  {e}")
            sys.exit(1)


def select_model(models: list[str]) -> str:
    """Let the user pick an Ollama model interactively."""
    if not models:
        return None

    print("  Available models:")
    for i, m in enumerate(models, 1):
        tag = "  👁 vision" if llm.is_multimodal(m) else ""
        print(f"  [{i}] {m}{tag}")

    choice = input(f"\n  Choose model [1]: ").strip() or "1"
    try:
        return models[int(choice) - 1]
    except (ValueError, IndexError):
        return models[0]


def main():
    args = parse_args()

    print(BANNER)

    # Resolve Ghost directory
    if args.ghost:
        ghost_dir = Path(args.ghost)
    else:
        ghost_dir = Path(__file__).parent / "ghost"

    # Setup Ghost
    ghost = setup_ghost(ghost_dir)

    # Detect Ollama models
    print("  Detecting Ollama models...")
    try:
        models = asyncio.run(llm.detect_models())
    except Exception:
        models = []

    if not models:
        print("\n  ⚠  No Ollama models found.")
        print("     Install Ollama → https://ollama.com")
        print("     Then: ollama pull llama3.2\n")
        answer = input("  Continue without a local model? (y/N): ").strip().lower()
        if answer != "y":
            sys.exit(0)
        model = "none"
    else:
        model = select_model(models)

    # Load ghost instructions
    instructions_path = Path(__file__).parent / "ghost_instructions.md"
    instructions = instructions_path.read_text(encoding="utf-8") if instructions_path.exists() else ""

    print(f"\n  Ghost active  →  {ghost.name}")
    print(f"  Model         →  {model}")
    print(f"  Interface     →  http://localhost:{args.port}")
    print(f"\n  Press Ctrl+C to stop and lock your Ghost.\n")

    # Open browser after a short delay (let the server start first)
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{args.port}")

    threading.Thread(target=open_browser, daemon=True).start()

    # Start web server (blocking — exits on Ctrl+C)
    from ui.server import start
    try:
        start(ghost, model, instructions, port=args.port)
    except KeyboardInterrupt:
        pass

    print("\n  Ghost secured. Goodbye.\n")


if __name__ == "__main__":
    main()
