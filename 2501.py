#!/usr/bin/env python3
"""
2501 DeepMemory — main launcher.
"""

import argparse
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from getpass import getpass
from pathlib import Path

if os.name == "nt":
    import ctypes
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    ctypes.windll.kernel32.SetConsoleCP(65001)

script_dir = Path(__file__).parent.absolute()

# --- Utility Functions ---

def is_writable(path: Path) -> bool:
    try:
        test_file = path / ".2501_write_test"
        test_file.touch()
        test_file.unlink()
        return True
    except (OSError, PermissionError):
        return False

def get_usb_drives():
    drives = []
    if os.name == "nt":
        import ctypes
        import string
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drive = f"{letter}:\\"
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
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
                    if d.is_dir() and is_writable(d):
                        drives.append(d)
    return drives

def _get_local_env_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", os.environ.get("APPDATA", "~")))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache"))
    path = base.expanduser() / "2501-deepmemory"
    path.mkdir(parents=True, exist_ok=True)
    return path

def _is_running_from_usb() -> bool:
    for d in get_usb_drives():
        if str(script_dir).startswith(str(d)):
            return True
    return False

# --- Environment Setup ---

if _is_running_from_usb():
    venv_dir = _get_local_env_dir() / "venv"
else:
    venv_dir = script_dir / "venv"

def _in_local_venv() -> bool:
    return os.environ.get("VIRTUAL_ENV") == str(venv_dir) or Path(sys.prefix).resolve() == venv_dir.resolve()

def _local_python() -> Path:
    if os.name == "nt":
        portable = script_dir / "bin" / "python" / "python.exe"
        if portable.exists(): return portable
        return venv_dir / "Scripts" / "python.exe"
    else:
        portable = script_dir / "bin" / "python" / "python"
        if portable.exists(): return portable
        return venv_dir / "bin" / "python"

def _get_libs_dir() -> Path:
    """Libs are installed per-host (LOCALAPPDATA) when running from USB to avoid
    path/version mismatches across machines. USB just carries app + portable Python."""
    py_ver = f"{sys.version_info.major}{sys.version_info.minor}"
    if _is_running_from_usb():
        return _get_local_env_dir() / f"libs_{os.name}_{py_ver}"
    return script_dir / f"libs_{os.name}_{py_ver}"

def _pip_install_to(target_dir: Path, requirements: Path) -> bool:
    """Install requirements to target_dir. Try current Python first, fallback to system Python on PATH."""
    target_dir.mkdir(exist_ok=True)
    candidates = [sys.executable]
    # Portable Python has no pip — try system Python from PATH as fallback
    for name in ("python", "py", "python3"):
        exe = shutil.which(name)
        if exe and exe not in candidates:
            candidates.append(exe)
    for exe in candidates:
        try:
            cmd = [exe, "-m", "pip", "install", "-t", str(target_dir), "-r", str(requirements)]
            if exe != sys.executable:
                # We are using a fallback/host python to install packages for the target python.
                # Force pip to download wheels compatible with the target python's version/platform.
                py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
                if os.name == "nt":
                    cmd += ["--python-version", py_ver, "--platform", "win_amd64", "--only-binary=:all:"]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                return True
        except Exception:
            continue
    print("  ⚠ No Python with pip found. Install Python from python.org or run deploy from a machine with pip.")
    return False

def _ensure_local_venv() -> None:
    libs_dir = _get_libs_dir()

    if os.name == "nt":
        if venv_dir.exists(): shutil.rmtree(venv_dir)
        libs_dir.mkdir(parents=True, exist_ok=True)
    else:
        if not venv_dir.exists() and not libs_dir.exists():
            print("Creating local virtual environment...")
            try:
                subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
            except subprocess.CalledProcessError:
                if venv_dir.exists(): shutil.rmtree(venv_dir)
                libs_dir.mkdir(exist_ok=True)

    python_exe = _local_python()
    if not python_exe.exists() and not libs_dir.exists():
        raise SystemExit("Failed to locate a valid Python environment.")

    env = os.environ.copy()
    if libs_dir.exists():
        env["PYTHONPATH"] = str(libs_dir) + os.pathsep + env.get("PYTHONPATH", "")

    check_cmd = [str(python_exe if python_exe.exists() else sys.executable), "-c", "import httpx; import cryptography; import faster_whisper"]
    if subprocess.run(check_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env).returncode != 0:
        print("Installing requirements...")
        if venv_dir.exists() and _local_python().exists() and os.name != "nt":
            subprocess.run([str(_local_python()), "-m", "pip", "install", "-r", str(script_dir / "requirements.txt")], check=True)
        else:
            if not _pip_install_to(libs_dir, script_dir / "requirements.txt"):
                raise SystemExit(1)

    if not _in_local_venv() and venv_dir.exists() and _local_python().exists() and os.name != "nt":
        os.execv(str(python_exe), [str(python_exe), str(__file__), *sys.argv[1:]])

