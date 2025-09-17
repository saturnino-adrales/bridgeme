"""Custom exceptions for BridgeMe."""


class BridgeMeError(Exception):
    """Base exception for all BridgeMe errors."""
    pass


class SSHConnectionError(BridgeMeError):
    """Raised when SSH connection fails."""
    pass


class TunnelError(BridgeMeError):
    """Raised when tunnel creation or management fails."""
    pass


class SessionError(BridgeMeError):
    """Raised when session management fails."""
    pass


class TerminalError(BridgeMeError):
    """Raised when terminal operations fail."""
    pass


class AuthenticationError(SSHConnectionError):
    """Raised when SSH authentication fails."""
    pass


class PortAllocationError(SessionError):
    """Raised when port allocation fails."""
    pass