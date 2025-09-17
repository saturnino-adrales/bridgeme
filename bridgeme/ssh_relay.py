"""SSH relay management for BridgeMe."""

import socket
import threading
import time
from typing import Optional, Tuple

import paramiko

from .exceptions import SSHConnectionError, TunnelError, AuthenticationError
from .utils import print_error, print_info, print_success, get_ssh_key_paths


class SSHRelay:
    """Manages SSH connections and tunnel creation."""

    def __init__(self, hostname: str, port: int = 22, username: Optional[str] = None):
        """Initialize SSH relay.

        Args:
            hostname: SSH server hostname or IP
            port: SSH server port (default: 22)
            username: SSH username (default: current user)
        """
        self.hostname = hostname
        self.port = port
        self.username = username
        self.client: Optional[paramiko.SSHClient] = None
        self.tunnel_thread: Optional[threading.Thread] = None
        self._stop_tunnel = threading.Event()

    def connect(self) -> None:
        """Establish SSH connection."""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            print_info(f"Connecting to {self.hostname}:{self.port}...")

            # Try SSH key authentication first
            ssh_keys = get_ssh_key_paths()
            connected = False

            for key_path in ssh_keys:
                try:
                    print_info(f"Trying SSH key: {key_path}")
                    self.client.connect(
                        hostname=self.hostname,
                        port=self.port,
                        username=self.username,
                        key_filename=str(key_path),
                        timeout=10,
                        auth_timeout=10,
                    )
                    print_success(f"Connected using SSH key: {key_path}")
                    connected = True
                    break
                except paramiko.AuthenticationException:
                    continue
                except Exception as e:
                    print_error(f"Failed to connect with key {key_path}: {e}")
                    continue

            # Try SSH agent if key files didn't work
            if not connected:
                try:
                    print_info("Trying SSH agent authentication...")
                    self.client.connect(
                        hostname=self.hostname,
                        port=self.port,
                        username=self.username,
                        timeout=10,
                        auth_timeout=10,
                    )
                    print_success("Connected using SSH agent")
                    connected = True
                except paramiko.AuthenticationException:
                    pass

            if not connected:
                raise AuthenticationError(
                    f"Authentication failed for {self.username}@{self.hostname}. "
                    "Please ensure SSH keys are properly configured."
                )

        except paramiko.AuthenticationException as e:
            raise AuthenticationError(f"Authentication failed: {e}")
        except paramiko.SSHException as e:
            raise SSHConnectionError(f"SSH connection failed: {e}")
        except Exception as e:
            raise SSHConnectionError(f"Connection failed: {e}")

    def create_reverse_tunnel(self, local_port: int, remote_port: int) -> None:
        """Create a reverse SSH tunnel.

        Args:
            local_port: Local port to bind on SSH server
            remote_port: Remote port to connect to on this machine
        """
        if not self.client:
            raise SSHConnectionError("Not connected to SSH server")

        try:
            # Create reverse tunnel: SSH server port -> local machine port
            transport = self.client.get_transport()
            if not transport:
                raise TunnelError("Failed to get SSH transport")

            print_info(f"Creating reverse tunnel: {self.hostname}:{local_port} -> localhost:{remote_port}")

            # Start tunnel in background thread
            self._stop_tunnel.clear()
            self.tunnel_thread = threading.Thread(
                target=self._tunnel_worker,
                args=(transport, local_port, remote_port),
                daemon=True
            )
            self.tunnel_thread.start()

            # Give tunnel time to start
            time.sleep(1)
            print_success(f"Reverse tunnel created: {self.hostname}:{local_port} -> localhost:{remote_port}")

        except Exception as e:
            raise TunnelError(f"Failed to create reverse tunnel: {e}")

    def _tunnel_worker(self, transport: paramiko.Transport, local_port: int, remote_port: int) -> None:
        """Worker thread for handling tunnel connections."""
        try:
            # Request port forwarding on the SSH server
            transport.request_port_forward("", local_port)

            while not self._stop_tunnel.is_set():
                try:
                    # Accept incoming connections on the SSH server
                    channel = transport.accept(timeout=1.0)
                    if channel is None:
                        continue

                    # Handle connection in separate thread
                    connection_thread = threading.Thread(
                        target=self._handle_tunnel_connection,
                        args=(channel, remote_port),
                        daemon=True
                    )
                    connection_thread.start()

                except Exception as e:
                    if not self._stop_tunnel.is_set():
                        print_error(f"Tunnel error: {e}")
                    break

        except Exception as e:
            print_error(f"Tunnel worker error: {e}")

    def _handle_tunnel_connection(self, channel: paramiko.Channel, remote_port: int) -> None:
        """Handle individual tunnel connection."""
        try:
            # Connect to local service
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(("localhost", remote_port))

            # Forward data between channel and socket
            self._forward_data(channel, sock)

        except Exception as e:
            print_error(f"Connection handling error: {e}")
        finally:
            try:
                channel.close()
            except:
                pass
            try:
                sock.close()
            except:
                pass

    def _forward_data(self, channel: paramiko.Channel, sock: socket.socket) -> None:
        """Forward data between SSH channel and local socket."""
        def forward_channel_to_socket():
            try:
                while True:
                    data = channel.recv(4096)
                    if not data:
                        break
                    sock.send(data)
            except:
                pass

        def forward_socket_to_channel():
            try:
                while True:
                    data = sock.recv(4096)
                    if not data:
                        break
                    channel.send(data)
            except:
                pass

        # Start forwarding threads
        t1 = threading.Thread(target=forward_channel_to_socket, daemon=True)
        t2 = threading.Thread(target=forward_socket_to_channel, daemon=True)

        t1.start()
        t2.start()

        # Wait for either thread to finish
        t1.join()
        t2.join()

    def stop_tunnel(self) -> None:
        """Stop the reverse tunnel."""
        if self.tunnel_thread and self.tunnel_thread.is_alive():
            print_info("Stopping tunnel...")
            self._stop_tunnel.set()
            self.tunnel_thread.join(timeout=5)
            print_success("Tunnel stopped")

    def disconnect(self) -> None:
        """Close SSH connection."""
        self.stop_tunnel()
        if self.client:
            self.client.close()
            self.client = None
            print_info("SSH connection closed")

    def is_connected(self) -> bool:
        """Check if SSH connection is active."""
        return self.client is not None and self.client.get_transport() is not None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()