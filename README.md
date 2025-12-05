# Sony Automator Controls

TCP to HTTP command bridge for Sony Automator devices. Receives TCP commands and triggers HTTP API calls to your Automator system.

## Features

- **TCP Command Listener** - Listen on multiple configurable TCP ports for incoming commands
- **HTTP API Integration** - Trigger Automator macros and shortcuts via HTTP
- **Command Mapping** - Map TCP commands to Automator macros through intuitive web interface
- **Desktop GUI** - Tkinter-based desktop application matching Elliott's house style
- **Web Interface** - Full-featured web GUI for configuration and monitoring
- **System Tray Support** - Run minimized in system tray

## Installation

### Requirements

- Python 3.8 or higher
- pip

### Install Dependencies

```bash
pip install -r requirements.txt
```

## Usage

### Run with GUI

```bash
python -m sony_automator_controls
```

### Run Server Only (No GUI)

```bash
python -m sony_automator_controls --no-gui --port 3114
```

## Configuration

Configuration is stored in `~/.sony_automator_controls/config.json`

### TCP Listeners

Configure which ports to listen for incoming TCP commands on the **TCP Commands** page.

### Automator Integration

1. Go to the **Automator Macros** page
2. Enter your Automator API URL
3. Add API key if required
4. Enable integration
5. Test connection

### Command Mapping

Map TCP commands to Automator macros on the **Command Mapping** page:

1. Create TCP commands on the **TCP Commands** page
2. Configure Automator integration
3. Go to **Command Mapping** page
4. Link TCP commands to Automator macros

## Testing

### Test TCP Commands

Send TCP commands to test:

```bash
# Windows
echo "TEST1" | ncat localhost 9001

# Linux/Mac
echo "TEST1" | nc localhost 9001
```

### Test HTTP Integration

Use the test buttons in the web interface to manually trigger Automator macros.

## Building Executable

### Install PyInstaller

```bash
pip install pyinstaller
```

### Build the Executable

```bash
python -m PyInstaller SonyAutomatorControls.spec
```

The executable will be in the `dist/` folder as `SonyAutomatorControls-1.0.0.exe`.

### Running the Executable

Simply double-click `SonyAutomatorControls-1.0.0.exe` to launch the application with the GUI. The application will:
- Start the web server on the configured port (default: 3114)
- Open the desktop GUI with system tray support
- Begin listening for TCP commands on configured ports

You can also run it from command line:

```bash
# Run with GUI (default)
.\dist\SonyAutomatorControls-1.0.0.exe

# Run without GUI (server only)
.\dist\SonyAutomatorControls-1.0.0.exe --no-gui

# Run on custom port
.\dist\SonyAutomatorControls-1.0.0.exe --port 8080
```

## Web Interface

Access the web interface at `http://localhost:3114`

### Pages

- **Home** - Dashboard showing connection status
- **TCP Commands** - Manage TCP command definitions
- **Automator Macros** - Configure Automator integration and view macros
- **Command Mapping** - Map TCP commands to Automator macros

## Architecture

```
TCP Client → TCP Server → Command Parser → HTTP Client → Automator API
                ↓
           Web Interface (Monitoring & Configuration)
                ↓
         Desktop GUI (System Tray Control)
```

## License

Copyright © Elliott. All rights reserved.

## Version

1.0.0
