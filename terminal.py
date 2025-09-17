"""
Cross-platform terminal and shell handling
"""

import os
import sys
import shutil
import subprocess
import threading
import platform
from typing import Optional, List, Tuple, Any
import logging

from .utils import get_platform_info, safe_close
from .exceptions import ShellError

logger = logging.getLogger("bridgeme")


class TerminalHandler:
    """Cross-platform terminal and shell handler"""

    def __init__(self):
        self.platform_info = get_platform_info()
        self.shell_path = self._detect_shell()
        self.shell_args = self._get_shell_args()

    def _detect_shell(self) -> str:
        """Detect the best available shell for the platform"""
        if self.platform_info["is_windows"]:
            return self._detect_windows_shell()
        else:
            return self._detect_unix_shell()

    def _detect_windows_shell(self) -> str:
        """Detect best Windows shell (PowerShell > cmd)"""
        # Try PowerShell Core first (pwsh)
        pwsh_path = shutil.which("pwsh")
        if pwsh_path:
            logger.debug(f"Found PowerShell Core: {pwsh_path}")
            return pwsh_path

        # Try Windows PowerShell
        powershell_path = shutil.which("powershell")
        if powershell_path:
            logger.debug(f"Found Windows PowerShell: {powershell_path}")
            return powershell_path

        # Fall back to cmd
        cmd_path = shutil.which("cmd")
        if cmd_path:
            logger.debug(f"Found cmd: {cmd_path}")
            return cmd_path

        raise ShellError("No suitable shell found on Windows")

    def _detect_unix_shell(self) -> str:
        """Detect best Unix shell (bash > sh)"""
        # Try bash first
        bash_path = shutil.which("bash")
        if bash_path:
            logger.debug(f"Found bash: {bash_path}")
            return bash_path

        # Try zsh
        zsh_path = shutil.which("zsh")
        if zsh_path:
            logger.debug(f"Found zsh: {zsh_path}")
            return zsh_path

        # Fall back to sh
        sh_path = shutil.which("sh")
        if sh_path:
            logger.debug(f"Found sh: {sh_path}")
            return sh_path

        # Try /bin/bash directly
        if os.path.exists("/bin/bash"):
            logger.debug("Found /bin/bash")
            return "/bin/bash"

        # Try /bin/sh directly
        if os.path.exists("/bin/sh"):
            logger.debug("Found /bin/sh")
            return "/bin/sh"

        raise ShellError("No suitable shell found on Unix system")

    def _get_shell_args(self) -> List[str]:
        """Get appropriate arguments for the detected shell"""
        shell_name = os.path.basename(self.shell_path).lower()

        if shell_name in ["powershell.exe", "pwsh.exe", "powershell", "pwsh"]:
            # PowerShell interactive mode
            return ["-NoLogo", "-Interactive"]
        elif shell_name in ["cmd.exe", "cmd"]:
            # Command Prompt interactive mode
            return []
        elif shell_name in ["bash", "zsh", "sh"]:
            # Unix shells interactive mode
            return ["-i"]
        else:
            # Default to no args
            return []

    def get_shell_command(self) -> List[str]:
        """Get the complete shell command to execute"""
        return [self.shell_path] + self.shell_args

    def create_pty_session(self) -> 'PTYSession':
        """Create a PTY session for interactive shell"""
        if self.platform_info["is_windows"]:
            return WindowsPTYSession(self.get_shell_command())
        else:
            return UnixPTYSession(self.get_shell_command())


class PTYSession:
    """Base class for PTY sessions"""

    def __init__(self, shell_command: List[str]):
        self.shell_command = shell_command
        self.process: Optional[subprocess.Popen] = None
        self.is_running = False

    def start(self) -> None:
        """Start the PTY session"""
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        """Write data to the shell"""
        raise NotImplementedError

    def read(self, size: int = 1024) -> bytes:
        """Read data from the shell"""
        raise NotImplementedError

    def close(self) -> None:
        """Close the PTY session"""
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    self.process.kill()
                    self.process.wait(timeout=2)
                except Exception:
                    pass
            finally:
                self.process = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class UnixPTYSession(PTYSession):
    """Unix PTY session using pty module"""

    def __init__(self, shell_command: List[str]):
        super().__init__(shell_command)
        self.master_fd: Optional[int] = None
        self.slave_fd: Optional[int] = None

    def start(self) -> None:
        """Start the Unix PTY session"""
        try:
            import pty
            import os

            # Create PTY
            self.master_fd, self.slave_fd = pty.openpty()

            # Start shell process
            self.process = subprocess.Popen(
                self.shell_command,
                stdin=self.slave_fd,
                stdout=self.slave_fd,
                stderr=self.slave_fd,
                start_new_session=True,
                preexec_fn=os.setsid
            )

            self.is_running = True
            logger.debug(f"Started Unix PTY session with command: {' '.join(self.shell_command)}")

        except Exception as e:
            self.close()
            raise ShellError(f"Failed to start Unix PTY session: {e}")

    def write(self, data: bytes) -> None:
        """Write data to the shell"""
        if not self.is_running or self.master_fd is None:
            raise ShellError("PTY session not running")

        try:
            os.write(self.master_fd, data)
        except OSError as e:
            raise ShellError(f"Failed to write to PTY: {e}")

    def read(self, size: int = 1024) -> bytes:
        """Read data from the shell"""
        if not self.is_running or self.master_fd is None:
            raise ShellError("PTY session not running")

        try:
            return os.read(self.master_fd, size)
        except OSError as e:
            if e.errno == 5:  # EIO - End of file
                return b""
            raise ShellError(f"Failed to read from PTY: {e}")

    def close(self) -> None:
        """Close the Unix PTY session"""
        super().close()

        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

        if self.slave_fd is not None:
            try:
                os.close(self.slave_fd)
            except OSError:
                pass
            self.slave_fd = None


