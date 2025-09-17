"""
SSH relay tunnel management for bridgeme
"""

import os
import socket
import threading
import time
import select
import logging
from typing import Optional, Tuple, Dict, Any, List
import paramiko
from paramiko import SSHClient, AutoAddPolicy

from .utils import (
    get_ssh_key_paths,
    parse_ssh_destination,
    safe_close,
    print_status,
    format_connection_string
)
from .session import SessionInfo, get_session_manager
from .exceptions import SSHConnectionError, TunnelError, AuthenticationError

logger = logging.getLogger("bridgeme")


class SSHRelay:
    """Manages SSH connections and tunnels for relaying connections"""

    def __init__(self, ssh_server: str, username: Optional[str] = None, key_file: Optional[str] = None):
        self.ssh_server = ssh_server
        self.username = username
        self.key_file = key_file
        self.ssh_client: Optional[SSHClient] = None
        self.is_connected = False
        self.tunnels: Dict[str, 'SSHTunnel'] = {}

        # Parse SSH destination
        parsed_user, self.hostname, self.port = parse_ssh_destination(ssh_server)
        if username is None and parsed_user:
            self.username = parsed_user
        if self.port is None:
            self.port = 22

    def connect(self) -> None:
        """Establish SSH connection to the relay server"""
        try:
            self.ssh_client = SSHClient()
            self.ssh_client.set_missing_host_key_policy(AutoAddPolicy())

            # Load system host keys
            try:
                self.ssh_client.load_system_host_keys()
            except Exception:
                pass

            # Prepare authentication
            auth_kwargs = {}

            if self.key_file:
                # Use specific key file
                auth_kwargs['key_filename'] = self.key_file
            else:
                # Try to use SSH agent first
                try:
                    auth_kwargs['allow_agent'] = True
                except Exception:
                    pass

                # Get available key files
                key_files = get_ssh_key_paths()
                if key_files:
                    auth_kwargs['key_filename'] = key_files

            # Connect
            logger.debug(f"Connecting to SSH server {self.hostname}:{self.port}")

            connect_kwargs = {
                'hostname': self.hostname,
                'port': self.port,
                'username': self.username,
                'timeout': 30,
                'compress': True,
                **auth_kwargs
            }

            self.ssh_client.connect(**connect_kwargs)
            self.is_connected = True

            logger.info(f"Connected to SSH relay server {self.hostname}:{self.port}")

        except paramiko.AuthenticationException as e:
            raise AuthenticationError(f"SSH authentication failed: {e}")
        except paramiko.SSHException as e:
            raise SSHConnectionError(f"SSH connection failed: {e}")
        except Exception as e:
            raise SSHConnectionError(f"Failed to connect to SSH server: {e}")

    def create_reverse_tunnel(self, session_info: SessionInfo) -> 'SSHTunnel':
        """Create reverse tunnel for a session"""
        if not self.is_connected or not self.ssh_client:
            raise SSHConnectionError("Not connected to SSH server")

        try:
            # Allocate relay port
            session_manager = get_session_manager()
            relay_port = session_manager.allocate_relay_port(session_info.session_id)

            # Create tunnel
            tunnel = SSHTunnel(
                ssh_client=self.ssh_client,
                session_info=session_info,
                relay_port=relay_port,
                local_host="localhost",
                local_port=session_info.host_port
            )

            tunnel.start()
            self.tunnels[session_info.session_id] = tunnel

            logger.info(f"Created reverse tunnel: relay:{relay_port} -> localhost:{session_info.host_port}")

            return tunnel

        except Exception as e:
            raise TunnelError(f"Failed to create reverse tunnel: {e}")

    def close_tunnel(self, session_id: str) -> None:
        """Close a specific tunnel"""
        tunnel = self.tunnels.pop(session_id, None)
        if tunnel:
            tunnel.stop()
            logger.info(f"Closed tunnel for session {session_id}")

    def close_all_tunnels(self) -> None:
        """Close all active tunnels"""
        for session_id in list(self.tunnels.keys()):
            self.close_tunnel(session_id)

    def disconnect(self) -> None:
        """Disconnect from SSH server and close all tunnels"""
        self.close_all_tunnels()

        if self.ssh_client:
            safe_close(self.ssh_client)
            self.ssh_client = None

        self.is_connected = False
        logger.info("Disconnected from SSH relay server")

    def get_connection_info(self) -> Dict[str, Any]:
        """Get connection information"""
        return {
            "ssh_server": self.ssh_server,
            "hostname": self.hostname,
            "port": self.port,
            "username": self.username,
            "is_connected": self.is_connected,
            "active_tunnels": len(self.tunnels),
            "tunnel_sessions": list(self.tunnels.keys())
        }

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


