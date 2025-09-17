"""
Command-line interface for bridgeme
"""

import sys
import signal
import logging
from typing import Optional
import click
from colorama import init, Fore, Style

from . import __version__
from .utils import (
    setup_logging,
    print_status,
    validate_ssh_destination,
    parse_ssh_destination,
    format_connection_string,
    get_platform_info
)
from .session import get_session_manager, shutdown_session_manager
from .shell_server import run_shell_server
from .ssh_relay import SSHRelay, SSHClientRelay
from .exceptions import BridgeMeError, SSHConnectionError, AuthenticationError

# Initialize colorama
init(autoreset=True)

# Global variables for cleanup
current_server = None
current_relay = None
current_client = None


def signal_handler(signum, frame):
    """Handle interrupt signals for graceful shutdown"""
    print_status("\\nReceived interrupt signal, shutting down...", "WARNING")

    # Clean up resources
    if current_server:
        current_server.stop()

    if current_relay:
        current_relay.disconnect()

    if current_client:
        current_client.disconnect()

    shutdown_session_manager()
    sys.exit(0)


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


@click.group(invoke_without_command=True, context_settings={'help_option_names': ['-h', '--help']})
@click.option('--host', help='SSH server to use as relay (host mode)')
@click.option('--username', '-u', help='SSH username')
@click.option('--key-file', '-k', help='SSH private key file')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
@click.option('--debug', is_flag=True, help='Debug output')
@click.option('--version', is_flag=True, help='Show version and exit')
@click.pass_context
def main(ctx, host, username, key_file, verbose, debug, version):
    """
    BridgeMe - SSH relay-based reverse shell tool for IT troubleshooting

    \\b
    Host Mode:
      bridgeme --host SSH_SERVER

    \\b
    Client Mode:
      bridgeme connect SSH_SERVER:PORT

    Examples:
      bridgeme --host user@relay.example.com
      bridgeme connect relay.example.com:12345
    """
    # Show version and exit
    if version:
        platform_info = get_platform_info()
        click.echo(f"bridgeme {__version__}")
        click.echo(f"Platform: {platform_info['platform']}")
        click.echo(f"Python: {platform_info['python_version']}")
        sys.exit(0)

    # Setup logging
    log_level = "DEBUG" if debug else ("INFO" if verbose else "WARNING")
    setup_logging(log_level)

    # If a subcommand is invoked, don't run main logic
    if ctx.invoked_subcommand is not None:
        return

    # If no subcommand and no host, show help
    if not host:
        click.echo(ctx.get_help())
        return

    try:
        # Host mode
        run_host_mode(host, username, key_file, verbose)

    except BridgeMeError as e:
        print_status(f"Error: {e}", "ERROR")
        sys.exit(1)
    except KeyboardInterrupt:
        print_status("\\nOperation cancelled by user", "WARNING")
        sys.exit(1)
    except Exception as e:
        if debug:
            import traceback
            traceback.print_exc()
        print_status(f"Unexpected error: {e}", "ERROR")
        sys.exit(1)


