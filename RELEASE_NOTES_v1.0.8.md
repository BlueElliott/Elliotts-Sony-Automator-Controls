# Sony Automator Controls v1.0.8 - Release Notes

## Comprehensive Logging System for Troubleshooting

This release adds **persistent file-based logging** with export capabilities to help diagnose issues on remote PCs.

---

## What's New

### Persistent File Logging

**Problem:** Console logs were lost when the window was closed, making it difficult to diagnose issues on remote PCs.

**Solution:** All logs are now automatically saved to rotating log files that persist across sessions.

**Log File Location:**
- Windows: `C:\Users\{username}\.sony_automator_controls\logs\sony_automator_controls.log`
- The path is also displayed in the desktop GUI

**Features:**
- **Rotating Files:** Automatic rotation when file reaches 5MB
- **Keep Last 5:** Maintains last 5 log files automatically
- **Dual Logging:** Logs to both console AND file simultaneously
- **Always Available:** Logs persist even if console window is closed

---

## New API Endpoints

### Export Logs
```
GET /logs/export
```
Downloads the complete log file with a timestamped filename.

**Example:**
```
http://localhost:3114/logs/export
```
Downloads: `sony_automator_controls_20251208_152000.log`

### View Logs in Browser
```
GET /logs/view?lines=500
```
View the last N lines of the log file directly in your browser.

**Examples:**
```
http://localhost:3114/logs/view          # Last 500 lines (default)
http://localhost:3114/logs/view?lines=1000  # Last 1000 lines
http://localhost:3114/logs/view?lines=100   # Last 100 lines
```

**Response:**
```json
{
  "log_file": "C:\\Users\\...\\sony_automator_controls.log",
  "total_lines": 2547,
  "showing_lines": 500,
  "logs": "2025-12-08 15:21:00 - INFO - Starting server...\n..."
}
```

### Health Check Enhanced
```
GET /health
```
Now includes the log file path in the response.

**Response:**
```json
{
  "status": "ok",
  "version": "1.0.8",
  "port": 3114,
  "log_file": "C:\\Users\\username\\.sony_automator_controls\\logs\\sony_automator_controls.log"
}
```

---

## How to Use

### Export Logs for Troubleshooting

1. **Via Browser:**
   - Navigate to `http://localhost:3114/logs/export`
   - Log file automatically downloads

2. **Via Direct File Access:**
   - Open File Explorer
   - Navigate to `C:\Users\{your-username}\.sony_automator_controls\logs\`
   - Open `sony_automator_controls.log` in any text editor

3. **View in Browser:**
   - Go to `http://localhost:3114/logs/view`
   - See last 500 lines of logs
   - Copy/paste for sharing

### Log File Contents

The log file includes:
- Server startup/shutdown events
- TCP command received and processed
- HTTP requests to Automator API
- Mapping lookups and triggers
- Error messages and warnings
- Connection status changes

**Example Log Entries:**
```
2025-12-08 15:21:00,613 - INFO - Starting Sony Automator Controls...
2025-12-08 15:21:00,653 - INFO - TCP Server: Started on port 9001
2025-12-08 15:21:32,304 - INFO - TCP Command: Received 'TEST2' on port 9001
2025-12-08 15:21:32,305 - INFO - Mapping Found: Test Command 2 → ArrowDown
2025-12-08 15:21:32,305 - INFO - HTTP Trigger: Calling shortcut: ArrowDown
2025-12-08 15:21:32,948 - INFO - HTTP Success: Triggered shortcut: ArrowDown
```

---

## Technical Changes

### Logging Configuration
- Added `RotatingFileHandler` with 5MB max size
- Keep last 5 rotated log files automatically
- Dual handlers: console + file
- UTF-8 encoding for all log files

### File Structure
```
C:\Users\{username}\.sony_automator_controls\
├── config.json
├── automator_cache.json
└── logs/
    ├── sony_automator_controls.log       # Current log
    ├── sony_automator_controls.log.1     # Previous rotation
    ├── sony_automator_controls.log.2
    ├── sony_automator_controls.log.3
    └── sony_automator_controls.log.4     # Oldest kept
```

### Modified Files
- `sony_automator_controls/core.py`
  - Added `_setup_logging()` function
  - Added rotating file handler
  - Added `/logs/export` endpoint
  - Added `/logs/view` endpoint
  - Enhanced `/health` endpoint

- `sony_automator_controls/__init__.py`
  - Version updated to `1.0.8`

---

## Upgrade Notes

### From v1.0.7 or earlier:

**No configuration changes needed** - this is a drop-in replacement.

1. Download `SonyAutomatorControls-1.0.8.exe` from releases
2. Replace your existing executable
3. Logs will automatically start being saved to:
   - `C:\Users\{your-username}\.sony_automator_controls\logs\`

### Recommended Actions:

1. **Test the log export:**
   - Open the web interface
   - Navigate to `/logs/export`
   - Verify log file downloads

2. **Check log location:**
   - Open the health endpoint: `http://localhost:3114/health`
   - Note the `log_file` path
   - Verify you can access this location

3. **Share logs for support:**
   - Use `/logs/export` to download logs
   - Share the downloaded file when reporting issues

---

## Why This Release?

Testing on a remote PC revealed logging errors that were difficult to diagnose because:
- Console logs were lost when window was closed
- No persistent record of errors
- Difficult to troubleshoot issues remotely

v1.0.8 solves this by:
- Always saving logs to file
- Providing easy export functionality
- Making troubleshooting simple and effective

---

## Changelog

### v1.0.8 (December 8, 2025)
- **NEW:** Persistent file-based logging with rotation
- **NEW:** `/logs/export` endpoint for downloading logs
- **NEW:** `/logs/view` endpoint for viewing logs in browser
- **ENHANCED:** `/health` endpoint includes log file path
- **IMPROVED:** Better troubleshooting and debugging capabilities

---

## Downloads

This release includes two executables:

1. **SonyAutomatorControls-1.0.8.exe** (Main Application)
   - Persistent file logging
   - Log export functionality
   - All performance optimizations from v1.0.6-1.0.7
   - Maximum speed with connection pooling

2. **TCPTestClient-1.0.0.exe** (Testing Tool)
   - Send test TCP commands
   - Verify command mappings

---

## Known Issues

None at this time.

---

## Support

If you encounter issues:
1. **Export your logs:** Go to `http://localhost:3114/logs/export`
2. **Check the log file** at the location shown in `/health`
3. **Report issues** at https://github.com/BlueElliott/Elliotts-Sony-Automator-Controls/issues
4. **Attach log file** when reporting bugs

---

**Built with:** Python 3.13, FastAPI, Uvicorn, httpx, Tkinter, psutil
**Release Date:** December 8, 2025
**Made with care by BlueElliott**
