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
import subprocess
import sys
import threading
import time
import webbrowser
from getpass import getpass
from pathlib import Path

script_dir = Path(__file__).parent.absolute()
venv_dir = script_dir / "venv"

# --- Local virtual environment bootstrap ---
# Ensure the script runs inside the repository-local venv and install requirements if needed.

def _in_local_venv() -> bool:
    return (
        os.environ.get("VIRTUAL_ENV") == str(venv_dir)
        or Path(sys.prefix).resolve() == venv_dir.resolve()
    )


def _local_python() -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _ensure_local_venv() -> None:
    libs_dir = script_dir / f"libs_{os.name}"
    if not venv_dir.exists() and not libs_dir.exists():
        print("Creating local virtual environment...")
        try:
            subprocess.run([sys.executable, "-m", "venv", "--copies", str(venv_dir)], check=True)
        except subprocess.CalledProcessError:
            print("Venv creation failed (USB limits). Using 'libs' folder fallback...")
            if venv_dir.exists(): shutil.rmtree(venv_dir)
            libs_dir.mkdir(exist_ok=True)

    python_exe = _local_python()
    if not python_exe.exists():
        if libs_dir.exists():
            # Fallback mode: use system python but ensure requirements in libs
            python_exe = Path(sys.executable)
        else:
            raise SystemExit("Failed to locate a valid Python environment.")

    # Check requirements
    env = os.environ.copy()
    if libs_dir.exists():
        env["PYTHONPATH"] = str(libs_dir) + os.pathsep + env.get("PYTHONPATH", "")

    check_cmd = [str(python_exe), "-c", "import httpx; import cryptography"]
    check_import = subprocess.run(check_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    
    if check_import.returncode != 0:
        print("Installing requirements...")
        if venv_dir.exists() and _local_python().exists():
            subprocess.run([str(_local_python()), "-m", "pip", "install", "--upgrade", "pip"], check=True)
            subprocess.run([str(_local_python()), "-m", "pip", "install", "-r", str(script_dir / "requirements.txt")], check=True)
        else:
            # Install to libs folder
            if libs_dir.exists():
                shutil.rmtree(libs_dir)
            libs_dir.mkdir(exist_ok=True)
            subprocess.run([sys.executable, "-m", "pip", "install", "-t", str(libs_dir), "-r", str(script_dir / "requirements.txt")], check=True)

    if not _in_local_venv() and venv_dir.exists() and _local_python().exists():
        print("Restarting with the local virtual environment...")
        os.execv(str(python_exe), [str(python_exe), str(__file__), *sys.argv[1:]])


_ensure_local_venv()

# --- Portable Dependency Support ---
# If a 'libs' folder exists in the script directory, add it to sys.path.
# This allows carrying dependencies on USB sticks (FAT32/exFAT) where venv symlinks fail.
libs_dir = script_dir / f"libs_{os.name}"
if libs_dir.exists():
    sys.path.insert(0, str(libs_dir))
# ----------------------------------

from core.ghost import Ghost, WrongPasswordError
from core import llm

VERSION = "1.1.0"

BANNER = f"""
  ██████╗ ███████╗ ██████╗  ██╗
  ╚════██╗██╔════╝██╔═████╗███║
   █████╔╝███████╗██║██╔██║╚██║
  ██╔═══╝ ╚════██║████╔╝██║ ██║
  ███████╗███████║╚██████╔╝ ██║
  ╚══════╝╚══════╝ ╚═════╝  ╚═╝
  DeepMemory v{VERSION} - Portable
"""


def parse_args():
    p = argparse.ArgumentParser(description="2501 DeepMemory")
    p.add_argument("--port", type=int, default=2501, help="UI port (default: 2501)")
    p.add_argument("--ghost", type=str, default=None, help="Path to Ghost directory")
    p.add_argument("--deploy", action="store_true", help="Force deployment to USB")
    p.add_argument("--sync-from-usb", action="store_true", help="Pull Ghost data from USB to Desktop")
    p.add_argument("--migrate", action="store_true", help="Migrate old flat wiki pages to categorical folders")
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
    """Detect potential USB mount points on Linux and Windows, filtering for writable ones."""
    drives = []
    if os.name == "nt":
        import ctypes
        import string
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drive = f"{letter}:\\"
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
                # 2=REMOVABLE, 3=FIXED. We ignore C:
                if drive_type in (2, 3) and letter != 'C':
                    path = Path(drive)
                    if is_writable(path):
                        drives.append(path)
            bitmask >>= 1
    else:
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
        
        is_update = False
        
        if target_dir.exists():
            print(f"\n  Folder '{target_dir.name}' already exists on USB.")
            action = input("  Do you want to [U]pdate code only, [O]verwrite all, or [C]ancel? (U/o/c): ").strip().lower()
            
            if action == 'u' or action == '':
                is_update = True
                # Remove old core/ui to prevent stale files
                for d in ["core", "ui"]:
                    old_dir = target_dir / d
                    if old_dir.exists():
                        try:
                            shutil.rmtree(old_dir)
                        except OSError as e:
                            pass
            elif action == 'o':
                target_ghost = target_dir / "ghost"
                if target_ghost.exists():
                    print("\n  ⚠️ You are about to overwrite and DESTROY the Ghost on the USB.")
                    pwd = getpass("  Enter USB Ghost password to confirm: ")
                    try:
                        from core.ghost import Ghost
                        Ghost.unlock(str(target_ghost), pwd)
                    except Exception:
                        print("  ❌ Wrong password. Deployment cancelled.")
                        return None
                try:
                    shutil.rmtree(target_dir)
                except OSError as e:
                    print(f"\n  ❌ Error removing existing folder: {e}")
                    return None
            else:
                return None

        print(f"\n  Deploying to {target_dir}...")
        
        # Files to copy
        to_copy = [
            "2501.py", "run.sh", "run.bat", "core", "ui", "ghost_instructions.md", 
            "requirements.txt", "name_your_ghost.png", "The Abstraction Fallacy.pdf", "README.md",
            "ui/static/favicon.png", "libs_nt", "libs_posix"
        ]
        
        if not is_update:
            to_copy.append("ghost")
        
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
        print(f"\n  To use your Ghost from the USB stick:")
        print(f"  - On LINUX:   Open terminal in {target_dir} and run: bash run.sh")
        print(f"  - On WINDOWS: Double-click run.bat in the USB folder")
        print(f"\n  Your memories, settings, and API keys are now safe on your USB stick.")
        return target_dir
    except (ValueError, IndexError):
        print("  Invalid choice.")
        return None


def sync_from_usb(dest_dir: Path):
    """Pull Ghost data from USB to Desktop."""
    drives = get_usb_drives()
    if not drives:
        print("\n  ⚠ No writable USB drives detected.")
        return
        
    print("\n  Select USB drive to sync from:")
    for i, d in enumerate(drives, 1):
        print(f"  [{i}] {d}")
        
    choice = input(f"\n  Choose drive [1-{len(drives)}] or Enter to cancel: ").strip()
    if not choice:
        return
        
    try:
        source_base = drives[int(choice) - 1]
        source_ghost = source_base / "2501-DeepMemory" / "ghost"
        
        if not source_ghost.exists():
            print(f"\n  ❌ No Ghost found on {source_base}/2501-DeepMemory/ghost")
            return
            
        dest_ghost = dest_dir / "ghost"
        if dest_ghost.exists():
            print("\n  ⚠️ This will overwrite your Desktop Ghost with the USB Ghost.")
            pwd = getpass("  Enter Desktop Ghost password to confirm: ")
            try:
                from core.ghost import Ghost
                Ghost.unlock(str(dest_ghost), pwd)
            except Exception:
                print("  ❌ Wrong password. Sync cancelled.")
                return
                
            shutil.rmtree(dest_ghost)
            
        print(f"\n  Syncing Ghost from {source_ghost} to {dest_ghost}...")
        shutil.copytree(source_ghost, dest_ghost)
        print("\n  ✅ Sync complete!")
        
    except (ValueError, IndexError):
        print("  Invalid choice.")


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


def migrate_wiki_logic(ghost: Ghost):
    """Organize old flat wiki pages into categorical folders."""
    print("\n  Scanning for old flat pages...")
    pages = ghost.list_wiki_pages()
    
    migrations = {}
    for p in pages:
        if "/" in p:
            continue
            
        new_name = None
        if p.startswith("concept-"):
            new_name = "concepts/" + p[len("concept-"):]
        elif p.startswith("project-"):
            new_name = "projects/" + p[len("project-"):]
        elif p.startswith("preferences-"):
            new_name = "preferences/" + p[len("preferences-"):]
        elif p.startswith("user-"):
            new_name = "user/" + p[len("user-"):]
            
        if new_name:
            migrations[p] = new_name

    if not migrations:
        print("  No pages to migrate.\n")
        return

    print(f"  Found {len(migrations)} pages to migrate:")
    for old, new in migrations.items():
        print(f"    {old}  ->  {new}")
        
    ans = input("\n  Proceed with migration? (y/N): ").strip().lower()
    if ans != "y":
        print("  Aborted.\n")
        return

    print("\n  Updating internal links...")
    all_pages = ghost.list_wiki_pages()
    for p in all_pages:
        try:
            content = ghost.read_wiki_page(p)
            new_content = content
            for old_name, new_name in migrations.items():
                old_link = f"[[{old_name}]]"
                new_link = f"[[{new_name}]]"
                if old_link in new_content:
                    new_content = new_content.replace(old_link, new_link)
            
            if new_content != content:
                ghost.write_wiki_page(p, new_content)
                print(f"    Updated links in {p}")
        except Exception as e:
            print(f"    ⚠ Error reading {p}: {e}")

    print("\n  Moving files...")
    wiki_dir = ghost.path / "wiki"
    for old_name, new_name in migrations.items():
        try:
            content = ghost.read_wiki_page(old_name)
            ghost.write_wiki_page(new_name, content)
            
            old_file_path = wiki_dir / f"{old_name}.md.enc"
            if old_file_path.exists():
                old_file_path.unlink()
                
            print(f"    Moved {old_name} -> {new_name}")
        except Exception as e:
            print(f"    ⚠ Failed to move {old_name}: {e}")

    print("\n  ✅ Migration complete!\n")


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
        if deploy_to_usb(script_dir):
            sys.exit(0)
        # If deployment failed/cancelled, we could either exit or continue. Let's exit.
        sys.exit(1)

    # Check for sync from usb
    if args.sync_from_usb:
        sync_from_usb(script_dir)
        sys.exit(0)

    # Auto-ask for deployment if not on a USB
    if "/media/" not in str(script_dir) and "/run/media/" not in str(script_dir):
        ans = input("  Do you want to deploy this 2501 to a USB stick? (y/N): ").strip().lower()
        if ans == "y":
            if deploy_to_usb(script_dir):
                print("\n  Exiting. Connect your USB stick to any computer and follow the instructions above.")
                sys.exit(0)

    # Resolve Ghost directory
    if args.ghost:
        ghost_dir = Path(args.ghost)
    else:
        ghost_dir = script_dir / "ghost"

    # Setup Ghost
    ghost = setup_ghost(ghost_dir)

    # Check for migration
    if args.migrate:
        migrate_wiki_logic(ghost)
        sys.exit(0)

    # Extract LLM Config from Ghost
    config = ghost.read_config() or {}
    llm_config = config.get("llm_config")
    
    # Fallback to legacy config if llm_config is not set
    if not llm_config:
        if config.get("openai_api_key"):
            llm_config = {"provider": "openai", "api_key": config["openai_api_key"]}
        elif config.get("gemini_api_key"):
            llm_config = {"provider": "gemini", "api_key": config["gemini_api_key"]}
        else:
            llm_config = {"provider": "ollama", "ollama_base": "http://localhost:11434"}
            
        # Migrate legacy to new format
        ghost.write_config({"llm_config": llm_config})

    # Detect models based on configured provider
    provider = llm_config.get("provider", "ollama")
    print(f"  Detecting models for provider: {provider}...")
    try:
        models = asyncio.run(llm.detect_models(llm_config))
    except Exception as e:
        print(f"  ⚠ Could not detect models: {e}")
        models = []

    model = "none"
    if models:
        model = select_model(models)
    else:
        print(f"\n  ⚠ No models found for {provider}.")
        if provider == "ollama":
            ans = input("  Would you like to configure an API key (OpenAI/Gemini/Claude) instead? (y/N): ").strip().lower()
            if ans == "y":
                # Fallback CLI setup for APIs if Ollama is down and UI isn't reached yet
                print("\n  --- External LLM Configuration ---")
                print("  1. OpenAI")
                print("  2. Gemini")
                print("  3. Anthropic Claude")
                choice = input("\n  Choose provider [1]: ").strip() or "1"
                
                if choice == "1":
                    key = getpass("  OpenAI API Key: ").strip()
                    llm_config = {"provider": "openai", "api_key": key}
                    model = "gpt-4o-mini"
                elif choice == "2":
                    key = getpass("  Gemini API Key: ").strip()
                    llm_config = {"provider": "gemini", "api_key": key}
                    model = "gemini-1.5-flash"
                elif choice == "3":
                    key = getpass("  Claude API Key: ").strip()
                    llm_config = {"provider": "claude", "api_key": key}
                    model = "claude-3-haiku-20240307"
                
                ghost.write_config({"llm_config": llm_config})
                print(f"  Provider {llm_config['provider']} saved.")
        else:
            print("  Running without LLM. Some features will be disabled.")

    # Load ghost instructions
    instructions_path = script_dir / "ghost_instructions.md"
    instructions = instructions_path.read_text(encoding="utf-8") if instructions_path.exists() else ""

    print(f"\n  Ghost active  →  {ghost.name}")
    print(f"  Model         →  {model}")
    print(f"  Interface     →  http://localhost:{args.port}")
    print(f"\n  Press Ctrl+C to stop and lock your Ghost.\n")

    # Open browser after a delay (longer on USB to ensure backend is ready)
    def open_browser():
        time.sleep(4.0)
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
