# Sony Automator Controls v1.1.1

**Release Date:** December 15, 2025

## New Features

### Web Interface Improvements

1. **Disconnect Detection System**
   - Added real-time disconnect detection with visual overlay
   - Shows reconnection status with attempt counter
   - Full-screen overlay appears when server becomes unavailable
   - Automatic page reload upon successful reconnection
   - No more browser "connection refused" errors during disconnects

2. **Connection Status Indicator**
   - Blue pulsing dot in navigation bar shows live connection status
   - Changes to red when disconnected
   - Matches application's cyan/teal color scheme
   - Always visible for quick status checks

3. **Tutorial Reset Feature**
   - Added "Reset Welcome Guide" button in Settings
   - Allows users to re-show the first-run tutorial banner
   - Useful for reviewing setup steps or after major updates

4. **Updated Welcome Banner Design**
   - Changed from purple gradient to light blue/cyan gradient
   - Better matches overall application theme
   - Improved link colors and button styling
   - Added subtle shadow effects for better visual hierarchy

### Backend Improvements

1. **Health Check Logging**
   - Suppressed `/health` endpoint logging in console
   - Reduces log noise from connection monitoring
   - Other endpoints still logged normally for debugging

2. **Auto-Update System**
   - Added `updater.py` module for checking GitHub releases
   - Desktop GUI includes "Check for Updates" button
   - Downloads and installs new versions automatically
   - Uses batch script for safe executable replacement

## Bug Fixes

- Fixed auto-refresh loop on home page that caused connection errors during disconnects
- Removed unnecessary page reloads that interrupted user workflow
- Fixed console logging filling up with health check requests

## Code Cleanup

- Removed development/planning documentation files:
  - `IMPLEMENTATION_PLAN_v1.1.0.md`
  - `SESSION_SUMMARY.md`
  - `WIP_v1.1.0_REMAINING_WORK.md`
  - `UPGRADE_SUMMARY.md`

## Technical Details

### Modified Files
- `sony_automator_controls/__init__.py` - Version bump to 1.1.1
- `sony_automator_controls/core.py` - Disconnect detection, connection indicator, tutorial reset, theme updates
- `sony_automator_controls/gui_launcher.py` - Health check logging filter

### New Files
- `sony_automator_controls/updater.py` - Auto-update functionality

### API Changes
- `SettingsIn` model now includes optional `first_run` parameter
- `/settings` POST endpoint handles tutorial reset
- New CSS classes for connection status indicator

## Upgrade Notes

This release is fully backward compatible with v1.1.0. No configuration changes required.

The disconnect detection system activates automatically on all web pages. If the server becomes unavailable while you're viewing the web interface, you'll see an overlay with reconnection status instead of browser error pages.

---

**Full Changelog:** https://github.com/BlueElliott/Elliotts-Sony-Automator-Controls/compare/v1.1.0...v1.1.1
