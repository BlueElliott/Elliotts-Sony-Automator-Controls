"""Auto-update functionality for Sony Automator Controls."""

import requests
import logging
import os
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

GITHUB_REPO = "BlueElliott/Elliotts-Sony-Automator-Controls"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def get_current_version() -> str:
    """Get the current application version."""
    from sony_automator_controls import __version__
    return __version__


def check_for_updates() -> Optional[Dict]:
    """
    Check GitHub for the latest release.

    Returns:
        Dict with keys: version, download_url, release_notes
        None if no update available or error occurred
    """
    try:
        logger.info("Checking for updates...")
        response = requests.get(GITHUB_API_URL, timeout=10)
        response.raise_for_status()

        data = response.json()
        latest_version = data.get("tag_name", "").lstrip("v")
        current_version = get_current_version()

        logger.info(f"Current version: {current_version}, Latest version: {latest_version}")

        # Compare versions
        if latest_version and latest_version != current_version:
            # Find the .exe asset
            assets = data.get("assets", [])
            exe_asset = None
            for asset in assets:
                if asset.get("name", "").endswith(".exe"):
                    exe_asset = asset
                    break

            if exe_asset:
                return {
                    "version": latest_version,
                    "download_url": exe_asset.get("browser_download_url"),
                    "release_notes": data.get("body", "No release notes available."),
                    "asset_name": exe_asset.get("name")
                }

        logger.info("No updates available")
        return None

    except Exception as e:
        logger.error(f"Error checking for updates: {e}")
        return None


def download_update(download_url: str, asset_name: str) -> Optional[Path]:
    """
    Download the update file.

    Returns:
        Path to downloaded file, or None if failed
    """
    try:
        logger.info(f"Downloading update from {download_url}")

        # Create temp directory for download
        temp_dir = Path(tempfile.gettempdir()) / "sony_automator_updates"
        temp_dir.mkdir(exist_ok=True)

        download_path = temp_dir / asset_name

        # Download with progress
        response = requests.get(download_url, stream=True, timeout=60)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(download_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        logger.debug(f"Download progress: {progress:.1f}%")

        logger.info(f"Download complete: {download_path}")
        return download_path

    except Exception as e:
        logger.error(f"Error downloading update: {e}")
        return None


def install_update(new_exe_path: Path) -> bool:
    """
    Install the update by replacing the current executable.

    Creates a batch script that:
    1. Waits for current process to exit
    2. Replaces the old exe with new one
    3. Restarts the application

    Returns:
        True if update script was created successfully
    """
    try:
        # Get current executable path
        if getattr(sys, 'frozen', False):
            current_exe = Path(sys.executable)
        else:
            # Running from source - can't update
            logger.warning("Running from source - updates not supported")
            return False

        logger.info(f"Current exe: {current_exe}")
        logger.info(f"New exe: {new_exe_path}")

        # Create update script
        script_path = current_exe.parent / "update_sac.bat"

        # Batch script to replace exe and restart
        script_content = f"""@echo off
echo Updating Sony Automator Controls...
timeout /t 2 /nobreak > nul
del /f /q "{current_exe}"
move /y "{new_exe_path}" "{current_exe}"
echo Update complete! Restarting...
start "" "{current_exe}"
del "%~f0"
"""

        with open(script_path, 'w') as f:
            f.write(script_content)

        logger.info(f"Update script created: {script_path}")

        # Start the update script and exit
        subprocess.Popen(
            ['cmd', '/c', str(script_path)],
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        logger.info("Update script started - application will restart")
        return True

    except Exception as e:
        logger.error(f"Error installing update: {e}")
        return False
