"""Command-line interface for BridgeMe."""

import signal
import sys
import threading
import time
from typing import Optional

import click

from . import __version__
from .exceptions import BridgeMeError, SSHConnectionError, TunnelError, SessionError
from .session import session_manager
from .ssh_relay import SSHRelay
from .terminal import TerminalHandler
from .utils import (
    print_box,
    print_error,
    print_info,
    print_success,
    print_warning
)


def signal_handler(signum, frame):
    """Handle interrupt signals gracefully."""
    print_info("\nShutting down BridgeMe...")
    session_manager.close_all_sessions()
    sys.exit(0)


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


@click.group(invoke_without_command=True)
@click.option("--host", help="SSH relay hostname for host mode")
@click.option("--version", is_flag=True, help="Show version and exit")
@click.pass_context
def main(ctx, host: Optional[str], version: bool):
    """BridgeMe: SSH relay-based reverse shell tool for IT troubleshooting."""
    if version:
        click.echo(f"BridgeMe version {__version__}")
        return

    if host:
        # Host mode
        ctx.invoke(host_mode, hostname=host)
    elif ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command("host")
@click.argument("hostname")
@click.option("--port", default=22, help="SSH port (default: 22)")
@click.option("--username", help="SSH username (default: current user)")
def host_mode(hostname: str, port: int, username: Optional[str]):
    """Start BridgeMe in host mode - creates tunnel and waits for client."""
    try:
        # Parse username from hostname if provided (user@host format)
        if "@" in hostname and username is None:
            username, hostname = hostname.split("@", 1)

        print_info(f"Starting BridgeMe host mode...")
        print_info(f"Target SSH server: {username}@{hostname}:{port}" if username else f"Target SSH server: {hostname}:{port}")

        # Create session
        session = session_manager.create_session(hostname)
        session.host_connected = True

        # Connect to SSH relay
        with SSHRelay(hostname, port, username) as relay:
            relay.connect()

            # Start local shell server
            with TerminalHandler() as terminal:
                print_info("Starting local shell server...")

                # Start shell
                master_fd, process = terminal.start_shell()

                # Create reverse tunnel
                relay.create_reverse_tunnel(session.port, session.port)

                # Show connection info
                client_command = session.get_client_command()
                print_box(
                    "BridgeMe Host Ready",
                    f"Session ID: {session.id}\n"
                    f"Client command:\n"
                    f"{client_command}\n\n"
                    f"Waiting for client connection..."
                )

                # Wait for client connection
                print_info("Server now blocked and waiting for connection...")

                # Start shell server
                start_shell_server(terminal, session.port)

    except KeyboardInterrupt:
        print_info("Host mode interrupted by user")
    except BridgeMeError as e:
        print_error(f"BridgeMe error: {e}")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        sys.exit(1)
    finally:
        if 'session' in locals():
            session_manager.close_session(session.id)


@main.command("connect")
@click.argument("target")
def client_mode(target: str):
    """Connect to BridgeMe host (client mode)."""
    try:
        # Parse target (hostname:port)
        if ":" not in target:
            print_error("Target must be in format hostname:port")
            sys.exit(1)

        hostname, port_str = target.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            print_error("Invalid port number")
            sys.exit(1)

        print_info(f"Connecting to host...")
        print_info(f"Target: {hostname}:{port}")

        # Connect to host via SSH relay
        start_client_connection(hostname, port)

    except KeyboardInterrupt:
        print_info("Client mode interrupted by user")
    except BridgeMeError as e:
        print_error(f"BridgeMe error: {e}")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        sys.exit(1)


@main.command("status")
def status():
    """Show status of active sessions."""
    sessions = session_manager.list_sessions()

    if not sessions:
        print_info("No active sessions")
        return

    print_info(f"Active sessions ({len(sessions)}):")
    for session in sessions.values():
        status_str = "🟢 Active" if session.client_connected and session.host_connected else "🟡 Waiting"
        print(f"  {session} - {status_str}")


@main.command("close")
@click.option("--all", "close_all", is_flag=True, help="Close all sessions")
@click.argument("session_id", required=False)
def close_session(close_all: bool, session_id: Optional[str]):
    """Close active session(s)."""
    if close_all:
        session_manager.close_all_sessions()
        print_success("All sessions closed")
    elif session_id:
        session = session_manager.get_session(session_id)
        if session:
            session_manager.close_session(session_id)
            print_success(f"Session {session_id} closed")
        else:
            print_error(f"Session {session_id} not found")
    else:
        print_error("Specify --all or provide session_id")


def start_shell_server(terminal: TerminalHandler, port: int):
    """Start shell server that listens for client connections."""
    import socket

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind(("localhost", port))
        server_socket.listen(1)
        server_socket.settimeout(1.0)  # Allow interruption

        print_info(f"Shell server listening on localhost:{port}")

        while True:
            try:
                client_socket, client_address = server_socket.accept()
                print_success("Great! You are now connected to the client")
                print_success("Your terminal is here.")

                # Forward terminal to client
                terminal.forward_to_socket(client_socket)

                print_info("Client disconnected")
                print_info("Waiting for reconnection or press Ctrl+C to exit...")

            except socket.timeout:
                continue
            except KeyboardInterrupt:
                break
            except Exception as e:
                print_error(f"Server error: {e}")
                break

    finally:
        server_socket.close()


def start_client_connection(hostname: str, port: int):
    """Start client connection to host."""
    import socket

    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            print_info(f"Connecting to host... (attempt {attempt + 1}/{max_retries})")

            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((hostname, port))

            print_success("Connected")
            print_box(
                "BridgeMe Client Connected",
                "Host is now controlling your terminal, wait until host disconnects."
            )

            # Start terminal and forward to host
            with TerminalHandler() as terminal:
                master_fd, process = terminal.start_shell()
                terminal.forward_to_socket(client_socket)

            break

        except ConnectionRefusedError:
            print_warning(f"Connection refused. Retrying in {retry_delay} seconds...")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                print_error("Failed to connect after all retries")
                print_error("Server disconnected, please run the command again or contact the Host user")
                sys.exit(1)

        except Exception as e:
            print_error(f"Connection error: {e}")
            if attempt < max_retries - 1:
                print_info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print_error("Server disconnected, please run the command again or contact the Host user")
                sys.exit(1)

        finally:
            try:
                client_socket.close()
            except:
                pass


if __name__ == "__main__":
    main()