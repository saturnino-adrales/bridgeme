"""
Shell server for host mode - accepts connections and spawns interactive shells
"""

import socket
import threading
import select
import time
import logging
from typing import Optional, Callable, Dict, Any
import signal
import sys

from .terminal import create_terminal_handler, PTYSession
from .session import SessionInfo, get_session_manager
from .utils import safe_close, print_status
from .exceptions import ShellError

logger = logging.getLogger("bridgeme")


class ClientConnection:
    """Represents a client connection to the shell server"""

    def __init__(self, client_socket: socket.socket, client_address: tuple, session_id: str):
        self.socket = client_socket
        self.address = client_address
        self.session_id = session_id
        self.pty_session: Optional[PTYSession] = None
        self.is_active = False
        self.threads = []

    def start(self) -> None:
        """Start handling the client connection"""
        try:
            self.is_active = True

            # Create PTY session for this client
            terminal_handler = create_terminal_handler()
            self.pty_session = terminal_handler.create_pty_session()
            self.pty_session.start()

            # Send welcome message
            welcome_msg = f"\\r\\n*** BridgeMe Shell Session {self.session_id} ***\\r\\n"
            welcome_msg += f"Connected from {self.address[0]}:{self.address[1]}\\r\\n\\r\\n"
            self.socket.send(welcome_msg.encode('utf-8'))

            # Start I/O forwarding threads
            socket_to_pty_thread = threading.Thread(
                target=self._forward_socket_to_pty,
                name=f"socket-to-pty-{self.session_id}",
                daemon=True
            )
            pty_to_socket_thread = threading.Thread(
                target=self._forward_pty_to_socket,
                name=f"pty-to-socket-{self.session_id}",
                daemon=True
            )

            self.threads = [socket_to_pty_thread, pty_to_socket_thread]

            socket_to_pty_thread.start()
            pty_to_socket_thread.start()

            logger.info(f"Started shell session for client {self.address} (session {self.session_id})")

            # Update session status
            session_manager = get_session_manager()
            session_manager.update_session_status(
                self.session_id,
                "connected",
                client_address=self.address
            )

        except Exception as e:
            logger.error(f"Failed to start client connection: {e}")
            self.close()
            raise

    def _forward_socket_to_pty(self) -> None:
        """Forward data from client socket to PTY"""
        try:
            while self.is_active and self.pty_session:
                try:
                    # Use select to check if data is available
                    ready, _, _ = select.select([self.socket], [], [], 1.0)
                    if not ready:
                        continue

                    data = self.socket.recv(1024)
                    if not data:
                        logger.debug("Client disconnected (no data received)")
                        break

                    # Forward to PTY
                    self.pty_session.write(data)

                except socket.timeout:
                    continue
                except socket.error as e:
                    logger.debug(f"Socket error in socket->pty forwarding: {e}")
                    break
                except Exception as e:
                    logger.error(f"Error in socket->pty forwarding: {e}")
                    break

        except Exception as e:
            logger.error(f"Exception in socket->pty thread: {e}")
        finally:
            self._handle_disconnect()

    def _forward_pty_to_socket(self) -> None:
        """Forward data from PTY to client socket"""
        try:
            while self.is_active and self.pty_session:
                try:
                    data = self.pty_session.read(1024)
                    if not data:
                        time.sleep(0.01)  # Small delay to prevent busy waiting
                        continue

                    # Send to client socket
                    self.socket.send(data)

                except socket.error as e:
                    logger.debug(f"Socket error in pty->socket forwarding: {e}")
                    break
                except Exception as e:
                    logger.error(f"Error in pty->socket forwarding: {e}")
                    break

        except Exception as e:
            logger.error(f"Exception in pty->socket thread: {e}")
        finally:
            self._handle_disconnect()

    def _handle_disconnect(self) -> None:
        """Handle client disconnection"""
        if self.is_active:
            logger.info(f"Client {self.address} disconnected from session {self.session_id}")
            self.close()

            # Update session status
            try:
                session_manager = get_session_manager()
                session_manager.update_session_status(self.session_id, "disconnected")
            except Exception as e:
                logger.error(f"Failed to update session status: {e}")

    def close(self) -> None:
        """Close the client connection"""
        self.is_active = False

        # Close PTY session
        if self.pty_session:
            self.pty_session.close()
            self.pty_session = None

        # Close client socket
        safe_close(self.socket)

        # Wait for threads to finish (with timeout)
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=2)