_ensure_local_venv()

libs_dir = _get_libs_dir()
if libs_dir.exists():
    sys.path.insert(0, str(libs_dir))
sys.path.insert(0, str(script_dir))

from core.ghost import Ghost, WrongPasswordError
from core import llm, utils

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
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=2501)
    p.add_argument("--ghost", type=str, default=None)
    p.add_argument("--deploy", action="store_true")
    p.add_argument("--sync-from-usb", action="store_true")
    p.add_argument("--migrate", action="store_true")
    return p.parse_args()

def download_portable_python(target_dir: Path):
    """Download embedded Python and bootstrap pip (embedded distro ships without it)."""
    url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
    print(f"\n  📥 Downloading Windows Engine...")
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            with urllib.request.urlopen(url) as response:
                total = int(response.headers.get('content-length', 0))
                curr = 0
                while True:
                    buf = response.read(8192)
                    if not buf: break
                    curr += len(buf)
                    tmp.write(buf)
                    print(f"     {curr/1024/1024:.1f}MB / {total/1024/1024:.1f}MB", end='\r')
            tmp_p = Path(tmp.name)
        with zipfile.ZipFile(tmp_p, 'r') as z: z.extractall(target_dir)
        tmp_p.unlink()
        print("\n  ✅ Engine extracted.")

        # Step 1: patch the ._pth file so site-packages is loaded (required for pip)
        print("  🔧 Enabling site-packages...")
        for pth_file in target_dir.glob("python*._pth"):
            content = pth_file.read_text()
            if "#import site" in content:
                pth_file.write_text(content.replace("#import site", "import site"))
            elif "import site" not in content:
                pth_file.write_text(content.rstrip() + "\nimport site\n")

        # Step 2: download get-pip.py and run it (ensurepip is not bundled in embedded Python)
        print("  📥 Bootstrapping pip...")
        python_exe = target_dir / "python.exe"
        get_pip = target_dir / "get-pip.py"
        urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip)
        result = subprocess.run([str(python_exe), str(get_pip), "--no-warn-script-location"],
                              capture_output=True, text=True, timeout=120)
        try: get_pip.unlink()
        except Exception: pass

        if result.returncode == 0:
            print("  ✅ Pip installed in portable Python.")
        else:
            print(f"  ⚠ Pip bootstrap failed: {result.stderr[-200:]}")
            print("    Portable Python will fall back to system Python for installs.")
        return True
    except Exception as e:
        print(f"\n  ❌ Error: {e}")
        return False

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
    except (ValueError, IndexError):
        print("  Invalid choice.")
        return None

    target_dir = target_base / "2501-DeepMemory"
    is_update = False
    
    if target_dir.exists():
        print(f"\n  Folder '{target_dir.name}' already exists on USB.")
        action = input("  Do you want to [U]pdate code only, [O]verwrite all, or [C]ancel? (U/o/c): ").strip().lower()
        
        if action == 'u' or action == '':
            is_update = True
            # Remove old core/ui/libs folders to prevent stale files
            for d in ["core", "ui", "libs_nt", "libs_posix"]:
                old_dir = target_dir / d
                if old_dir.exists():
                    try:
                        shutil.rmtree(old_dir)
                    except OSError:
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

    include_python = False
    if os.name == "nt" and not (target_dir / "bin" / "python").exists():
        ans = input("\n  Include Windows Portable Engine for portability? (Y/n): ").strip().lower()
        if ans != 'n':
            include_python = True
            
    target_dir.mkdir(parents=True, exist_ok=True)

    if include_python:
        download_portable_python(target_dir / "bin" / "python")

    to_copy = ["2501.py", "run.sh", "run.bat", "core", "ui", "ghost_instructions.md", "requirements.txt"]
    if not is_update: to_copy.append("ghost")
    try:
        for item in to_copy:
            s, d = source_dir / item, target_dir / item
            if s.exists():
                if s.is_dir():
                    if d.exists(): shutil.rmtree(d)
                    shutil.copytree(s, d)
                else: shutil.copy(s, d)
        try: (target_dir / "run.sh").chmod(0o755)
        except Exception: pass
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

