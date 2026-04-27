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
import os
import shutil
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
  DeepMemory v1 - Portable
"""


def parse_args():
    p = argparse.ArgumentParser(description="2501 DeepMemory")
    p.add_argument("--port", type=int, default=2501, help="UI port (default: 2501)")
    p.add_argument("--ghost", type=str, default=None, help="Path to Ghost directory")
    p.add_argument("--deploy", action="store_true", help="Force deployment to USB")
    return p.parse_args()


def is_writable(path: Path) -> bool:
    """Check if a directory is writable."""
    try:
        test_file = path / ".2501_write_test"
        test_file.touch()
        test_file.unlink()
        return True
    except (OSError, PermissionError):
        return False


def get_usb_drives():
    """Detect potential USB mount points on Linux, filtering for writable ones."""
    drives = []
    user = os.environ.get("USER")
    search_paths = [Path(f"/media/{user}"), Path(f"/run/media/{user}")]
    
    for base in search_paths:
        if base.exists():
            for d in base.iterdir():
                if d.is_dir():
                    # Only add if writable
                    if is_writable(d):
                        drives.append(d)
    return drives


def deploy_to_usb(source_dir: Path):
    """Ask user to select a USB drive and copy the project there."""
    drives = get_usb_drives()
    if not drives:
        print("\n  ⚠ No writable USB drives detected.")
        print("     Ensure your USB stick is plugged in and not read-only.")
        return None

    print("\n  Select target USB drive:")
    for i, d in enumerate(drives, 1):
        print(f"  [{i}] {d}")
    
    choice = input(f"\n  Choose drive [1-{len(drives)}] or Enter to cancel: ").strip()
    if not choice:
        return None
    
    try:
        target_base = drives[int(choice) - 1]
        target_dir = target_base / "2501-DeepMemory"
        
        if target_dir.exists():
            confirm = input(f"\n  Folder '{target_dir.name}' already exists. Overwrite? (y/N): ").strip().lower()
            if confirm != "y":
                return None
            try:
                shutil.rmtree(target_dir)
            except OSError as e:
                print(f"\n  ❌ Error removing existing folder: {e}")
                return None

        print(f"\n  Deploying to {target_dir}...")
        
        # Files to copy
        to_copy = [
            "2501.py", "run.sh", "core", "ui", "ghost_instructions.md", 
            "requirements.txt", "ghost", "name_your_ghost.png", "The Abstraction Fallacy.pdf", "README.md",
            "ui/static/favicon.png", "banner_2501.png"
        ]
        
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            for item in to_copy:
                src = source_dir / item
                if src.exists():
                    if src.is_dir():
                        shutil.copytree(src, target_dir / item)
                    else:
                        shutil.copy(src, target_dir / item)
            
            # Try to make run.sh executable
            try:
                (target_dir / "run.sh").chmod(0o755)
            except Exception:
                pass

        except OSError as e:
            print(f"\n  ❌ Deployment failed: {e}")
            if "Read-only file system" in str(e):
                print("     The selected drive is read-only.")
            return None
        
        print("\n  ✅ Deployment complete!")
        print(f"  You can now take the USB stick and run it with:")
        print(f"     cd {target_dir}")
        print(f"     bash run.sh")
        return target_dir
    except (ValueError, IndexError):
        print("  Invalid choice.")
        return None


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


def configure_api(ghost: Ghost):
    """Prompt for API keys if Ollama is not available."""
    print("\n  --- External LLM Configuration ---")
    print("  1. OpenAI (GPT-4o, GPT-4o-mini)")
    print("  2. Gemini (1.5 Pro/Flash)")
    print("  3. Skip (no LLM)")
    
    choice = input("\n  Choose provider [1]: ").strip() or "1"
    
    config = ghost.read_config() or {}
    
    if choice == "1":
        key = getpass("  OpenAI API Key: ").strip()
        if key:
            config["llm_provider"] = "openai"
            config["openai_api_key"] = key
            ghost.write_config(config)
            return "gpt-4o-mini"
    elif choice == "2":
        key = getpass("  Gemini API Key: ").strip()
        if key:
            config["llm_provider"] = "gemini"
            config["gemini_api_key"] = key
            ghost.write_config(config)
            return "gemini-1.5-flash"
    
    return "none"


def main():
    args = parse_args()
    script_dir = Path(__file__).parent.absolute()

    print(BANNER)

    # Check for deployment
    if args.deploy:
        deploy_to_usb(script_dir)
        sys.exit(0)

    # Auto-ask for deployment if not on a USB (heuristic: not in /media or /run/media)
    if "/media/" not in str(script_dir) and "/run/media/" not in str(script_dir):
        ans = input("  Do you want to deploy this 2501 to a USB stick? (y/N): ").strip().lower()
        if ans == "y":
            target = deploy_to_usb(script_dir)
            if target:
                print("\n  Closing local Shell. Please use the USB stick to continue.")
                sys.exit(0)

    # Resolve Ghost directory
    if args.ghost:
        ghost_dir = Path(args.ghost)
    else:
        ghost_dir = script_dir / "ghost"

    # Setup Ghost
    ghost = setup_ghost(ghost_dir)

    # Export API keys from Ghost config
    config = ghost.read_config() or {}
    if config.get("openai_api_key"):
        os.environ["OPENAI_API_KEY"] = config["openai_api_key"]
    if config.get("gemini_api_key"):
        os.environ["GEMINI_API_KEY"] = config["gemini_api_key"]

    # Detect Ollama models
    print("  Detecting Ollama models...")
    try:
        models = asyncio.run(llm.detect_models())
    except Exception:
        models = []

    model = "none"
    if models:
        model = select_model(models)
    else:
        print("\n  ⚠ No Ollama models found.")
        # Check if we have an API config in the Ghost
        provider = config.get("llm_provider")
        
        if provider in ["openai", "gemini"]:
            print(f"  Using configured provider: {provider}")
            model = "gpt-4o-mini" if provider == "openai" else "gemini-1.5-flash"
        else:
            ans = input("  Would you like to configure an API key (OpenAI/Gemini)? (y/N): ").strip().lower()
            if ans == "y":
                model = configure_api(ghost)
                # Re-export after configuration
                new_config = ghost.read_config()
                if new_config.get("openai_api_key"): os.environ["OPENAI_API_KEY"] = new_config["openai_api_key"]
                if new_config.get("gemini_api_key"): os.environ["GEMINI_API_KEY"] = new_config["gemini_api_key"]
            else:
                print("  Running without LLM. Some features will be disabled.")

    # Load ghost instructions
    instructions_path = script_dir / "ghost_instructions.md"
    instructions = instructions_path.read_text(encoding="utf-8") if instructions_path.exists() else ""

    print(f"\n  Ghost active  →  {ghost.name}")
    print(f"  Model         →  {model}")
    print(f"  Interface     →  http://localhost:{args.port}")
    print(f"\n  Press Ctrl+C to stop and lock your Ghost.\n")

    # Open browser after a short delay
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{args.port}")

    threading.Thread(target=open_browser, daemon=True).start()

    # Start web server
    from ui.server import start
    try:
        start(ghost, model, instructions, port=args.port)
    except KeyboardInterrupt:
        pass

    print("\n  Ghost secured. Goodbye.\n")


if __name__ == "__main__":
    main()
