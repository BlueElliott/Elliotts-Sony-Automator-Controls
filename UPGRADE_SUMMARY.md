# Sony Automator Controls - Upgrade Summary

## Changes Implemented (December 6, 2025)

This document summarizes the improvements made to Sony Automator Controls, bringing it up to feature parity with Elliott's Singular Controls.

---

## 1. Automated PyPI Publishing and GitHub Releases

### What was added:
- **GitHub Actions Workflow** ([.github/workflows/build.yml](.github/workflows/build.yml))
  - Automated builds on version tags (e.g., `v1.0.3`)
  - Builds Windows executable with PyInstaller
  - Builds Python package (wheel + sdist)
  - Publishes to PyPI automatically (requires `PYPI_API_TOKEN` secret)
  - Creates GitHub releases with release notes
  - Includes version.txt for runtime version detection

### How to use:
1. Update version in [pyproject.toml](pyproject.toml) and [sony_automator_controls/__init__.py](sony_automator_controls/__init__.py)
2. Commit changes: `git commit -am "Release v1.0.3"`
3. Create and push tag: `git tag v1.0.3 && git push origin v1.0.3`
4. GitHub Actions will automatically:
   - Build the Windows executable
   - Build Python package
   - Publish to PyPI (if token is configured)
   - Create GitHub release with exe attached

### Requirements:
- Add `PYPI_API_TOKEN` to GitHub repository secrets (Settings → Secrets → Actions)
- Get token from https://pypi.org/manage/account/token/

---

## 2. Port Configuration Dialog

### What was added:
- **Interactive port change dialog** in the GUI
- Port card now has a clickable "Change Port" button
- Port range validation (1024-65535)
- Configuration persistence
- User notification to restart after port change

### How to use:
1. Click on the "Change Port" button in the port card
2. Enter a new port number (1024-65535)
3. Restart the application for changes to take effect

### Files modified:
- [sony_automator_controls/gui_launcher.py](sony_automator_controls/gui_launcher.py)
  - Added `change_port()` method
  - Added `_handle_port_card_click()` method
  - Added clickable "Change Port" button to port card UI

---

## 3. Version Display

### What was added:
- **Runtime version detection** with fallback support
- Version displayed in:
  - GUI window title
  - GUI main page (below app name)
  - Web page titles
  - Web page headers
  - Console output
  - Health endpoint JSON response

### How it works:
The `_runtime_version()` function checks in order:
1. `version.txt` file (created by GitHub Actions during build)
2. Package `__version__` from `__init__.py`
3. Fallback to "1.0.2"

This ensures:
- Development builds show correct version from source
- CI builds show tag version from version.txt
- Portable exe shows embedded version

### Files modified:
- [sony_automator_controls/core.py](sony_automator_controls/core.py)
  - Added `_app_root()` helper function
  - Added `_runtime_version()` function
  - Updated `_get_base_html()` to show version in title and header
  - Updated `/health` endpoint to return version
- [sony_automator_controls/gui_launcher.py](sony_automator_controls/gui_launcher.py)
  - Imported `_runtime_version()`
  - Updated window title to show version
  - Updated brand label to show version
  - Updated console output to show version

---

## 4. Custom Logo and Icon

### What was added:
- **SAC (Sony Automator Controls) Icon**
  - Multi-resolution ICO file (16x16 to 256x256)
  - High-res PNG (256x256)
  - Teal accent color matching app theme (#00bcd4)
  - Concentric circles design with lines to S, A, C
  - Checkmark symbol in center

### Icon design:
```
┌──────────────────────┐
│                      │
│      S (top)         │
│        │             │
│    ┌───●───┐        │
│    │   │   │        │
│  A ●───✓───● C     │
│    │       │        │
│    └───────┘        │
│                      │
└──────────────────────┘
```

### Files added:
- [create_sac_icon.py](create_sac_icon.py) - Icon generator script
- [static/sac_icon.ico](static/sac_icon.ico) - Multi-resolution icon file
- [static/sac_icon.png](static/sac_icon.png) - High-res PNG version

### Files modified:
- [sony_automator_controls/gui_launcher.py](sony_automator_controls/gui_launcher.py)
  - Added `_set_window_icon()` method
  - Added Windows app ID for taskbar grouping
- [SonyAutomatorControls.spec](SonyAutomatorControls.spec)
  - Already configured to use `static/sac_icon.ico`

### How to regenerate icon:
```bash
python create_sac_icon.py
```

---

## 5. Configuration Improvements

### What was updated:
- **Enhanced pyproject.toml**
  - Updated to match Singular Controls format
  - Added MIT license metadata
  - Added comprehensive classifiers
  - Added optional dependencies for dev and build
  - Added tool configurations (black, ruff, bandit)
  - Separated build dependencies from runtime
  - Added package data for static files

### Files modified:
- [pyproject.toml](pyproject.toml)
  - Version updated to 1.0.2
  - Added license field
  - Added dev/build optional dependencies
  - Added tool configurations
  - Updated author information
  - Added more keywords and classifiers

---

## Summary of Files Changed

### New Files:
- `.github/workflows/build.yml` - CI/CD automation
- `create_sac_icon.py` - Icon generation script
- `static/sac_icon.ico` - Application icon (multi-res)
- `static/sac_icon.png` - Icon PNG version
- `UPGRADE_SUMMARY.md` - This file

### Modified Files:
- `pyproject.toml` - Enhanced package configuration
- `sony_automator_controls/__init__.py` - Version update
- `sony_automator_controls/core.py` - Added version functions, updated HTML
- `sony_automator_controls/gui_launcher.py` - Port dialog, icon loading, version display
- `SonyAutomatorControls.spec` - Already configured for icon

---

## Testing Checklist

Before releasing:
- [ ] Test port change dialog
- [ ] Verify version shows correctly in GUI
- [ ] Verify version shows correctly on web pages
- [ ] Check icon appears in taskbar and window
- [ ] Test executable build with PyInstaller
- [ ] Verify GitHub Actions workflow (push a test tag)
- [ ] Test PyPI upload (optional, if token configured)

---

## Next Steps

1. **Test the changes locally:**
   ```bash
   python -m sony_automator_controls
   ```

2. **Build executable:**
   ```bash
   pip install pyinstaller
   pyinstaller SonyAutomatorControls.spec
   ```

3. **Create a release:**
   - Update version in `pyproject.toml` and `__init__.py`
   - Commit and tag: `git tag v1.0.3 && git push --tags`
   - GitHub Actions will build and create release

4. **Optional: Configure PyPI:**
   - Create account at https://pypi.org
   - Generate API token
   - Add as `PYPI_API_TOKEN` in GitHub repository secrets

---

## Notes

- All changes maintain backward compatibility
- GUI features match Elliott's Singular Controls design patterns
- Icon design follows the same aesthetic (concentric circles, teal accent)
- Version detection works in both development and production builds
- PyPI publishing is optional (workflow skips if token not configured)

---

*Generated: December 6, 2025*
*Changes by: Claude Code (Sonnet 4.5)*
