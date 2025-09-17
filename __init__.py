"""
bridgeme - SSH relay-based reverse shell tool for IT troubleshooting
"""

__version__ = "1.0.0"
__author__ = "bridgeme"
__description__ = "SSH relay-based reverse shell tool for IT troubleshooting"

from .exceptions import BridgeMeError, SSHConnectionError, ShellError, SessionError

__all__ = ["BridgeMeError", "SSHConnectionError", "ShellError", "SessionError"]