def wait_for_server(port: int, timeout: int = 15):
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                time.sleep(0.5)
                return True
        time.sleep(0.5)
    return False

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
    if args.deploy: deploy_to_usb(script_dir); sys.exit(0)
    
    is_usb = _is_running_from_usb()
    if not is_usb:
        ans = input("  Do you want to deploy this 2501 to a USB stick? (y/N): ").strip().lower()
        if ans == "y":
            if deploy_to_usb(script_dir):
                print("\n  Exiting. Connect your USB stick to any computer and follow the instructions above.")
            sys.exit(0)

    ghost_dir = script_dir / "ghost"
    ghost = setup_ghost(ghost_dir)

    config = ghost.read_config() or {}
    llm_config = config.get("llm_config")
    
    if not llm_config:
        if config.get("openai_api_key"):
            llm_config = {"provider": "openai", "api_key": config["openai_api_key"]}
        elif config.get("gemini_api_key"):
            llm_config = {"provider": "gemini", "api_key": config["gemini_api_key"]}
        else:
            llm_config = {"provider": "ollama", "ollama_base": "http://localhost:11434"}
        ghost.write_config({"llm_config": llm_config})

    print("\n  Select LLM Configuration:")
    print("  [1] Ollama (Local/Network)")
    print("  [2] Remote API (OpenAI/Gemini/Claude/ReiLab)")
    print("  [3] Use last saved configuration")
    
    start_choice = input("\n  Choose [3]: ").strip() or "3"
    
    if start_choice == "1":
        ip = input("  Enter Ollama IP endpoint (default: localhost): ").strip()
        if not ip:
            ip = "localhost"
        if not ip.startswith("http"):
            ip = f"http://{ip}"
        if ":" not in ip.replace("http://", "").replace("https://", ""):
            ip += ":11434"
        llm_config = {"provider": "ollama", "ollama_base": ip}
        ghost.write_config({"llm_config": llm_config})
        
    elif start_choice == "2":
        print("\n  --- External LLM Configuration ---")
        print("  1. OpenAI")
        print("  2. Gemini")
        print("  3. Anthropic Claude")
        print("  4. ReiLab")
        api_choice = input("\n  Choose provider [1]: ").strip() or "1"
        if api_choice == "1":
            llm_config = {"provider": "openai", "api_key": getpass("  OpenAI API Key: ").strip()}
        elif api_choice == "2":
            llm_config = {"provider": "gemini", "api_key": getpass("  Gemini API Key: ").strip()}
        elif api_choice == "3":
            llm_config = {"provider": "claude", "api_key": getpass("  Claude API Key: ").strip()}
        elif api_choice == "4":
            llm_config = {"provider": "reilab", "api_key": getpass("  ReiLab API Key: ").strip()}
        ghost.write_config({"llm_config": llm_config})
        print(f"  ✓ Provider {llm_config['provider']} saved.")

    provider = llm_config.get("provider", "ollama")
    print(f"\n  Detecting models for provider: {provider}...")
    
    if provider == "ollama":
        is_available, check_msg, model_count = asyncio.run(llm.check_ollama_available(llm_config))
        if not is_available:
            print(f"\n  ⚠ {check_msg}")
            print(f"\n  Attempting to start Ollama service...")
            success, start_msg = utils.start_ollama_service()
            if success:
                print(f"  {start_msg}")
                time.sleep(2)
                is_available, check_msg, model_count = asyncio.run(llm.check_ollama_available(llm_config))
            else:
                print(f"  {start_msg}")
            
            if not is_available:
                configured_base = llm_config.get("ollama_base", "http://localhost:11434")
                if configured_base != "http://localhost:11434":
                    print(f"  Trying localhost fallback...")
                    llm_config["ollama_base"] = "http://localhost:11434"
                    is_available, check_msg, model_count = asyncio.run(llm.check_ollama_available(llm_config))
                    if is_available:
                        print(f"  ✓ Found Ollama on localhost.")
                        ghost.write_config({"llm_config": llm_config})
                    else:
                        print(f"  ⚠ {check_msg}")
                
                if not is_available:
                    print(f"\n  Ollama not found at {llm_config.get('ollama_base')}")
                    remote_ip = input(f"  Enter Ollama IP (e.g. http://10.0.0.5:11434) or ENTER to skip: ").strip()
                    if remote_ip:
                        if not remote_ip.startswith("http"): remote_ip = f"http://{remote_ip}"
                        llm_config["ollama_base"] = remote_ip
                        is_available, check_msg, model_count = asyncio.run(llm.check_ollama_available(llm_config))
                        if is_available:
                            print(f"  ✓ Connected to {remote_ip}")
                            ghost.write_config({"llm_config": llm_config})

                if not is_available:
                    print(f"\n  Would you like to configure an alternative LLM provider?")
                    ans = input(f"  (1=OpenAI, 2=Gemini, 3=Claude, 4=ReiLab, 0=Try anyway): ").strip() or "0"
                    if ans in ["1", "2", "3", "4"]:
                        provider_map = {"1": "openai", "2": "gemini", "3": "claude", "4": "reilab"}
                        key_names = {"1": "OpenAI", "2": "Gemini", "3": "Claude", "4": "ReiLab"}
                        chosen_provider = provider_map[ans]
                        api_key = getpass(f"  {key_names[ans]} API Key: ").strip()
                        llm_config = {"provider": chosen_provider, "api_key": api_key}
                        provider = chosen_provider
                        ghost.write_config({"llm_config": llm_config})
                        print(f"  ✓ Provider switched to {chosen_provider}.")
    
    try:
        models = asyncio.run(llm.detect_models(llm_config))
    except Exception as e:
        print(f"  ⚠ Could not detect models: {e}")
        models = []

    model = "none"
    if models:
        # Read the most recent config to get last_model
        current_config = ghost.read_config() or {}
        last_model = current_config.get("last_model")
        
        if start_choice == "3" and last_model in models:
            model = last_model
            print(f"  ✓ Automatically selected last saved model: {model}")
        else:
            model = select_model(models)
            current_config["last_model"] = model
            ghost.write_config(current_config)
    else:
        print(f"\n  ⚠ No models found for {provider}.")
        if provider == "ollama":
            ans = input("  Would you like to configure an alternative provider? (y/N): ").strip().lower()
            if ans == "y":
                print("\n  --- External LLM Configuration ---")
                print("  1. OpenAI")
                print("  2. Gemini")
                print("  3. Anthropic Claude")
                print("  4. ReiLab")
                choice = input("\n  Choose provider [1]: ").strip() or "1"
                if choice == "1":
                    llm_config = {"provider": "openai", "api_key": getpass("  OpenAI API Key: ").strip()}
                    model = "gpt-4o-mini"
                elif choice == "2":
                    llm_config = {"provider": "gemini", "api_key": getpass("  Gemini API Key: ").strip()}
                    model = "gemini-1.5-flash"
                elif choice == "3":
                    llm_config = {"provider": "claude", "api_key": getpass("  Claude API Key: ").strip()}
                    model = "claude-3-haiku-20240307"
                elif choice == "4":
                    llm_config = {"provider": "reilab", "api_key": getpass("  ReiLab API Key: ").strip()}
                    model = "google/gemini-2.5-flash"
                ghost.write_config({"llm_config": llm_config})
                print(f"  Provider {llm_config['provider']} saved.")
        else:
            print("  Running without LLM. Some features will be disabled.")
    
    instructions = (script_dir / "ghost_instructions.md").read_text(encoding="utf-8") if (script_dir / "ghost_instructions.md").exists() else ""
    
    print(f"\n  Ghost active  →  {ghost.name}")
    print(f"  Model         →  {model}")
    print(f"  Interface     →  http://localhost:{args.port}")
    print(f"\n  Press Ctrl+C to stop and lock your Ghost.\n")

    def open_browser():
        if wait_for_server(args.port):
            webbrowser.open(f"http://localhost:{args.port}")
    threading.Thread(target=open_browser, daemon=True).start()
    
    from ui.server import start
    try: start(ghost, model, instructions, port=args.port)
    except KeyboardInterrupt: pass

if __name__ == "__main__":
    main()
