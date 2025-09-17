"""Session management for BridgeMe."""

import threading
import time
from typing import Dict, Optional, Set

from .exceptions import SessionError, PortAllocationError
from .utils import find_available_port, generate_session_id, print_info, print_success


class SessionManager:
    """Manages BridgeMe sessions and port allocation."""

    def __init__(self):
        """Initialize session manager."""
        self._sessions: Dict[str, "Session"] = {}
        self._allocated_ports: Set[int] = set()
        self._lock = threading.Lock()

    def create_session(self, ssh_host: str) -> "Session":
        """Create a new session.

        Args:
            ssh_host: SSH relay hostname

        Returns:
            New session object
        """
        with self._lock:
            session_id = generate_session_id()
            while session_id in self._sessions:
                session_id = generate_session_id()

            # Allocate a port
            port = self._allocate_port()

            session = Session(session_id, ssh_host, port)
            self._sessions[session_id] = session

            print_success(f"Created session {session_id} with port {port}")
            return session

    def get_session(self, session_id: str) -> Optional["Session"]:
        """Get session by ID."""
        with self._lock:
            return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> None:
        """Close and remove a session."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                self._allocated_ports.discard(session.port)
                print_info(f"Closed session {session_id}")

    def close_all_sessions(self) -> None:
        """Close all active sessions."""
        with self._lock:
            session_ids = list(self._sessions.keys())
            for session_id in session_ids:
                self.close_session(session_id)
            print_info("Closed all sessions")

    def list_sessions(self) -> Dict[str, "Session"]:
        """List all active sessions."""
        with self._lock:
            return dict(self._sessions)

    def _allocate_port(self) -> int:
        """Allocate an available port."""
        max_attempts = 100
        for _ in range(max_attempts):
            try:
                port = find_available_port()
                if port not in self._allocated_ports:
                    self._allocated_ports.add(port)
                    return port
            except RuntimeError:
                pass

        raise PortAllocationError("Failed to allocate available port")

    def cleanup_stale_sessions(self, max_age_hours: int = 24) -> None:
        """Clean up sessions older than max_age_hours."""
        current_time = time.time()
        cutoff_time = current_time - (max_age_hours * 3600)

        with self._lock:
            stale_sessions = [
                session_id for session_id, session in self._sessions.items()
                if session.created_at < cutoff_time
            ]

            for session_id in stale_sessions:
                self.close_session(session_id)

            if stale_sessions:
                print_info(f"Cleaned up {len(stale_sessions)} stale sessions")


class Session:
    """Represents a BridgeMe session."""

    def __init__(self, session_id: str, ssh_host: str, port: int):
        """Initialize session.

        Args:
            session_id: Unique session identifier
            ssh_host: SSH relay hostname
            port: Allocated port for this session
        """
        self.id = session_id
        self.ssh_host = ssh_host
        self.port = port
        self.created_at = time.time()
        self.last_activity = time.time()
        self.client_connected = False
        self.host_connected = False

    def update_activity(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = time.time()

    def get_client_command(self) -> str:
        """Get the command for client to connect."""
        return f"bridgeme connect {self.ssh_host}:{self.port}"

    def get_age_minutes(self) -> float:
        """Get session age in minutes."""
        return (time.time() - self.created_at) / 60

    def get_idle_minutes(self) -> float:
        """Get minutes since last activity."""
        return (time.time() - self.last_activity) / 60

    def __str__(self) -> str:
        """String representation of session."""
        return (f"Session {self.id}: {self.ssh_host}:{self.port} "
                f"(age: {self.get_age_minutes():.1f}m, "
                f"idle: {self.get_idle_minutes():.1f}m)")


# Global session manager instance
session_manager = SessionManager()