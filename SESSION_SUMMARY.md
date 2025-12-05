# Sony Automator Controls - Session Summary

## Project Overview

**Name:** Sony Automator Controls
**Version:** 1.0.2 (Current)
**Repository:** https://github.com/BlueElliott/Elliotts-Sony-Automator-Controls

A desktop application that bridges TCP commands to HTTP API calls for Cuez Automator systems. Enables external control systems to trigger Automator macros, deck buttons, and keyboard shortcuts through simple TCP connections.

---

## What's New in v1.0.2 (Current)

### Critical Web GUI Connectivity Fix

**Problem:** Downloaded releases showed "ERR_CONNECTION_REFUSED" when accessing web GUI at http://127.0.0.1:3114

**Root Cause Analysis:**
- Compared with Elliott's Singular Control project (which worked correctly)
- Identified server was binding to `127.0.0.1` (localhost only) instead of `0.0.0.0` (all interfaces)
- Windows firewall/network security was blocking localhost connections in packaged executables

**Solution Implemented:**
1. **Changed Server Binding** - Updated from `host="127.0.0.1"` to `host="0.0.0.0"`
2. **Added psutil Integration** - Automatic port cleanup before server start
3. **Enhanced Server Initialization** - Use `uvicorn.Config()` and `uvicorn.Server()` for advanced control
4. **Port Management Functions**:
   - `is_port_in_use()` - Check if port is occupied
   - `kill_process_on_port()` - Automatically terminate processes using the port

### Files Modified

- `sony_automator_controls/gui_launcher.py` - Server initialization and port management
- `sony_automator_controls/__init__.py` - Version bump to 1.0.2
- `SonyAutomatorControls.spec` - Added psutil to hidden imports

---

## What's in v1.0.1

### Shortcut & Button Trigger Fixes

1. **Shortcut Display Issue**
   - **Problem:** Shortcuts from `/api/trigger/shortcut/` weren't appearing in web GUI
   - **Cause:** API returns shortcuts without `type` or `title` fields
   - **Fix:** Modified `fetch_automator_macros()` to add type and generate display titles from keyboard components
   - **Result:** Shortcuts now display as "Ctrl + Alt + S", "ArrowDown", etc.

2. **TCP Command Mapping Failures**
   - **Problem:** Shortcuts and buttons triggered via TCP commands returned 500 errors
   - **Cause:** All items routed to `/api/macro/{id}` instead of correct endpoints
   - **Fix:** Updated `trigger_automator_macro()` to route based on item type:
     - Macros → `/api/macro/{id}`
     - Buttons → `/api/trigger/button/{id}`
     - Shortcuts → `/api/trigger/shortcut/{id}`

3. **Legacy Config Compatibility**
   - **Problem:** Old config files missing `automator_macro_type` field
   - **Fix:** Added auto-detection in `process_tcp_command()` that looks up type from macro list

### UI Improvements

1. **Searchable Dropdowns** - Replaced `<select>` with `<input>` + `<datalist>` for command mapping
2. **Collapsible Sections** - Macros, buttons, shortcuts default to collapsed state
3. **Search Functionality** - Added search bar to filter across all three item types
4. **Better Labels** - Improved display formatting for shortcuts and buttons

---

## What's in v1.0.0

### Initial Release

1. **TCP to HTTP Bridge**
   - Multi-port TCP listener support
   - Command parsing and routing
   - HTTP request generation to Automator API

2. **Desktop GUI**
   - Tkinter-based interface
   - Matches Elliott's house style
   - ITV Reem font integration
   - System tray support with minimize
   - Console window for debugging

3. **Web Interface**
   - 4 main pages: Home, TCP Commands, Automator Macros, Command Mapping
   - Dark theme matching house style
   - Real-time status monitoring
   - Configuration persistence

4. **Automator Integration**
   - Connect to Cuez Automator via HTTP API
   - Fetch and cache macros, buttons, shortcuts
   - Test triggers directly from UI
   - Command mapping system

5. **Configuration System**
   - JSON-based config storage (`~/.sony_automator_controls/config.json`)
   - Persistent TCP port configurations
   - Command mappings with type awareness
   - Automator connection settings

---

## Repository Structure

