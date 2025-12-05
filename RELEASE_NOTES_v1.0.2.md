# Sony Automator Controls v1.0.2 - Release Notes

## Critical Fix: Web GUI Connectivity Issue Resolved

This release resolves the **"ERR_CONNECTION_REFUSED"** issue that prevented the web GUI from loading when running downloaded executables.

---

## What's Fixed

### Web GUI Connectivity (CRITICAL)

**Problem:** Users downloading the v1.0.0 or v1.0.1 releases experienced connection failures when trying to access the web interface at `http://127.0.0.1:3114`.

**Root Cause:** The server was binding to `127.0.0.1` (localhost loopback only) instead of `0.0.0.0` (all network interfaces). This caused Windows firewall and network security to block connections in packaged executables.

**Solution:** After comparing with the working Elliott's Singular Control project, we implemented the same robust server initialization approach:

1. **Changed server binding from `127.0.0.1` to `0.0.0.0`** ← PRIMARY FIX
2. **Added psutil for automatic port cleanup** - Kills existing processes on the port before starting
3. **Enhanced server initialization** - Uses `uvicorn.Config()` and `uvicorn.Server()` for advanced control
4. **Port management helpers** - `is_port_in_use()` and `kill_process_on_port()` functions

---

## Technical Changes

### Modified Files

- **sony_automator_controls/gui_launcher.py**
  - Added `import psutil`
  - Added `is_port_in_use()` helper function
  - Added `kill_process_on_port()` helper function
  - Updated `start_server()` method to use `host="0.0.0.0"`
  - Implemented automatic port cleanup before server start

- **sony_automator_controls/__init__.py**
  - Version bumped to `1.0.2`

- **SonyAutomatorControls.spec**
  - Added `'psutil'` to `hiddenimports` list

### Code Example

```python
# Before (v1.0.0 - v1.0.1) - BROKEN
uvicorn.run(core.app, host="127.0.0.1", port=self.server_port)

# After (v1.0.2) - FIXED
config = uvicorn.Config(
    core.app,
    host="0.0.0.0",  # ← Key change
    port=self.server_port,
    log_level="info"
)
server = uvicorn.Server(config)
server.run()
```

---

## Downloads

This release includes two executables:

1. **SonyAutomatorControls-1.0.2.exe** (Main Application)
   - Desktop GUI with system tray support
   - Web interface on port 3114
   - TCP command listener
   - Automator API integration

2. **TCPTestClient-1.0.0.exe** (Testing Tool)
   - Send test TCP commands
   - Configure host and port
   - Predefined test commands
   - Response logging

---

## Installation & Usage

### Quick Start

1. Download `SonyAutomatorControls-1.0.2.exe`
2. Double-click to run
3. Desktop GUI opens automatically
4. Click "Open Web GUI" to access control panel at `http://localhost:3114`

### First-Time Setup

1. Go to **Settings** page
2. Enable "Automator Integration"
3. Enter your Automator API URL (e.g., `http://172.26.6.2`)
4. Click "Test Connection"
5. Click "Save Settings"

See [README.md](README.md) for complete step-by-step guide.

---

## Upgrade Notes

### From v1.0.0 or v1.0.1

- **Configuration preserved** - Your settings will carry over automatically
- **No migration needed** - Just replace the executable
- **Same port (3114)** - No changes to existing integrations
- **Backward compatible** - All command mappings work exactly the same

### Breaking Changes

None. This is a drop-in replacement for v1.0.0 and v1.0.1.

---

## Testing Checklist

Before releasing, the following were verified:

- ✅ Web GUI accessible at `http://localhost:3114`
- ✅ Web GUI accessible via network IP (e.g., `http://172.26.6.x:3114`)
- ✅ Desktop GUI launches successfully
- ✅ System tray functionality works
- ✅ Automator connection test succeeds
- ✅ TCP command listeners start on configured ports
- ✅ Command mappings trigger correct Automator actions
- ✅ Macros, buttons, and shortcuts all route correctly
- ✅ Port cleanup kills existing processes automatically
- ✅ Configuration persists between restarts

---

## Known Issues

None at this time.

---

## Documentation

- **README.md** - Complete user guide with step-by-step setup
- **SESSION_SUMMARY.md** - Technical details, version history, developer notes

---

## Acknowledgments

This fix was implemented by analyzing and copying the working approach from **Elliott's Singular Control** project, which uses the same architecture but doesn't experience connectivity issues.

---

## Support

If you encounter issues:

1. Check [README.md](README.md) troubleshooting section
2. Review [SESSION_SUMMARY.md](SESSION_SUMMARY.md) for technical details
3. Open an issue at https://github.com/BlueElliott/Elliotts-Sony-Automator-Controls/issues

---

**Built with:** Python 3.13, FastAPI, Uvicorn, Tkinter, psutil
**Release Date:** December 5, 2025
**Made with care by BlueElliott**
