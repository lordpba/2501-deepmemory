"""
Cross-platform utility functions for 2501 DeepMemory.
Handles OS-specific operations like starting Ollama service.
"""

import platform
import subprocess
import sys


def start_ollama_service() -> tuple[bool, str]:
    """
    Attempt to start the Ollama service on the current platform.
    
    Returns:
        tuple[bool, str]: (success: bool, message: str)
        - success: True if service was started or already running
        - message: Human-readable status message
    """
    system = platform.system()
    
    if system == "Windows":
        return _start_ollama_windows()
    elif system == "Linux":
        return _start_ollama_linux()
    elif system == "Darwin":  # macOS
        return _start_ollama_macos()
    else:
        return False, f"Unsupported OS: {system}. Please start Ollama manually."


def _start_ollama_windows() -> tuple[bool, str]:
    """
    Attempt to start Ollama service on Windows using 'net start'.
    Requires administrator privileges.
    """
    try:
        # Try to start the service
        result = subprocess.run(
            ["net", "start", "ollama"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            return True, "✓ Ollama service started successfully."
        elif "already being run" in result.stderr.lower() or "is already running" in result.stderr.lower():
            return True, "✓ Ollama service is already running."
        else:
            # Service start failed - likely not installed or not admin
            if "Access is denied" in result.stderr:
                return False, (
                    "⚠ Admin privilege required. Please:\n"
                    "  1. Open PowerShell as Administrator\n"
                    "  2. Run: net start ollama\n"
                    "  Or install Ollama from: https://ollama.ai/download"
                )
            else:
                return False, (
                    "⚠ Could not start Ollama service. Please:\n"
                    "  1. Ensure Ollama is installed: https://ollama.ai/download\n"
                    "  2. Open PowerShell as Administrator\n"
                    "  3. Run: net start ollama"
                )
    except subprocess.TimeoutExpired:
        return False, "⚠ Ollama service start timed out. Check if it's already running."
    except FileNotFoundError:
        return False, (
            "⚠ 'net' command not found. This is unexpected on Windows.\n"
            "Please install Ollama from: https://ollama.ai/download"
        )
    except Exception as e:
        return False, f"⚠ Error starting Ollama: {e}"


def _start_ollama_linux() -> tuple[bool, str]:
    """
    Attempt to start Ollama service on Linux using 'systemctl'.
    """
    try:
        # Check if systemctl exists
        result = subprocess.run(
            ["systemctl", "start", "ollama"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            return True, "✓ Ollama service started successfully."
        elif "No such file" in result.stderr or "not found" in result.stderr.lower():
            # systemctl not available - might be in container or non-systemd system
            return False, (
                "⚠ systemctl not available. To start Ollama:\n"
                "  1. If using systemd: sudo systemctl start ollama\n"
                "  2. Or run directly: ollama serve\n"
                "  3. Or use Docker: docker run -d -p 11434:11434 ollama/ollama"
            )
        else:
            return False, (
                f"⚠ Could not start Ollama service: {result.stderr.strip()}\n"
                "  Try: sudo systemctl start ollama\n"
                "  Or install from: https://ollama.ai/download"
            )
    except PermissionError:
        return False, (
            "⚠ Permission denied. Try:\n"
            "  sudo systemctl start ollama"
        )
    except subprocess.TimeoutExpired:
        return False, "⚠ Ollama service start timed out. Check if it's already running."
    except FileNotFoundError:
        return False, (
            "⚠ systemctl not found. Please install Ollama:\n"
            "  https://ollama.ai/download\n"
            "  Or run: ollama serve"
        )
    except Exception as e:
        return False, f"⚠ Error starting Ollama: {e}"


def _start_ollama_macos() -> tuple[bool, str]:
    """
    Attempt to start Ollama on macOS.
    On macOS, Ollama typically runs as a background service or LaunchAgent.
    """
    try:
        # Try to start via launchctl if registered
        result = subprocess.run(
            ["launchctl", "start", "ai.ollama.ollama"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0 or "already running" in result.stderr.lower():
            return True, "✓ Ollama service started successfully."
        else:
            return False, (
                "⚠ Could not start Ollama. Please:\n"
                "  1. Open Ollama.app from Applications folder\n"
                "  2. Or install from: https://ollama.ai/download"
            )
    except FileNotFoundError:
        return False, (
            "⚠ Ollama not found. Please:\n"
            "  1. Download from: https://ollama.ai/download\n"
            "  2. Run the installer\n"
            "  3. Open Ollama.app from Applications"
        )
    except subprocess.TimeoutExpired:
        return False, "⚠ Ollama service start timed out. Check if it's already running."
    except Exception as e:
        return False, f"⚠ Error starting Ollama: {e}"


def is_admin_windows() -> bool:
    """
    Check if running as admin on Windows.
    Returns False on non-Windows systems.
    """
    if platform.system() != "Windows":
        return False
    
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