```
Elliotts-Sony-Automator-Controls/
├── sony_automator_controls/       # Main Python package
│   ├── __init__.py                # Version: 1.0.2
│   ├── __main__.py                # Entry point
│   ├── core.py                    # FastAPI app, all endpoints, HTML/CSS/JS
│   └── gui_launcher.py            # Desktop GUI with Tkinter
├── static/                        # Static assets
│   ├── sac_icon.ico               # Application icon
│   └── ITV Reem-*.ttf             # Font family (matching Singular Control)
├── tcp_test_client.py             # Standalone TCP testing GUI
├── SonyAutomatorControls.spec     # PyInstaller config for main app
├── TCPTestClient.spec             # PyInstaller config for test client
├── .gitignore
├── pyproject.toml
├── README.md                      # User guide with how-to steps
├── requirements.txt
└── SESSION_SUMMARY.md             # This file
```

---

## Critical Technical Details

### Cuez Automator API Integration

The application integrates with three different Automator API endpoints:

```python
# Macros - Saved sequences
GET  {base_url}/api/macro/
POST {base_url}/api/macro/{id}

# Buttons - Deck button controls
GET  {base_url}/api/trigger/button/
POST {base_url}/api/trigger/button/{id}

# Shortcuts - Keyboard shortcuts
GET  {base_url}/api/trigger/shortcut/
POST {base_url}/api/trigger/shortcut/{id}
```

### Server Binding Configuration

**CRITICAL:** Server must bind to `0.0.0.0` for downloaded executables to work:

```python
# WRONG - Only accessible from same machine via localhost
config = uvicorn.Config(app, host="127.0.0.1", port=3114)

# CORRECT - Accessible from network and localhost
config = uvicorn.Config(app, host="0.0.0.0", port=3114)
```

### Port Management System

```python
def is_port_in_use(port: int) -> bool:
    """Check if port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def kill_process_on_port(port: int) -> bool:
    """Kill any process using the specified port."""
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.connections():
                if conn.laddr.port == port:
                    proc.kill()
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False
```

### Type-Based Routing

```python
async def trigger_automator_macro(macro_id: str, macro_name: str, item_type: str = "macro"):
    """Route to correct Automator endpoint based on type."""
    if item_type == "button":
        endpoint = f"{url}/api/trigger/button/{macro_id}"
    elif item_type == "shortcut":
        endpoint = f"{url}/api/trigger/shortcut/{macro_id}"
    else:  # macro
        endpoint = f"{url}/api/macro/{macro_id}"

    response = requests.post(endpoint, timeout=5)
```

### Shortcut Display Generation

```python
# Shortcuts don't have titles in API, generate from keyboard components
for shortcut in shortcuts:
    shortcut["type"] = "shortcut"

    key_parts = []
    if shortcut.get("control"):
        key_parts.append("Ctrl")
    if shortcut.get("alt"):
        key_parts.append("Alt")
    if shortcut.get("shift"):
        key_parts.append("Shift")
    key_parts.append(shortcut.get("key", "Unknown"))

    shortcut["title"] = " + ".join(key_parts)  # e.g., "Ctrl + Alt + S"
```

---

## Key Files and Their Purposes

### `sony_automator_controls/core.py`

- **Lines 50-120:** Configuration model and server setup
- **Lines 235-295:** `trigger_automator_macro()` - Type-based routing
- **Lines 324-448:** `fetch_automator_macros()` - Fetches and formats items from Automator
- **Lines 180-254:** TCP command processing and mapping logic
- **Lines 500-800:** Web page rendering with embedded HTML/CSS/JS
- **Lines 900-1100:** API endpoints for configuration and control

### `sony_automator_controls/gui_launcher.py`

- **Lines 1-40:** Imports and setup
- **Lines 38-56:** Port management helper functions (NEW in v1.0.2)
- **Lines 447-481:** `start_server()` - Server initialization with auto port cleanup
- **Lines 200-350:** Desktop GUI layout and controls
- **Lines 400-500:** System tray integration

### `tcp_test_client.py`

- Standalone GUI application for testing TCP commands
- Predefined test commands (TEST1, TEST2, CAMERA_ON, etc.)
- Configurable host and port
- Send button with response logging

---

## How to Build Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run in development mode
python -m sony_automator_controls

# Build standalone executables
pyinstaller SonyAutomatorControls.spec
pyinstaller TCPTestClient.spec

