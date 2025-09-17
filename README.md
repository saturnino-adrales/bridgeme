# BridgeMe

SSH relay-based reverse shell tool for IT troubleshooting.

## Overview

BridgeMe allows IT administrators to troubleshoot remote machines through an SSH relay server, eliminating the need for multiple users to have SSH access. Only the troubleshooter needs SSH credentials - clients connect through a simple Python tool.

## Installation

```bash
pip install bridgeme
```

## Quick Start

### Host Mode (Troubleshooter)

```bash
# Connect to your SSH relay server and create tunnel
bridgeme --host user@relay.example.com

# Output:
# ╭─ BridgeMe Host Ready ─────────────────────────────╮
# │  Session ID: abc123de                             │
# │  Client command:                                  │
# │  bridgeme connect relay.example.com:12345         │
# ╰───────────────────────────────────────────────────╯
```

### Client Mode (Machine needing help)

```bash
# Run the command provided by the host
bridgeme connect relay.example.com:12345

# Output:
# ╭─ BridgeMe Client Connected ───────────────────────╮
# │  Host is now controlling your terminal            │
# ╰───────────────────────────────────────────────────╯
```

## Features

- **Cross-platform**: Works on Windows, macOS, and Linux
- **Auto-shell detection**: Automatically uses PowerShell, cmd, bash, or zsh
- **SSH key support**: Uses existing SSH keys and SSH agent
- **Session management**: Multiple concurrent troubleshooting sessions
- **Reconnection support**: Clients can reconnect if disconnected
- **Graceful error handling**: Clear error messages and connection status

## Architecture

```
[Client Machine] ←→ [SSH Relay Server] ←→ [Troubleshooter Machine]
     bridgeme              tunnel              bridgeme --host
```

1. **Host** runs `bridgeme --host SSH_SERVER` - creates reverse tunnel
2. **Client** runs `bridgeme connect SSH_SERVER:PORT` - connects through tunnel
3. **Result**: Host gets terminal access to client machine for troubleshooting

## Commands

### Host Commands

```bash
# Start host mode
bridgeme --host username@relay.example.com
bridgeme host relay.example.com --port 2222 --username admin

# Show status
bridgeme status

# Close sessions
bridgeme close --all
bridgeme close abc123de
```

### Client Commands

```bash
# Connect to host
bridgeme connect relay.example.com:12345
```

### Utility Commands

```bash
# Show version
bridgeme --version

# Show help
bridgeme --help
```

## Requirements

- Python 3.8+
- SSH access to a relay server (host only)
- Network connectivity between all machines

## Dependencies

- `paramiko>=2.7.0` - SSH client functionality
- `click>=7.0` - CLI interface
- `psutil>=5.0.0` - System information
- `colorama>=0.4.0` - Cross-platform colors

### Optional Dependencies

- `pywinpty>=1.1.0` - Better Windows terminal support

Install with: `pip install bridgeme[windows]`

## Security Considerations

- Only the troubleshooter needs SSH credentials
- All communication is encrypted through SSH tunnels
- Sessions are isolated and automatically cleaned up
- No permanent access is granted to client machines

## Troubleshooting

### Connection Issues

If connection fails:

1. **Verify SSH access**: Ensure you can SSH to the relay server manually
2. **Check SSH keys**: Use `ssh-add -l` to verify SSH agent has keys
3. **Network connectivity**: Ensure all machines can reach the relay server
4. **Firewall settings**: Check that required ports are not blocked

### Common Error Messages

- `Authentication failed`: SSH keys not properly configured
- `Connection refused`: Relay server not reachable or SSH service down
- `Port allocation failed`: Too many concurrent sessions (restart)

## Development

```bash
# Clone repository
git clone https://github.com/yourusername/bridgeme.git
cd bridgeme

# Install in development mode
pip install -e .

# Install development dependencies
pip install -e .[dev]

# Run tests
pytest
```

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## Support

For issues and questions:

- Create an issue on GitHub
- Check existing issues for solutions
- Review troubleshooting section above