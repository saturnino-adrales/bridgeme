"""Cross-platform terminal handling for BridgeMe."""

import os
import pty
import select
import socket
import subprocess
import sys
import threading
import time
from typing import Optional, Tuple

from .exceptions import TerminalError
from .utils import detect_shell, is_windows, print_error, print_info, print_success


class TerminalHandler:
    """Handles cross-platform terminal operations."""

    def __init__(self):
        """Initialize terminal handler."""
        self.process: Optional[subprocess.Popen] = None
        self.master_fd: Optional[int] = None
        self.shell_cmd, self.shell_args = detect_shell()

    def start_shell(self) -> Tuple[int, subprocess.Popen]:
        """Start an interactive shell and return master fd and process.

        Returns:
            Tuple of (master_fd, process) for Unix or (None, process) for Windows
        """
        try:
            if is_windows():
                return self._start_windows_shell()
            else:
                return self._start_unix_shell()
        except Exception as e:
            raise TerminalError(f"Failed to start shell: {e}")

    def _start_unix_shell(self) -> Tuple[int, subprocess.Popen]:
        """Start shell on Unix-like systems using PTY."""
        try:
            # Create PTY pair
            master_fd, slave_fd = pty.openpty()

            # Start shell process
            self.process = subprocess.Popen(
                [self.shell_cmd] + self.shell_args,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
            )

            # Close slave fd (parent doesn't need it)
            os.close(slave_fd)

            self.master_fd = master_fd
            print_success(f"Started shell: {self.shell_cmd}")
            return master_fd, self.process

        except Exception as e:
            raise TerminalError(f"Failed to start Unix shell: {e}")

    def _start_windows_shell(self) -> Tuple[None, subprocess.Popen]:
        """Start shell on Windows using subprocess."""
        try:
            # For Windows, we use subprocess with pipes
            self.process = subprocess.Popen(
                [self.shell_cmd] + self.shell_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                bufsize=0,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP') else 0,
            )

            print_success(f"Started shell: {self.shell_cmd}")
            return None, self.process

        except Exception as e:
            raise TerminalError(f"Failed to start Windows shell: {e}")

    def forward_to_socket(self, sock: socket.socket) -> None:
        """Forward terminal I/O to a socket connection."""
        if not self.process:
            raise TerminalError("No shell process running")

        try:
            if is_windows():
                self._forward_windows_to_socket(sock)
            else:
                self._forward_unix_to_socket(sock)
        except Exception as e:
            raise TerminalError(f"Terminal forwarding failed: {e}")

    def _forward_unix_to_socket(self, sock: socket.socket) -> None:
        """Forward Unix PTY to socket."""
        if not self.master_fd:
            raise TerminalError("No master fd available")

        stop_event = threading.Event()

        def forward_socket_to_terminal():
            """Forward socket data to terminal."""
            try:
                while not stop_event.is_set():
                    ready, _, _ = select.select([sock], [], [], 0.1)
                    if ready:
                        data = sock.recv(4096)
                        if not data:
                            break
                        os.write(self.master_fd, data)
            except Exception as e:
                print_error(f"Socket to terminal forwarding error: {e}")
            finally:
                stop_event.set()

        def forward_terminal_to_socket():
            """Forward terminal data to socket."""
            try:
                while not stop_event.is_set():
                    ready, _, _ = select.select([self.master_fd], [], [], 0.1)
                    if ready:
                        data = os.read(self.master_fd, 4096)
                        if not data:
                            break
                        sock.send(data)
            except Exception as e:
                print_error(f"Terminal to socket forwarding error: {e}")
            finally:
                stop_event.set()

        # Start forwarding threads
        t1 = threading.Thread(target=forward_socket_to_terminal, daemon=True)
        t2 = threading.Thread(target=forward_terminal_to_socket, daemon=True)

        t1.start()
        t2.start()

        # Wait for process to exit or connection to close
        try:
            while self.process.poll() is None and not stop_event.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            t1.join(timeout=1)
            t2.join(timeout=1)

    def _forward_windows_to_socket(self, sock: socket.socket) -> None:
        """Forward Windows subprocess to socket."""
        if not self.process or not self.process.stdin or not self.process.stdout:
            raise TerminalError("Invalid Windows process state")

        stop_event = threading.Event()

        def forward_socket_to_terminal():
            """Forward socket data to terminal."""
            try:
                while not stop_event.is_set():
                    ready, _, _ = select.select([sock], [], [], 0.1)
                    if ready:
                        data = sock.recv(4096)
                        if not data:
                            break
                        self.process.stdin.write(data)
                        self.process.stdin.flush()
            except Exception as e:
                print_error(f"Socket to terminal forwarding error: {e}")
            finally:
                stop_event.set()

        def forward_terminal_to_socket():
            """Forward terminal data to socket."""
            try:
                while not stop_event.is_set():
                    # Check if data is available
                    if self.process.stdout:
                        data = self.process.stdout.read(4096)
                        if data:
                            sock.send(data)
                        elif self.process.poll() is not None:
                            break
                    time.sleep(0.01)  # Small delay to prevent busy waiting
            except Exception as e:
                print_error(f"Terminal to socket forwarding error: {e}")
            finally:
                stop_event.set()

        # Start forwarding threads
        t1 = threading.Thread(target=forward_socket_to_terminal, daemon=True)
        t2 = threading.Thread(target=forward_terminal_to_socket, daemon=True)

        t1.start()
        t2.start()

        # Wait for process to exit or connection to close
        try:
            while self.process.poll() is None and not stop_event.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            t1.join(timeout=1)
            t2.join(timeout=1)

    def stop(self) -> None:
        """Stop the terminal process."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            except Exception as e:
                print_error(f"Error stopping terminal: {e}")
            finally:
                self.process = None

        if self.master_fd:
            try:
                os.close(self.master_fd)
            except:
                pass
            finally:
                self.master_fd = None

    def is_running(self) -> bool:
        """Check if terminal process is running."""
        return self.process is not None and self.process.poll() is None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()