# Output files:
# - dist/SonyAutomatorControls-1.0.2.exe
# - dist/TCPTestClient-1.0.0.exe
```

---

## How to Release

1. **Update version** in `sony_automator_controls/__init__.py`
2. **Test locally** - Verify all functionality works
3. **Commit changes:**
   ```bash
   git add -A
   git commit -m "Description of changes"
   ```
4. **Push to main:**
   ```bash
   git push origin main
   ```
5. **Create and push tag:**
   ```bash
   git tag v1.0.2
   git push origin v1.0.2
   ```
6. **Create GitHub Release manually:**
   - Go to https://github.com/BlueElliott/Elliotts-Sony-Automator-Controls/releases/new
   - Select tag v1.0.2
   - Upload executables: `SonyAutomatorControls-1.0.2.exe` and `TCPTestClient-1.0.0.exe`
   - Add release notes

---

## Web Interface URLs

When running locally on port 3114:

- **Home:** http://localhost:3114/
- **TCP Commands:** http://localhost:3114/tcp-commands
- **Automator Macros:** http://localhost:3114/automator-macros
- **Command Mapping:** http://localhost:3114/command-mapping
- **Settings:** http://localhost:3114/settings

---

## Common Issues and Solutions

### Issue: Web GUI shows "Connection Refused"

**Solution:** Ensure you're using v1.0.2 or later. Earlier versions bound to 127.0.0.1 which caused firewall issues in downloaded executables.

### Issue: Shortcuts not appearing in web interface

**Solution:**
- Click "Fetch Automator Items" button
- Check that Automator API is accessible
- Look in "Shortcuts" collapsible section (they have keyboard combinations like "Ctrl + S")

### Issue: TCP commands trigger macros but not shortcuts/buttons

**Solution:**
- Verify command mappings have correct item type
- For old configs, delete and recreate the mapping (auto-detection will fix type)
- Check console logs for routing errors

### Issue: Port already in use

**Solution:** v1.0.2+ automatically kills processes on the port. If issues persist:
- Manually change port in Settings page
- Use Desktop GUI "Change Port" button
- Check for firewall rules blocking the port

### Issue: Automator connection test fails

**Solution:**
- Verify Automator API URL is correct (e.g., http://172.26.6.2)
- Check network connectivity
- Ensure Automator system is running and accessible
- Try accessing the API URL directly in a browser

---

## Version History

### v1.0.2 (2025-12-05)
- **CRITICAL:** Fixed web GUI connectivity in downloaded releases
- Changed server binding from 127.0.0.1 to 0.0.0.0
- Added psutil for automatic port cleanup
- Enhanced server initialization matching Singular Control
- Updated README with simple how-to-use guide

### v1.0.1 (2025-12-05)
- Fixed shortcut display in web GUI
- Fixed TCP command routing for buttons and shortcuts
- Added auto-detection for legacy config files
- Searchable dropdowns for command mapping
- Collapsible sections with search functionality

### v1.0.0 (2025-12-04)
- Initial release
- TCP to HTTP command bridge
- Desktop GUI with system tray
- Web interface with 4 pages
- Automator API integration (macros, buttons, shortcuts)
- Command mapping system
- Configuration persistence
- ITV Reem fonts and branding

---

## Development Notes

### Lessons Learned

1. **Server Binding Matters** - Always use `0.0.0.0` for production apps that need network access
2. **Port Management** - Automatic cleanup prevents "port in use" errors
3. **Type Awareness** - Different Automator endpoints require routing logic
4. **API Response Variations** - Shortcuts lack fields that macros/buttons have (need to generate)
5. **Config Migration** - Auto-detection helps handle legacy configurations gracefully

### Comparison with Elliott's Singular Control

Both projects share:
- Desktop GUI with Tkinter
- FastAPI web backend
- ITV Reem fonts
- System tray support
- Port management
- uvicorn.Config() + uvicorn.Server() pattern
- Host binding to 0.0.0.0

Key differences:
- **Sony Automator:** TCP to HTTP bridge, command mapping focus
- **Singular Control:** Direct Singular.live API integration, TfL/TriCaster modules

---

## Package Naming

- **Python package:** `sony_automator_controls`
- **Executable:** `SonyAutomatorControls-{VERSION}.exe`
- **Test Client:** `TCPTestClient-{VERSION}.exe`
- **Repository:** `Elliotts-Sony-Automator-Controls`
