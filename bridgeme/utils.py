"""Utility functions for BridgeMe."""

import os
import platform
import socket
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import psutil
from colorama import Fore, Style, init

# Initialize colorama for cross-platform colors
init(autoreset=True)


def get_platform() -> str:
    """Get the current platform."""
    return platform.system().lower()


def is_windows() -> bool:
    """Check if running on Windows."""
    return get_platform() == "windows"


def is_macos() -> bool:
    """Check if running on macOS."""
    return get_platform() == "darwin"


def is_linux() -> bool:
    """Check if running on Linux."""
    return get_platform() == "linux"


def find_available_port(start_port: int = 10000, end_port: int = 65000) -> int:
    """Find an available port in the given range."""
    for port in range(start_port, end_port + 1):
        if is_port_available(port):
            return port
    raise RuntimeError(f"No available ports in range {start_port}-{end_port}")


def is_port_available(port: int) -> bool:
    """Check if a port is available."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("localhost", port))
            return True
    except OSError:
        return False


def get_ssh_key_paths() -> List[Path]:
    """Get common SSH key paths."""
    ssh_dir = Path.home() / ".ssh"
    key_files = ["id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"]

    paths = []
    for key_file in key_files:
        key_path = ssh_dir / key_file
        if key_path.exists():
            paths.append(key_path)

    return paths


def detect_shell() -> Tuple[str, List[str]]:
    """Detect the best shell for the current platform."""
    if is_windows():
        # Try PowerShell first, then cmd
        if subprocess.run(["where", "pwsh"], capture_output=True).returncode == 0:
            return "pwsh", ["-NoLogo", "-NoProfile"]
        elif subprocess.run(["where", "powershell"], capture_output=True).returncode == 0:
            return "powershell", ["-NoLogo", "-NoProfile"]
        else:
            return "cmd", ["/Q"]
    else:
        # Unix-like systems: bash > zsh > sh
        shells = ["/bin/bash", "/usr/bin/bash", "/bin/zsh", "/usr/bin/zsh", "/bin/sh"]
        for shell in shells:
            if Path(shell).exists():
                return shell, ["-i"]

        # Fallback to $SHELL or sh
        shell = os.environ.get("SHELL", "/bin/sh")
        return shell, ["-i"]


def print_success(message: str) -> None:
    """Print a success message."""
    print(f"{Fore.GREEN}✓{Style.RESET_ALL} {message}")


def print_error(message: str) -> None:
    """Print an error message."""
    print(f"{Fore.RED}✗{Style.RESET_ALL} {message}", file=sys.stderr)


def print_warning(message: str) -> None:
    """Print a warning message."""
    print(f"{Fore.YELLOW}⚠{Style.RESET_ALL} {message}")


def print_info(message: str) -> None:
    """Print an info message."""
    print(f"{Fore.BLUE}ℹ{Style.RESET_ALL} {message}")


def print_box(title: str, content: str, width: int = 60) -> None:
    """Print content in a decorative box."""
    border = "─" * (width - 2)
    print(f"╭─ {title} {border[len(title)+1:]}╮")

    for line in content.split("\n"):
        if line.strip():
            padding = " " * (width - len(line) - 3)
            print(f"│ {line}{padding}│")
        else:
            print(f"│{' ' * (width - 2)}│")

    print(f"╰{'─' * (width - 2)}╯")


def generate_session_id() -> str:
    """Generate a unique session ID."""
    import random
    import string
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))


def get_process_by_port(port: int) -> Optional[psutil.Process]:
    """Get the process using a specific port."""
    for conn in psutil.net_connections():
        if conn.laddr.port == port:
            try:
                return psutil.Process(conn.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    return None