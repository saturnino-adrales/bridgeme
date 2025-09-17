"""
Utility functions for bridgeme package
"""

import os
import sys
import random
import socket
import logging
import platform
from typing import Optional, List, Tuple
from colorama import init, Fore, Style

# Initialize colorama for cross-platform colored output
init(autoreset=True)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Set up logging with colored output"""
    logger = logging.getLogger("bridgeme")

    if logger.handlers:
        return logger

    # Set log level
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)

    # Create console handler with color formatting
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    # Custom formatter with colors
    class ColoredFormatter(logging.Formatter):
        COLORS = {
            'DEBUG': Fore.CYAN,
            'INFO': Fore.GREEN,
            'WARNING': Fore.YELLOW,
            'ERROR': Fore.RED,
            'CRITICAL': Fore.MAGENTA,
        }

        def format(self, record):
            color = self.COLORS.get(record.levelname, '')
            record.levelname = f"{color}{record.levelname}{Style.RESET_ALL}"
            return super().format(record)

    formatter = ColoredFormatter(
        fmt='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def print_status(message: str, status: str = "INFO") -> None:
    """Print colored status message"""
    colors = {
        "INFO": Fore.CYAN,
        "SUCCESS": Fore.GREEN,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
        "DEBUG": Fore.MAGENTA,
    }
    color = colors.get(status.upper(), Fore.WHITE)
    print(f"{color}[{status}]{Style.RESET_ALL} {message}")


def find_available_port(start_port: int = 10000, end_port: int = 65000) -> int:
    """Find an available port in the specified range"""
    max_attempts = 100

    for _ in range(max_attempts):
        port = random.randint(start_port, end_port)
        if is_port_available(port):
            return port

    # If random selection fails, try sequential search
    for port in range(start_port, end_port + 1):
        if is_port_available(port):
            return port

    raise Exception(f"No available ports found in range {start_port}-{end_port}")


def is_port_available(port: int) -> bool:
    """Check if a port is available for binding"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('localhost', port))
            return True
    except OSError:
        return False


def get_platform_info() -> dict:
    """Get platform-specific information"""
    return {
        "system": platform.system(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "is_windows": platform.system().lower() == "windows",
        "is_macos": platform.system().lower() == "darwin",
        "is_linux": platform.system().lower() == "linux",
    }


def get_ssh_key_paths() -> List[str]:
    """Get common SSH key file paths"""
    home_dir = os.path.expanduser("~")
    ssh_dir = os.path.join(home_dir, ".ssh")

    key_files = [
        "id_rsa",
        "id_ecdsa",
        "id_ed25519",
        "id_dsa",
    ]

    paths = []
    for key_file in key_files:
        key_path = os.path.join(ssh_dir, key_file)
        if os.path.exists(key_path):
            paths.append(key_path)

    return paths


def parse_ssh_destination(destination: str) -> Tuple[Optional[str], str, Optional[int]]:
    """
    Parse SSH destination string into components

    Args:
        destination: String like "user@host:port" or "host:port" or "host"

    Returns:
        Tuple of (username, hostname, port)
    """
    username = None
    hostname = destination
    port = None

    # Split user@host
    if "@" in destination:
        username, hostname = destination.split("@", 1)

    # Split host:port
    if ":" in hostname:
        hostname, port_str = hostname.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            # If port is not a number, treat the whole thing as hostname
            hostname = f"{hostname}:{port_str}"
            port = None

    return username, hostname, port


def validate_ssh_destination(destination: str) -> bool:
    """Validate SSH destination format"""
    try:
        username, hostname, port = parse_ssh_destination(destination)

        # Hostname is required
        if not hostname or hostname.strip() == "":
            return False

        # Port must be valid if specified
        if port is not None and (port < 1 or port > 65535):
            return False

        return True
    except Exception:
        return False


def format_connection_string(hostname: str, port: int, username: Optional[str] = None) -> str:
    """Format connection string for display"""
    if username:
        return f"{username}@{hostname}:{port}"
    return f"{hostname}:{port}"


def safe_close(obj, method_name: str = "close") -> None:
    """Safely close an object if it has the specified method"""
    try:
        if obj and hasattr(obj, method_name):
            method = getattr(obj, method_name)
            if callable(method):
                method()
    except Exception:
        pass  # Ignore errors during cleanup


def truncate_string(text: str, max_length: int = 80) -> str:
    """Truncate string with ellipsis if too long"""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."