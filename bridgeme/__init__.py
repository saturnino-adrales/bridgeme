"""BridgeMe: SSH relay-based reverse shell tool for IT troubleshooting."""

__version__ = "0.1.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"
__description__ = "SSH relay-based reverse shell tool for IT troubleshooting"

from .exceptions import (
    BridgeMeError,
    SSHConnectionError,
    TunnelError,
    SessionError,
    TerminalError,
)

__all__ = [
    "BridgeMeError",
    "SSHConnectionError",
    "TunnelError",
    "SessionError",
    "TerminalError",
]