class SSHTunnel:
    """Represents an active SSH tunnel"""

    def __init__(self, ssh_client: SSHClient, session_info: SessionInfo,
                 relay_port: int, local_host: str = "localhost", local_port: int = None):
        self.ssh_client = ssh_client
        self.session_info = session_info
        self.relay_port = relay_port
        self.local_host = local_host
        self.local_port = local_port or session_info.host_port
        self.is_running = False
        self.transport: Optional[paramiko.Transport] = None
        self.server_socket: Optional[socket.socket] = None
        self.accept_thread: Optional[threading.Thread] = None
        self.connections: List['TunnelConnection'] = []

    def start(self) -> None:
        """Start the SSH tunnel"""
        try:
            self.transport = self.ssh_client.get_transport()
            if not self.transport:
                raise TunnelError("No SSH transport available")

            # Request remote port forwarding
            self.transport.request_port_forward('', self.relay_port, handler=self._handle_tunnel_connection)
            self.is_running = True

            logger.info(f"SSH tunnel started on remote port {self.relay_port}")

        except Exception as e:
            self.stop()
            raise TunnelError(f"Failed to start SSH tunnel: {e}")

    def _handle_tunnel_connection(self, channel: paramiko.Channel, origin_addr: Tuple[str, int],
                                server_addr: Tuple[str, int]) -> None:
        """Handle incoming tunnel connections"""
        logger.debug(f"New tunnel connection from {origin_addr}")

        try:
            # Create connection to local shell server
            local_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            local_socket.connect((self.local_host, self.local_port))

            # Create tunnel connection handler
            connection = TunnelConnection(channel, local_socket, origin_addr)
            self.connections.append(connection)

            # Start forwarding in a separate thread
            forward_thread = threading.Thread(
                target=connection.start_forwarding,
                name=f"tunnel-{self.session_info.session_id}-{origin_addr[0]}",
                daemon=True
            )
            forward_thread.start()

        except Exception as e:
            logger.error(f"Failed to handle tunnel connection: {e}")
            safe_close(channel)

    def stop(self) -> None:
        """Stop the SSH tunnel"""
        self.is_running = False

        # Close all connections
        for connection in self.connections:
            connection.close()
        self.connections.clear()

        # Cancel port forwarding
        if self.transport and self.transport.is_active():
            try:
                self.transport.cancel_port_forward('', self.relay_port)
            except Exception as e:
                logger.debug(f"Error canceling port forward: {e}")

        logger.info(f"SSH tunnel stopped (relay port {self.relay_port})")

    def get_stats(self) -> Dict[str, Any]:
        """Get tunnel statistics"""
        return {
            "session_id": self.session_info.session_id,
            "relay_port": self.relay_port,
            "local_port": self.local_port,
            "is_running": self.is_running,
            "active_connections": len(self.connections),
            "connection_origins": [conn.origin_addr for conn in self.connections if conn.is_active]
        }


class TunnelConnection:
    """Represents a single connection through an SSH tunnel"""

    def __init__(self, channel: paramiko.Channel, local_socket: socket.socket, origin_addr: Tuple[str, int]):
        self.channel = channel
        self.local_socket = local_socket
        self.origin_addr = origin_addr
        self.is_active = False

    def start_forwarding(self) -> None:
        """Start bidirectional forwarding between channel and local socket"""
        self.is_active = True

        try:
            # Start forwarding threads
            channel_to_socket_thread = threading.Thread(
                target=self._forward_channel_to_socket,
                daemon=True
            )
            socket_to_channel_thread = threading.Thread(
                target=self._forward_socket_to_channel,
                daemon=True
            )

            channel_to_socket_thread.start()
            socket_to_channel_thread.start()

            # Wait for threads to complete
            channel_to_socket_thread.join()
            socket_to_channel_thread.join()

        except Exception as e:
            logger.error(f"Error in tunnel forwarding: {e}")
        finally:
            self.close()

    def _forward_channel_to_socket(self) -> None:
        """Forward data from SSH channel to local socket"""
        try:
            while self.is_active:
                # Check if channel has data
                if self.channel.recv_ready():
                    data = self.channel.recv(4096)
                    if not data:
                        break
                    self.local_socket.send(data)
                else:
                    time.sleep(0.01)  # Small delay

        except Exception as e:
            logger.debug(f"Channel->socket forwarding error: {e}")
        finally:
            self.is_active = False

    def _forward_socket_to_channel(self) -> None:
        """Forward data from local socket to SSH channel"""
        try:
            while self.is_active:
                # Use select to check for data
                ready, _, _ = select.select([self.local_socket], [], [], 1.0)
                if ready:
                    data = self.local_socket.recv(4096)
                    if not data:
                        break
                    self.channel.send(data)

        except Exception as e:
            logger.debug(f"Socket->channel forwarding error: {e}")
        finally:
            self.is_active = False

    def close(self) -> None:
        """Close the tunnel connection"""
        self.is_active = False
        safe_close(self.channel)
        safe_close(self.local_socket)