class WindowsPTYSession(PTYSession):
    """Windows PTY session using subprocess with PIPE"""

    def __init__(self, shell_command: List[str]):
        super().__init__(shell_command)

    def start(self) -> None:
        """Start the Windows PTY session"""
        try:
            # Try to use winpty if available for better terminal support
            if self._try_winpty():
                return

            # Fall back to regular subprocess
            self.process = subprocess.Popen(
                self.shell_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=False,
                bufsize=0,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )

            self.is_running = True
            logger.debug(f"Started Windows PTY session with command: {' '.join(self.shell_command)}")

        except Exception as e:
            self.close()
            raise ShellError(f"Failed to start Windows PTY session: {e}")

    def _try_winpty(self) -> bool:
        """Try to use winpty for better Windows terminal support"""
        try:
            import winpty

            # Create winpty process
            self.winpty_proc = winpty.PtyProcess.spawn(
                ' '.join(self.shell_command),
                dimensions=(80, 24)
            )

            self.is_running = True
            logger.debug("Started Windows PTY session with winpty")
            return True

        except ImportError:
            logger.debug("winpty not available, falling back to subprocess")
            return False
        except Exception as e:
            logger.debug(f"Failed to start winpty session: {e}")
            return False

    def write(self, data: bytes) -> None:
        """Write data to the shell"""
        if not self.is_running:
            raise ShellError("PTY session not running")

        try:
            if hasattr(self, 'winpty_proc'):
                # Use winpty
                self.winpty_proc.write(data.decode('utf-8', errors='ignore'))
            elif self.process and self.process.stdin:
                # Use subprocess
                self.process.stdin.write(data)
                self.process.stdin.flush()
        except Exception as e:
            raise ShellError(f"Failed to write to PTY: {e}")

    def read(self, size: int = 1024) -> bytes:
        """Read data from the shell"""
        if not self.is_running:
            raise ShellError("PTY session not running")

        try:
            if hasattr(self, 'winpty_proc'):
                # Use winpty
                data = self.winpty_proc.read(size, blocking=False)
                return data.encode('utf-8', errors='ignore')
            elif self.process and self.process.stdout:
                # Use subprocess
                return self.process.stdout.read(size)
            else:
                return b""
        except Exception as e:
            if "timeout" in str(e).lower():
                return b""
            raise ShellError(f"Failed to read from PTY: {e}")

    def close(self) -> None:
        """Close the Windows PTY session"""
        super().close()

        if hasattr(self, 'winpty_proc'):
            try:
                self.winpty_proc.terminate()
            except Exception:
                pass


def create_terminal_handler() -> TerminalHandler:
    """Factory function to create a terminal handler"""
    return TerminalHandler()


def get_available_shells() -> List[str]:
    """Get list of available shells on the system"""
    handler = TerminalHandler()
    shells = []

    if handler.platform_info["is_windows"]:
        # Windows shells
        for shell in ["pwsh", "powershell", "cmd"]:
            path = shutil.which(shell)
            if path:
                shells.append(path)
    else:
        # Unix shells
        for shell in ["bash", "zsh", "sh"]:
            path = shutil.which(shell)
            if path:
                shells.append(path)

        # Check common paths
        for path in ["/bin/bash", "/bin/zsh", "/bin/sh"]:
            if os.path.exists(path) and path not in shells:
                shells.append(path)

    return shells


if __name__ == "__main__":
    # Test the terminal handler
    print("Available shells:", get_available_shells())

    handler = create_terminal_handler()
    print("Selected shell:", handler.shell_path)
    print("Shell command:", handler.get_shell_command())