def run_host_mode(ssh_server: str, username: Optional[str], key_file: Optional[str], verbose: bool):
    """Run in host mode - create reverse tunnel and wait for clients"""
    global current_server, current_relay

    print_status("Starting BridgeMe in host mode", "INFO")

    # Validate SSH server
    if not validate_ssh_destination(ssh_server):
        raise BridgeMeError(f"Invalid SSH server format: {ssh_server}")

    parsed_user, hostname, port = parse_ssh_destination(ssh_server)
    effective_username = username or parsed_user or click.prompt("SSH username", type=str)

    print_status(f"Connecting to SSH relay server: {hostname}:{port or 22}", "INFO")

    try:
        # Create session
        session_manager = get_session_manager()
        session = session_manager.create_session(ssh_server, effective_username)

        print_status(f"Created session {session.session_id}", "SUCCESS")

        # Start shell server
        print_status(f"Starting shell server on port {session.host_port}", "INFO")
        current_server = run_shell_server(session)
        current_server.start()

        # Connect to SSH relay
        print_status("Establishing SSH connection...", "INFO")
        current_relay = SSHRelay(ssh_server, effective_username, key_file)
        current_relay.connect()

        # Create reverse tunnel
        print_status("Creating reverse tunnel...", "INFO")
        tunnel = current_relay.create_reverse_tunnel(session)

        # Display connection information
        relay_address = format_connection_string(hostname, tunnel.relay_port, effective_username)
        print_status("Reverse tunnel established successfully!", "SUCCESS")
        print()
        print(f"{Fore.GREEN}╭─ BridgeMe Host Ready ─────────────────────────────╮{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}                                                   {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}  Session ID: {Fore.CYAN}{session.session_id:<35}{Style.RESET_ALL} {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}  Shell Port: {Fore.CYAN}{session.host_port:<35}{Style.RESET_ALL} {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}  Relay Port: {Fore.CYAN}{tunnel.relay_port:<35}{Style.RESET_ALL} {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}                                                   {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}  {Fore.YELLOW}Client command:{Style.RESET_ALL}                              {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}  {Fore.WHITE}bridgeme {relay_address:<29}{Style.RESET_ALL} {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}                                                   {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}╰───────────────────────────────────────────────────╯{Style.RESET_ALL}")
        print()
        print_status("Waiting for client connections... (Press Ctrl+C to stop)", "INFO")

        if verbose:
            print_status("Verbose mode: Will show connection details", "DEBUG")

        # Wait for connections
        current_server.wait_for_connections()

    except AuthenticationError as e:
        raise BridgeMeError(f"SSH authentication failed: {e}")
    except SSHConnectionError as e:
        raise BridgeMeError(f"SSH connection failed: {e}")
    except Exception as e:
        raise BridgeMeError(f"Failed to start host mode: {e}")

    finally:
        # Cleanup
        if current_server:
            current_server.stop()
        if current_relay:
            current_relay.disconnect()


def run_client_mode(destination: str, username: Optional[str], key_file: Optional[str], verbose: bool):
    """Run in client mode - connect to host through relay"""
    global current_client

    print_status("Starting BridgeMe in client mode", "INFO")

    # Parse destination (SSH_SERVER:PORT format)
    if ':' not in destination:
        raise BridgeMeError("Client destination must be in format SSH_SERVER:PORT")

    ssh_server, port_str = destination.rsplit(':', 1)
    try:
        relay_port = int(port_str)
    except ValueError:
        raise BridgeMeError(f"Invalid port number: {port_str}")

    # Validate SSH server
    if not validate_ssh_destination(ssh_server):
        raise BridgeMeError(f"Invalid SSH server format: {ssh_server}")

    parsed_user, hostname, ssh_port = parse_ssh_destination(ssh_server)
    effective_username = username or parsed_user or click.prompt("SSH username", type=str)

    print_status(f"Connecting to relay {hostname}:{relay_port} via SSH {hostname}:{ssh_port or 22}", "INFO")

    try:
        # Create SSH client for relay connection
        current_client = SSHClientRelay(ssh_server, relay_port, effective_username, key_file)
        current_client.connect()

        print_status("Connected to host shell!", "SUCCESS")
        print()
        print(f"{Fore.GREEN}╭─ BridgeMe Client Connected ───────────────────────╮{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}                                                   {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}  Connected to: {Fore.CYAN}{hostname}:{relay_port:<25}{Style.RESET_ALL} {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}  Username: {Fore.CYAN}{effective_username:<33}{Style.RESET_ALL} {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}                                                   {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}  {Fore.YELLOW}You now have shell access to the host system{Style.RESET_ALL}  {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}  {Fore.YELLOW}Type 'exit' or press Ctrl+C to disconnect{Style.RESET_ALL}     {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL}                                                   {Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}╰───────────────────────────────────────────────────╯{Style.RESET_ALL}")
        print()

        # Start interactive session
        current_client.start_forwarding()

    except AuthenticationError as e:
        raise BridgeMeError(f"SSH authentication failed: {e}")
    except SSHConnectionError as e:
        raise BridgeMeError(f"Connection failed: {e}")
    except Exception as e:
        raise BridgeMeError(f"Failed to connect: {e}")

    finally:
        # Cleanup
        if current_client:
            current_client.disconnect()
        print_status("Disconnected from host", "INFO")