class SSHClientRelay:
    """Simple SSH client for connecting to relay and forwarding I/O"""

    def __init__(self, ssh_server: str, relay_port: int, username: Optional[str] = None,
                 key_file: Optional[str] = None):
        self.ssh_server = ssh_server
        self.relay_port = relay_port
        self.username = username
        self.key_file = key_file
        self.ssh_client: Optional[SSHClient] = None
        self.channel: Optional[paramiko.Channel] = None
        self.is_connected = False

        # Parse SSH destination
        parsed_user, self.hostname, self.port = parse_ssh_destination(ssh_server)
        if username is None and parsed_user:
            self.username = parsed_user
        if self.port is None:
            self.port = 22

    def connect(self) -> None:
        """Connect to relay server and establish forwarding"""
        try:
            # Connect to SSH server
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(AutoAddPolicy())

            # Authentication setup
            auth_kwargs = {}
            if self.key_file:
                auth_kwargs['key_filename'] = self.key_file
            else:
                auth_kwargs['allow_agent'] = True
                key_files = get_ssh_key_paths()
                if key_files:
                    auth_kwargs['key_filename'] = key_files

            # Connect
            self.ssh_client.connect(
                hostname=self.hostname,
                port=self.port,
                username=self.username,
                timeout=30,
                **auth_kwargs
            )

            # Create direct TCP connection to the relay port
            transport = self.ssh_client.get_transport()
            self.channel = transport.open_channel(
                'direct-tcpip',
                ('localhost', self.relay_port),
                ('localhost', 0)
            )

            if not self.channel:
                raise TunnelError("Failed to create channel")

            self.is_connected = True
            logger.info(f"Connected to relay {self.hostname}:{self.relay_port}")

        except Exception as e:
            self.disconnect()
            raise SSHConnectionError(f"Failed to connect to relay: {e}")

    def start_forwarding(self) -> None:
        """Start forwarding between channel and stdin/stdout"""
        if not self.is_connected or not self.channel:
            raise SSHConnectionError("Not connected")

        try:
            import sys
            import tty
            import termios

            # Set terminal to raw mode on Unix
            if hasattr(sys.stdin, 'fileno'):
                try:
                    old_settings = termios.tcgetattr(sys.stdin)
                    tty.setraw(sys.stdin)
                except Exception:
                    old_settings = None
            else:
                old_settings = None

            try:
                # Start forwarding threads
                stdin_to_channel_thread = threading.Thread(
                    target=self._forward_stdin_to_channel,
                    daemon=True
                )
                channel_to_stdout_thread = threading.Thread(
                    target=self._forward_channel_to_stdout,
                    daemon=True
                )

                stdin_to_channel_thread.start()
                channel_to_stdout_thread.start()

                # Wait for connection to close
                while self.is_connected and self.channel and not self.channel.closed:
                    time.sleep(0.1)

            finally:
                # Restore terminal settings
                if old_settings:
                    try:
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Error in forwarding: {e}")
        finally:
            self.disconnect()

    def _forward_stdin_to_channel(self) -> None:
        """Forward stdin to SSH channel"""
        try:
            import sys

            while self.is_connected and self.channel:
                # Read from stdin
                try:
                    data = sys.stdin.buffer.read(1)
                    if data:
                        self.channel.send(data)
                except Exception:
                    break

        except Exception as e:
            logger.debug(f"Stdin->channel forwarding error: {e}")

    def _forward_channel_to_stdout(self) -> None:
        """Forward SSH channel to stdout"""
        try:
            import sys

            while self.is_connected and self.channel:
                if self.channel.recv_ready():
                    data = self.channel.recv(1024)
                    if data:
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                    else:
                        break
                else:
                    time.sleep(0.01)

        except Exception as e:
            logger.debug(f"Channel->stdout forwarding error: {e}")

    def disconnect(self) -> None:
        """Disconnect from relay"""
        self.is_connected = False

        if self.channel:
            safe_close(self.channel)
            self.channel = None

        if self.ssh_client:
            safe_close(self.ssh_client)
            self.ssh_client = None

        logger.info("Disconnected from relay")


if __name__ == "__main__":
    # Test SSH relay
    import sys

    if len(sys.argv) < 2:
        print("Usage: python ssh_relay.py <ssh_server>")
        sys.exit(1)

    ssh_server = sys.argv[1]
    logging.basicConfig(level=logging.DEBUG)

    # Test SSH connection
    relay = SSHRelay(ssh_server)
    try:
        relay.connect()
        print(f"Connected to {ssh_server}")
        print(f"Connection info: {relay.get_connection_info()}")
    except Exception as e:
        print(f"Failed to connect: {e}")
    finally:
        relay.disconnect()