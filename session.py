"""
Session management and port allocation for bridgeme
"""

import time
import threading
import uuid
from typing import Dict, Optional, Set, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from .utils import find_available_port, is_port_available
from .exceptions import SessionError, PortAllocationError

logger = logging.getLogger("bridgeme")


@dataclass
class SessionInfo:
    """Information about an active session"""
    session_id: str
    host_port: int
    relay_port: Optional[int] = None
    ssh_server: Optional[str] = None
    username: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    status: str = "initializing"  # initializing, waiting, connected, disconnected, closed
    client_info: Dict[str, Any] = field(default_factory=dict)

    def update_activity(self) -> None:
        """Update last activity timestamp"""
        self.last_activity = datetime.now()

    def is_expired(self, timeout_minutes: int = 60) -> bool:
        """Check if session has expired due to inactivity"""
        if self.status in ["closed", "disconnected"]:
            return True

        expiry_time = self.last_activity + timedelta(minutes=timeout_minutes)
        return datetime.now() > expiry_time

    def age_minutes(self) -> float:
        """Get session age in minutes"""
        return (datetime.now() - self.created_at).total_seconds() / 60


class SessionManager:
    """Manages active sessions and port allocation"""

    def __init__(self, port_range_start: int = 10000, port_range_end: int = 65000):
        self.port_range_start = port_range_start
        self.port_range_end = port_range_end
        self.sessions: Dict[str, SessionInfo] = {}
        self.allocated_ports: Set[int] = set()
        self.lock = threading.RLock()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._cleanup_running = False

        # Start cleanup thread
        self.start_cleanup_thread()

    def start_cleanup_thread(self) -> None:
        """Start background thread for session cleanup"""
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            return

        self._cleanup_running = True
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="session-cleanup"
        )
        self._cleanup_thread.start()
        logger.debug("Started session cleanup thread")

    def stop_cleanup_thread(self) -> None:
        """Stop background cleanup thread"""
        self._cleanup_running = False
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)

    def _cleanup_loop(self) -> None:
        """Background cleanup loop"""
        while self._cleanup_running:
            try:
                self.cleanup_expired_sessions()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in session cleanup: {e}")
                time.sleep(10)  # Shorter sleep on error

    def create_session(self, ssh_server: Optional[str] = None, username: Optional[str] = None) -> SessionInfo:
        """Create a new session with allocated ports"""
        with self.lock:
            session_id = str(uuid.uuid4())[:8]  # Short session ID

            # Allocate host port
            try:
                host_port = self._allocate_port()
            except Exception as e:
                raise PortAllocationError(f"Failed to allocate host port: {e}")

            # Create session info
            session = SessionInfo(
                session_id=session_id,
                host_port=host_port,
                ssh_server=ssh_server,
                username=username,
                status="initializing"
            )

            self.sessions[session_id] = session
            logger.info(f"Created session {session_id} with host port {host_port}")

            return session

    def _allocate_port(self) -> int:
        """Allocate an available port"""
        max_attempts = 100

        for _ in range(max_attempts):
            port = find_available_port(self.port_range_start, self.port_range_end)

            if port not in self.allocated_ports and is_port_available(port):
                self.allocated_ports.add(port)
                return port

        raise PortAllocationError("Unable to allocate available port")

    def allocate_relay_port(self, session_id: str) -> int:
        """Allocate relay port for a session"""
        with self.lock:
            session = self.get_session(session_id)
            if not session:
                raise SessionError(f"Session {session_id} not found")

            if session.relay_port:
                return session.relay_port

            try:
                relay_port = self._allocate_port()
                session.relay_port = relay_port
                session.update_activity()
                logger.info(f"Allocated relay port {relay_port} for session {session_id}")
                return relay_port
            except Exception as e:
                raise PortAllocationError(f"Failed to allocate relay port: {e}")

    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        """Get session by ID"""
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                session.update_activity()
            return session

    def update_session_status(self, session_id: str, status: str, **kwargs) -> None:
        """Update session status and additional info"""
        with self.lock:
            session = self.get_session(session_id)
            if session:
                session.status = status
                session.update_activity()

                # Update additional fields
                for key, value in kwargs.items():
                    if hasattr(session, key):
                        setattr(session, key, value)
                    else:
                        session.client_info[key] = value

                logger.debug(f"Updated session {session_id} status to {status}")

    def close_session(self, session_id: str) -> None:
        """Close and clean up a session"""
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return

            # Release allocated ports
            if session.host_port in self.allocated_ports:
                self.allocated_ports.remove(session.host_port)

            if session.relay_port and session.relay_port in self.allocated_ports:
                self.allocated_ports.remove(session.relay_port)

            # Update status and remove from active sessions
            session.status = "closed"
            del self.sessions[session_id]

            logger.info(f"Closed session {session_id}")

    def list_active_sessions(self) -> Dict[str, SessionInfo]:
        """Get all active sessions"""
        with self.lock:
            return {
                sid: session for sid, session in self.sessions.items()
                if session.status not in ["closed"]
            }

    def cleanup_expired_sessions(self, timeout_minutes: int = 60) -> int:
        """Clean up expired sessions"""
        with self.lock:
            expired_sessions = []

            for session_id, session in self.sessions.items():
                if session.is_expired(timeout_minutes):
                    expired_sessions.append(session_id)

            for session_id in expired_sessions:
                logger.info(f"Cleaning up expired session {session_id}")
                self.close_session(session_id)

            return len(expired_sessions)

    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics"""
        with self.lock:
            active_sessions = self.list_active_sessions()

            stats = {
                "total_sessions": len(active_sessions),
                "allocated_ports": len(self.allocated_ports),
                "sessions_by_status": {},
                "oldest_session_minutes": None,
                "newest_session_minutes": None,
            }

            if active_sessions:
                ages = [session.age_minutes() for session in active_sessions.values()]
                stats["oldest_session_minutes"] = max(ages)
                stats["newest_session_minutes"] = min(ages)

                # Count by status
                for session in active_sessions.values():
                    status = session.status
                    stats["sessions_by_status"][status] = stats["sessions_by_status"].get(status, 0) + 1

            return stats

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_cleanup_thread()

        # Close all sessions
        with self.lock:
            session_ids = list(self.sessions.keys())
            for session_id in session_ids:
                self.close_session(session_id)


# Global session manager instance
_session_manager: Optional[SessionManager] = None
_session_manager_lock = threading.Lock()


def get_session_manager() -> SessionManager:
    """Get or create global session manager instance"""
    global _session_manager

    with _session_manager_lock:
        if _session_manager is None:
            _session_manager = SessionManager()
        return _session_manager


def shutdown_session_manager() -> None:
    """Shutdown global session manager"""
    global _session_manager

    with _session_manager_lock:
        if _session_manager:
            _session_manager.stop_cleanup_thread()
            _session_manager = None


if __name__ == "__main__":
    # Test session manager
    import time

    manager = SessionManager()

    # Create test sessions
    session1 = manager.create_session("test-server", "testuser")
    print(f"Created session: {session1.session_id}")

    session2 = manager.create_session("test-server2", "testuser2")
    print(f"Created session: {session2.session_id}")

    # Allocate relay ports
    relay_port1 = manager.allocate_relay_port(session1.session_id)
    print(f"Relay port for session1: {relay_port1}")

    # List sessions
    active = manager.list_active_sessions()
    print(f"Active sessions: {len(active)}")

    # Get stats
    stats = manager.get_session_stats()
    print(f"Stats: {stats}")

    # Clean up
    manager.close_session(session1.session_id)
    manager.close_session(session2.session_id)
    manager.stop_cleanup_thread()