@main.command()
@click.argument('destination')
@click.option('--username', '-u', help='SSH username')
@click.option('--key-file', '-k', help='SSH private key file')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def connect(destination, username, key_file, verbose):
    """Connect to host through SSH relay (client mode)"""
    try:
        run_client_mode(destination, username, key_file, verbose)
    except BridgeMeError as e:
        print_status(f"Error: {e}", "ERROR")
        sys.exit(1)
    except KeyboardInterrupt:
        print_status("\\nOperation cancelled by user", "WARNING")
        sys.exit(1)
    except Exception as e:
        print_status(f"Unexpected error: {e}", "ERROR")
        sys.exit(1)


@main.command()
@click.option('--timeout', '-t', default=60, help='Session timeout in minutes')
def status(timeout):
    """Show active sessions and statistics"""
    try:
        session_manager = get_session_manager()
        sessions = session_manager.list_active_sessions()
        stats = session_manager.get_session_stats()

        print(f"{Fore.CYAN}BridgeMe Status{Style.RESET_ALL}")
        print("=" * 50)

        if not sessions:
            print(f"{Fore.YELLOW}No active sessions{Style.RESET_ALL}")
        else:
            print(f"Active Sessions: {len(sessions)}")
            print(f"Allocated Ports: {stats['allocated_ports']}")
            print()

            for session_id, session in sessions.items():
                age_min = session.age_minutes()
                status_color = Fore.GREEN if session.status == "connected" else Fore.YELLOW

                print(f"Session {Fore.CYAN}{session_id}{Style.RESET_ALL}:")
                print(f"  Status: {status_color}{session.status}{Style.RESET_ALL}")
                print(f"  Age: {age_min:.1f} minutes")
                print(f"  Host Port: {session.host_port}")
                if session.relay_port:
                    print(f"  Relay Port: {session.relay_port}")
                if session.ssh_server:
                    print(f"  SSH Server: {session.ssh_server}")
                print()

    except Exception as e:
        print_status(f"Error getting status: {e}", "ERROR")
        sys.exit(1)


@main.command()
@click.argument('session_id', required=False)
@click.option('--all', '-a', is_flag=True, help='Close all sessions')
def close(session_id, all):
    """Close active sessions"""
    try:
        session_manager = get_session_manager()

        if all:
            sessions = session_manager.list_active_sessions()
            for sid in sessions.keys():
                session_manager.close_session(sid)
                print_status(f"Closed session {sid}", "SUCCESS")

            if sessions:
                print_status(f"Closed {len(sessions)} sessions", "SUCCESS")
            else:
                print_status("No active sessions to close", "INFO")

        elif session_id:
            session = session_manager.get_session(session_id)
            if session:
                session_manager.close_session(session_id)
                print_status(f"Closed session {session_id}", "SUCCESS")
            else:
                print_status(f"Session {session_id} not found", "ERROR")
                sys.exit(1)

        else:
            print_status("Either session_id or --all flag is required", "ERROR")
            sys.exit(1)

    except Exception as e:
        print_status(f"Error closing sessions: {e}", "ERROR")
        sys.exit(1)


@main.command()
def version():
    """Show version information"""
    platform_info = get_platform_info()

    print(f"{Fore.CYAN}BridgeMe {__version__}{Style.RESET_ALL}")
    print()
    print(f"Platform: {platform_info['platform']}")
    print(f"Python: {platform_info['python_version']}")
    print(f"Architecture: {platform_info['machine']}")
    print()
    print("SSH relay-based reverse shell tool for IT troubleshooting")


if __name__ == "__main__":
    main()