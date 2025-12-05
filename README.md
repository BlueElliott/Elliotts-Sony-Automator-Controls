# Sony Automator Controls

> **TCP to HTTP command bridge for Sony Automator devices**

A desktop application that receives TCP commands and triggers HTTP API calls to your Cuez Automator system. Perfect for integrating external control systems with Automator macros, buttons, and keyboard shortcuts.

## Quick Start

### Windows Executable (Easiest)

1. Download `SonyAutomatorControls-1.0.2.exe` from [Releases](https://github.com/BlueElliott/Elliotts-Sony-Automator-Controls/releases)
2. Double-click to run - no installation needed!
3. The desktop GUI will open and the web interface is available at `http://localhost:3114`

### Python Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Run with GUI
python -m sony_automator_controls

# Run server only (no GUI)
python -m sony_automator_controls --no-gui --port 3114
```

## Features

- **TCP Command Listener** - Listen on multiple TCP ports for incoming commands
- **HTTP API Bridge** - Trigger Automator macros, buttons, and shortcuts via HTTP
- **Command Mapping** - Map TCP commands to Automator actions through web interface
- **Desktop GUI** - Clean interface matching Elliott's house style with ITV Reem fonts
- **Web Interface** - Full-featured control panel with live status monitoring
- **System Tray Support** - Minimize to tray for background operation

## How to Use

### Step 1: Configure Automator Connection

1. Open the web interface at `http://localhost:3114`
2. Go to **Settings** page
3. Enable "Automator Integration"
4. Enter your Automator API URL (e.g., `http://172.26.6.2`)
5. Click "Test Connection" to verify
6. Click "Save Settings"

### Step 2: View Available Actions

1. Go to **Automator Macros** page
2. Click "Fetch Automator Items" to load available:
   - **Macros** - Saved macro sequences
   - **Buttons** - Deck button controls
   - **Shortcuts** - Keyboard shortcut triggers
3. Click the test button next to any item to trigger it manually

### Step 3: Configure TCP Listeners

1. Go to **TCP Commands** page
2. Add TCP ports you want to listen on (e.g., 9001, 9002, 9003)
3. Define command names (e.g., "CAMERA_ON", "VT_PLAY", "GRAPHICS_1")
4. Save your commands

### Step 4: Map Commands to Automator Actions

1. Go to **Command Mapping** page
2. Select a TCP command from the dropdown
3. Search and select the Automator action to trigger
4. Click "Add Mapping"
5. Test using the "Test TCP Command" button

### Step 5: Send Commands

Send TCP commands from your control system:

```bash
# Example using netcat (Windows)
echo "CAMERA_ON" | ncat localhost 9001

# Example using netcat (Linux/Mac)
echo "CAMERA_ON" | nc localhost 9001
```

Or use the included **TCP Test Client** (`TCPTestClient-1.0.0.exe`) to send test commands with a GUI.

## Web Interface Pages

| Page | URL | Description |
|------|-----|-------------|
| Home | `http://localhost:3114/` | Status dashboard |
| TCP Commands | `http://localhost:3114/tcp-commands` | Manage TCP ports and command definitions |
| Automator Macros | `http://localhost:3114/automator-macros` | View and test macros, buttons, shortcuts |
| Command Mapping | `http://localhost:3114/command-mapping` | Link TCP commands to Automator actions |
| Settings | `http://localhost:3114/settings` | Configure Automator connection and port |

## Desktop Application

The desktop GUI provides:

- **Server Status** - Visual indicator shows server running state
- **Web GUI Access** - Click "Open Web GUI" to launch browser
- **Port Configuration** - Change server port
- **Console View** - Toggle server logs for debugging
- **System Tray** - Minimize to tray with right-click menu

## Configuration

Settings are saved to `~/.sony_automator_controls/config.json`:

```json
{
  "server_port": 3114,
  "automator_url": "http://172.26.6.2",
  "automator_enabled": true,
  "tcp_ports": [9001, 9002, 9003],
  "tcp_commands": {...},
  "command_mappings": {...}
}
```

## Building from Source

```bash
# Install PyInstaller
pip install pyinstaller

# Build main application
python -m PyInstaller SonyAutomatorControls.spec
# Output: dist/SonyAutomatorControls-1.0.2.exe

# Build TCP test client
python -m PyInstaller TCPTestClient.spec
# Output: dist/TCPTestClient-1.0.0.exe
```

## Troubleshooting

**Web GUI shows "Connection Refused"?**
- Make sure you downloaded the latest v1.0.2 release
- The server should bind to all network interfaces (0.0.0.0)

**Port already in use?**
- Change the port in Settings or Desktop GUI
- The app will automatically kill processes on the port before starting

**Automator connection fails?**
- Verify the Automator API URL is correct
- Check network connectivity to the Automator system
- Use "Test Connection" button to diagnose

**TCP commands not triggering?**
- Verify command mappings are configured correctly
- Check that TCP ports are listening (shown on TCP Commands page)
- Use TCP Test Client to verify commands work
- Check console logs for errors

**Shortcuts/Buttons not appearing?**
- Make sure you clicked "Fetch Automator Items"
- Check that Automator API is responding
- Look for shortcuts in the "Shortcuts" section (they have keyboard combinations)

## Version History

### v1.0.2 (Current)
- **CRITICAL FIX:** Changed server binding from 127.0.0.1 to 0.0.0.0 (resolves web GUI connectivity)
- Added psutil for automatic port cleanup
- Enhanced server initialization matching Elliott's Singular Control
- Automatic process killing on port before starting

### v1.0.1
- Fixed shortcut/button triggers via TCP commands
- Added auto-detection of item types for command mappings
- Better display formatting for shortcuts
- Improved error handling

### v1.0.0
- Initial release
- TCP to HTTP command bridge
- Desktop GUI with system tray
- Web interface with 4 pages
- Automator API integration
- Command mapping system
- ITV Reem fonts and branding

## Architecture

```
TCP Client → TCP Listener → Command Mapper → HTTP Client → Cuez Automator API
                                ↓
                         Web Interface (Config & Monitoring)
                                ↓
                          Desktop GUI (Control)
```

## License

Copyright © Elliott. All rights reserved.

## Support

- **Issues**: [GitHub Issues](https://github.com/BlueElliott/Elliotts-Sony-Automator-Controls/issues)

---

**Made with care by BlueElliott**
