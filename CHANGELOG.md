# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2024-09-17

### Added
- Initial release of BridgeMe
- SSH relay-based reverse shell functionality for IT troubleshooting
- Cross-platform support (Windows, macOS, Linux)
- Auto-shell detection (PowerShell/cmd/bash/zsh)
- SSH key authentication support
- Session management with auto-generated ports
- Graceful error handling and user feedback
- Support for reconnection if client disconnects
- Multiple concurrent troubleshooting sessions
- Command-line interface with Click
- Comprehensive documentation and README

### Features
- **Host mode**: `bridgeme --host user@ssh-server.com`
  - Creates reverse SSH tunnel through relay server
  - Auto-generates session ports
  - Provides client connection command
  - Waits for client connections

- **Client mode**: `bridgeme connect ssh-server.com:PORT`
  - Connects through SSH relay to host session
  - Forwards local terminal to host
  - Shows connection status and disconnect handling

- **Session management**:
  - `bridgeme status` - Show active sessions
  - `bridgeme close --all` - Close all sessions
  - Auto-cleanup of stale sessions

### Technical Details
- Python 3.8+ support
- Dependencies: paramiko, click, psutil, colorama
- Cross-platform terminal handling with PTY/subprocess
- Secure SSH tunnel communication
- Session isolation and management
- Comprehensive error handling

### Security
- Only troubleshooter needs SSH credentials
- All communication encrypted through SSH tunnels
- Sessions are isolated and automatically cleaned up
- No permanent access granted to client machines

[0.1.0]: https://github.com/yourusername/bridgeme/releases/tag/v0.1.0