class ShellServer:
    """Server that accepts connections and spawns shell sessions"""

    def __init__(self, session_info: SessionInfo, host: str = "localhost"):
        self.session_info = session_info
        self.host = host
        self.port = session_info.host_port
        self.server_socket: Optional[socket.socket] = None
        self.is_running = False
        self.clients: Dict[str, ClientConnection] = {}
        self.accept_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the shell server"""
        try:
            # Create server socket
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.settimeout(1.0)  # Timeout for accept()

            # Bind and listen
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)

            self.is_running = True

            logger.info(f"Shell server listening on {self.host}:{self.port}")

            # Update session status
            session_manager = get_session_manager()
            session_manager.update_session_status(self.session_info.session_id, "waiting")

            # Start accept thread
            self.accept_thread = threading.Thread(
                target=self._accept_loop,
                name=f"accept-{self.session_info.session_id}",
                daemon=True
            )
            self.accept_thread.start()

        except Exception as e:
            self.stop()
            raise ShellError(f"Failed to start shell server: {e}")

    def _accept_loop(self) -> None:
        """Accept incoming connections"""
        while self.is_running and self.server_socket:
            try:
                client_socket, client_address = self.server_socket.accept()

                if not self.is_running:
                    safe_close(client_socket)
                    break

                logger.info(f"New client connection from {client_address}")

                # Create client connection handler
                client_id = f"{client_address[0]}:{client_address[1]}"
                client_connection = ClientConnection(
                    client_socket,
                    client_address,
                    self.session_info.session_id
                )

                # Start handling the client in a separate thread
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_connection,),
                    name=f"client-{client_id}",
                    daemon=True
                )
                client_thread.start()

            except socket.timeout:
                continue  # Check if still running
            except socket.error as e:
                if self.is_running:
                    logger.error(f"Socket error in accept loop: {e}")
                break
            except Exception as e:
                logger.error(f"Error in accept loop: {e}")
                break

    def _handle_client(self, client_connection: ClientConnection) -> None:
        """Handle a single client connection"""
        client_id = f"{client_connection.address[0]}:{client_connection.address[1]}"

        try:
            # Store client connection
            self.clients[client_id] = client_connection

            # Start the client session
            client_connection.start()

            # Wait for client to finish
            for thread in client_connection.threads:
                thread.join()

        except Exception as e:
            logger.error(f"Error handling client {client_id}: {e}")
        finally:
            # Clean up client
            client_connection.close()
            self.clients.pop(client_id, None)

    def stop(self) -> None:
        """Stop the shell server"""
        self.is_running = False

        # Close all client connections
        for client_connection in list(self.clients.values()):
            client_connection.close()
        self.clients.clear()

        # Close server socket
        if self.server_socket:
            safe_close(self.server_socket)
            self.server_socket = None

        # Wait for accept thread to finish
        if self.accept_thread and self.accept_thread.is_alive():
            self.accept_thread.join(timeout=5)

        logger.info(f"Shell server stopped")

    def wait_for_connections(self, timeout: Optional[float] = None) -> None:
        """Wait for the server to handle connections"""
        start_time = time.time()

        while self.is_running:
            try:
                time.sleep(0.5)

                # Check timeout
                if timeout and (time.time() - start_time) > timeout:
                    break

                # Check if accept thread is still alive
                if self.accept_thread and not self.accept_thread.is_alive():
                    break

            except KeyboardInterrupt:
                logger.info("Received interrupt signal, stopping server")
                break

    def get_stats(self) -> Dict[str, Any]:
        """Get server statistics"""
        return {
            "is_running": self.is_running,
            "host": self.host,
            "port": self.port,
            "session_id": self.session_info.session_id,
            "active_clients": len(self.clients),
            "client_addresses": [client.address for client in self.clients.values()],
        }

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def run_shell_server(session_info: SessionInfo, host: str = "localhost") -> ShellServer:
    """Factory function to create and start a shell server"""
    server = ShellServer(session_info, host)
    return server


if __name__ == "__main__":
    # Test shell server
    from .session import SessionManager

    logging.basicConfig(level=logging.DEBUG)

    # Create test session
    manager = SessionManager()
    session = manager.create_session("test-server", "testuser")

    # Start shell server
    with run_shell_server(session) as server:
        print(f"Shell server running on port {session.host_port}")
        print(f"Connect with: telnet localhost {session.host_port}")

        try:
            server.wait_for_connections()
        except KeyboardInterrupt:
            print("\\nShutting down...")

    # Clean up
    manager.close_session(session.session_id)
    manager.stop_cleanup_thread()