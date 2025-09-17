"""
Custom exceptions for bridgeme package
"""


class BridgeMeError(Exception):
    """Base exception for all bridgeme errors"""
    pass


class SSHConnectionError(BridgeMeError):
    """Raised when SSH connection fails"""
    pass


class ShellError(BridgeMeError):
    """Raised when shell operations fail"""
    pass


class SessionError(BridgeMeError):
    """Raised when session management fails"""
    pass


class PortAllocationError(SessionError):
    """Raised when port allocation fails"""
    pass


class AuthenticationError(SSHConnectionError):
    """Raised when SSH authentication fails"""
    pass


class TunnelError(SSHConnectionError):
    """Raised when SSH tunnel creation fails"""
    pass