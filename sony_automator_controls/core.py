"""Core application logic for Sony Automator Controls."""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

import requests
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Configure logging with file handler
def _setup_logging():
    """Setup logging with both console and file handlers."""
    # Create logs directory in user's home
    log_dir = Path.home() / ".sony_automator_controls" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Create rotating log file (keep last 5 files, 5MB each)
    from logging.handlers import RotatingFileHandler
    log_file = log_dir / "sony_automator_controls.log"

    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5),
            logging.StreamHandler()
        ]
    )
    return log_file

_log_file_path = _setup_logging()
logger = logging.getLogger(__name__)

# Version
from sony_automator_controls import __version__

# Global state
tcp_servers: Dict[int, asyncio.Server] = {}
tcp_connections: Dict[int, List[tuple]] = {}
automator_status = {"connected": False, "last_check": None, "error": None}
config_data = {}
server_start_time = time.time()

# Command/Event logging
COMMAND_LOG: List[str] = []
MAX_LOG_ENTRIES = 200

# TCP Capture state
tcp_capture_active = False
tcp_capture_result = None

# Persistent HTTP client for connection pooling (much faster than creating new client each time)
_http_client: Optional[httpx.AsyncClient] = None


def log_event(kind: str, detail: str):
    """Log an event to the command log."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    line = f"[{ts}] {kind}: {detail}"
    COMMAND_LOG.append(line)
    if len(COMMAND_LOG) > MAX_LOG_ENTRIES:
        del COMMAND_LOG[: len(COMMAND_LOG) - MAX_LOG_ENTRIES]
    logger.info(f"{kind}: {detail}")


def effective_port() -> int:
    """Get the effective port the server is running on."""
    return config_data.get("web_port", 3114)


def _app_root() -> Path:
    """Return the root directory of the app (for bundled exe or source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def _runtime_version() -> str:
    """
    Try to read version from version.txt next to the app, then package version.
    Fallback to __version__ if not present.
    """
    try:
        vfile = _app_root() / "version.txt"
        if vfile.exists():
            text = vfile.read_text(encoding="utf-8").strip()
            if ":" in text:
                text = text.split(":", 1)[1].strip()
            return text
    except Exception:
        pass
    # Try to get version from package
    try:
        return __version__
    except Exception:
        return "1.0.2"

# Configuration file path
CONFIG_DIR = Path.home() / ".sony_automator_controls"
CONFIG_FILE = CONFIG_DIR / "config.json"
AUTOMATOR_CACHE_FILE = CONFIG_DIR / "automator_cache.json"

# Automator data cache (persisted to disk) - now stores per Automator
automator_data_cache: Dict[str, Any] = {
    # Structure: {"automator_id": {"macros": [], "buttons": [], "shortcuts": [], "last_updated": None}}
}

# Default configuration (v1.1.0 with multi-Automator support)
DEFAULT_CONFIG = {
    "version": __version__,
    "config_version": "1.1.0",
    "theme": "dark",
    "web_port": 3114,
    "first_run": True,  # New: detect first-run for welcome experience
    "tcp_listeners": [],  # Empty by default for first-run
    "tcp_commands": [],  # Empty by default for first-run
    "automators": [],  # New: array of Automator configurations
    "command_mappings": []
}


# Pydantic models
class TCPListener(BaseModel):
    port: int
    name: str
    enabled: bool


class TCPCommand(BaseModel):
    id: str
    name: str
    tcp_trigger: str
    description: str = ""


class AutomatorConfig(BaseModel):
    id: str  # New: unique ID for each Automator
    name: str  # New: user-friendly name
    url: str
    api_key: str = ""
    enabled: bool


class CommandMapping(BaseModel):
    tcp_command_id: str
    automator_id: str  # New: which Automator to target
    automator_macro_id: str
    automator_macro_name: str = ""
    item_type: str = "macro"  # macro, button, or shortcut


class ConfigUpdate(BaseModel):
    tcp_listeners: Optional[List[TCPListener]] = None
    tcp_commands: Optional[List[TCPCommand]] = None
    automators: Optional[List[AutomatorConfig]] = None  # Updated: now list
    command_mappings: Optional[List[CommandMapping]] = None
    web_port: Optional[int] = None
    first_run: Optional[bool] = None  # New: for dismissing welcome


class SettingsIn(BaseModel):
    web_port: Optional[int] = None
    theme: Optional[str] = "dark"


# Configuration management
def ensure_config_dir():
    """Ensure configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def migrate_config_to_v1_1_0(old_config: dict) -> dict:
    """Migrate configuration from v1.0.x to v1.1.0."""
    import uuid

    logger.info("Migrating configuration from v1.0.x to v1.1.0...")

    new_config = DEFAULT_CONFIG.copy()

    # Keep existing settings
    new_config["version"] = __version__
    new_config["config_version"] = "1.1.0"
    new_config["theme"] = old_config.get("theme", "dark")
    new_config["web_port"] = old_config.get("web_port", 3114)
    new_config["tcp_listeners"] = old_config.get("tcp_listeners", [])
    new_config["tcp_commands"] = old_config.get("tcp_commands", [])

    # Migrate old single automator to automators array
    old_automator = old_config.get("automator", {})
    if old_automator and old_automator.get("url"):
        automator_id = f"auto_{uuid.uuid4().hex[:8]}"
        new_config["automators"] = [{
            "id": automator_id,
            "name": "Primary Automator",
            "url": old_automator.get("url", ""),
            "api_key": old_automator.get("api_key", ""),
            "enabled": old_automator.get("enabled", False)
        }]

        # Migrate command mappings to include automator_id
        old_mappings = old_config.get("command_mappings", [])
        new_mappings = []
        for mapping in old_mappings:
            new_mapping = mapping.copy()
            new_mapping["automator_id"] = automator_id  # Link to migrated Automator
            if "item_type" not in new_mapping:
                new_mapping["item_type"] = "macro"
            new_mappings.append(new_mapping)
        new_config["command_mappings"] = new_mappings
    else:
        new_config["automators"] = []
        new_config["command_mappings"] = []

    # Mark as not first run if had config
    new_config["first_run"] = False

    logger.info("Configuration migration complete")
    return new_config


def load_config() -> dict:
    """Load configuration from file."""
    ensure_config_dir()

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"Configuration loaded from {CONFIG_FILE}")

                # Check if migration is needed (v1.0.x to v1.1.0)
                config_version = config.get("config_version", "1.0.0")
                if config_version < "1.1.0" or "automator" in config:
                    config = migrate_config_to_v1_1_0(config)
                    save_config(config)  # Save migrated config

                return config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return DEFAULT_CONFIG.copy()
    else:
        # Create default config
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    """Save configuration to file."""
    ensure_config_dir()

    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        logger.info(f"Configuration saved to {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"Error saving config: {e}")


def load_automator_cache() -> dict:
    """Load cached Automator data from disk."""
    global automator_data_cache

    ensure_config_dir()

    if AUTOMATOR_CACHE_FILE.exists():
        try:
            with open(AUTOMATOR_CACHE_FILE, 'r', encoding='utf-8') as f:
                automator_data_cache = json.load(f)
                logger.info(f"Automator cache loaded from {AUTOMATOR_CACHE_FILE}")
                return automator_data_cache
        except Exception as e:
            logger.error(f"Error loading Automator cache: {e}")

    return automator_data_cache


def save_automator_cache():
    """Save Automator data cache to disk (now per-Automator structure)."""
    global automator_data_cache

    ensure_config_dir()

    try:
        with open(AUTOMATOR_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(automator_data_cache, f, indent=2)
        logger.info(f"Automator cache saved to {AUTOMATOR_CACHE_FILE}")
    except Exception as e:
        logger.error(f"Error saving Automator cache: {e}")


def get_automator_cache(automator_id: str) -> dict:
    """Get cache for a specific Automator."""
    global automator_data_cache

    if automator_id not in automator_data_cache:
        automator_data_cache[automator_id] = {
            "macros": [],
            "buttons": [],
            "shortcuts": [],
            "last_updated": None
        }

    return automator_data_cache[automator_id]


def merge_automator_data(automator_id: str, new_data: dict):
    """
    Smart merge of new Automator data with existing cache for a specific Automator.
    Preserves existing items and their IDs, adds new items, removes deleted items.
    This ensures command mappings don't break when data is updated.
    """
    global automator_data_cache

    # Get or create cache for this Automator
    cache = get_automator_cache(automator_id)

    for key in ["macros", "buttons", "shortcuts"]:
        if key in new_data:
            existing_items = {item.get("id"): item for item in cache.get(key, [])}
            new_items = {item.get("id"): item for item in new_data.get(key, [])}

            # Merge: update existing, add new
            merged = {}
            for item_id, item in new_items.items():
                if item_id in existing_items:
                    # Update existing item
                    merged[item_id] = item
                else:
                    # Add new item
                    merged[item_id] = item

            cache[key] = list(merged.values())

    cache["last_updated"] = datetime.now().isoformat()
    automator_data_cache[automator_id] = cache
    save_automator_cache()


def get_automator_by_id(automator_id: str) -> Optional[dict]:
    """Get Automator configuration by ID."""
    global config_data

    automators = config_data.get("automators", [])
    for automator in automators:
        if automator.get("id") == automator_id:
            return automator

    return None


def get_all_automators() -> List[dict]:
    """Get all Automator configurations."""
    global config_data
    return config_data.get("automators", [])


# TCP Server implementation
async def handle_tcp_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, port: int):
    """Handle individual TCP client connection."""
    global tcp_capture_active, tcp_capture_result

    addr = writer.get_extra_info('peername')
    logger.debug(f"TCP client connected from {addr} on port {port}")

    # Track connection
    if port not in tcp_connections:
        tcp_connections[port] = []
    tcp_connections[port].append((addr, time.time()))

    try:
        while True:
            data = await reader.readline()
            if not data:
                break

            message = data.decode().strip()
            # Only log received command, not duplicate info
            logger.debug(f"Received TCP command on port {port}: {message}")

            # If capture mode is active, store the command
            if tcp_capture_active:
                tcp_capture_result = {
                    "command": message,
                    "port": port,
                    "source": str(addr)
                }
                log_event("TCP Capture", f"Captured command '{message}' from port {port}")
                tcp_capture_active = False  # Disable capture after first command

            # Process the command
            await process_tcp_command(message, port)

    except Exception as e:
        logger.error(f"Error handling TCP client {addr}: {e}")
    finally:
        logger.debug(f"TCP client disconnected: {addr}")
        tcp_connections[port] = [conn for conn in tcp_connections[port] if conn[0] != addr]
        writer.close()
        await writer.wait_closed()


async def process_tcp_command(command: str, port: int):
    """Process incoming TCP command and trigger corresponding HTTP action."""
    global config_data

    # Single log event for command received
    log_event("TCP Command", f"Received '{command}' on port {port}")

    # Find matching TCP command in config
    tcp_cmd = None
    for cmd in config_data.get("tcp_commands", []):
        if cmd["tcp_trigger"].upper() == command.upper():
            tcp_cmd = cmd
            break

    if not tcp_cmd:
        log_event("TCP Warning", f"No definition for command '{command}'")
        return

    # Find command mapping
    mapping = None
    for m in config_data.get("command_mappings", []):
        if m["tcp_command_id"] == tcp_cmd["id"]:
            mapping = m
            break

    if not mapping:
        log_event("TCP Warning", f"No mapping for '{tcp_cmd['name']}'")
        return

    # Get automator_id from mapping
    automator_id = mapping.get("automator_id")
    if not automator_id:
        log_event("Mapping Error", f"No Automator specified for '{tcp_cmd['name']}'")
        return

    # Single log for successful mapping
    log_event("Mapping Found", f"{tcp_cmd['name']} → {mapping['automator_macro_name']}")

    # Trigger HTTP request to Automator
    item_type = mapping.get("item_type") or mapping.get("automator_macro_type")

    # If type is missing from mapping (old config), try to detect it from the macro ID
    if not item_type:
        macros = fetch_automator_macros(automator_id)
        for macro in macros:
            if macro.get("id") == mapping["automator_macro_id"]:
                item_type = macro.get("type", "macro")
                logger.debug(f"Auto-detected type '{item_type}' for {mapping['automator_macro_name']}")
                break
        if not item_type:
            item_type = "macro"  # Final fallback

    await trigger_automator_macro(mapping["automator_macro_id"], mapping["automator_macro_name"], item_type, automator_id)


def _get_http_client() -> httpx.AsyncClient:
    """Get or create persistent HTTP client with connection pooling."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=5.0,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            http2=False  # HTTP/1.1 is faster for simple requests
        )
    return _http_client


async def trigger_automator_macro(macro_id: str, macro_name: str, item_type: str = "macro", automator_id: Optional[str] = None):
    """Trigger an Automator macro, button, or shortcut via HTTP."""
    global config_data

    # Get Automator config
    if automator_id:
        automator_config = get_automator_by_id(automator_id)
    else:
        # If no ID provided, use first/only Automator
        automators = get_all_automators()
        if len(automators) == 1:
            automator_config = automators[0]
        else:
            log_event("Automator Error", "No Automator specified")
            logger.error("No Automator specified for trigger")
            return

    if not automator_config:
        log_event("Automator Error", f"Automator {automator_id} not found")
        logger.error(f"Automator {automator_id} not found")
        return

    if not automator_config.get("enabled"):
        log_event("Automator Warning", f"{automator_config['name']} is disabled")
        logger.warning(f"Automator {automator_config['name']} is disabled")
        return

    url = automator_config.get("url", "").strip()

    if not url:
        log_event("Automator Error", f"{automator_config['name']} URL not configured")
        logger.error(f"Automator {automator_config['name']} URL not configured")
        return

    # Ensure URL has protocol
    if not url.startswith('http://') and not url.startswith('https://'):
        url = f"http://{url}"

    url = url.rstrip("/")

    # Construct HTTP request based on type
    if item_type == "button":
        endpoint = f"{url}/api/trigger/button/{macro_id}"
    elif item_type == "shortcut":
        endpoint = f"{url}/api/trigger/shortcut/{macro_id}"
    else:  # macro
        endpoint = f"{url}/api/macro/{macro_id}"

    try:
        # Single log event for trigger attempt
        log_event("HTTP Trigger", f"[{automator_config['name']}] Calling {item_type}: {macro_name}")

        # Use persistent HTTP client with connection pooling for maximum speed
        client = _get_http_client()
        response = await client.get(endpoint)
        response.raise_for_status()

        log_event("HTTP Success", f"[{automator_config['name']}] Triggered {item_type}: {macro_name}")
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        log_event("HTTP Error", f"[{automator_config['name']}] Failed to trigger {macro_name}: {str(e)}")
        logger.error(f"Error triggering Automator {item_type} {macro_name} on {automator_config['name']}: {e}")


async def start_tcp_server(port: int):
    """Start a TCP server on specified port."""
    global tcp_servers

    if port in tcp_servers:
        log_event("TCP Warning", f"Server already running on port {port}")
        logger.warning(f"TCP server already running on port {port}")
        return

    try:
        server = await asyncio.start_server(
            lambda r, w: handle_tcp_client(r, w, port),
            '0.0.0.0',
            port
        )
        tcp_servers[port] = server
        tcp_connections[port] = []
        log_event("TCP Server", f"Started on port {port}")
        logger.info(f"TCP server started on port {port}")

        # Start serving in background
        asyncio.create_task(server.serve_forever())

    except Exception as e:
        log_event("TCP Error", f"Failed to start server on port {port}: {str(e)}")
        logger.error(f"Error starting TCP server on port {port}: {e}")


async def stop_tcp_server(port: int):
    """Stop TCP server on specified port."""
    global tcp_servers

    if port not in tcp_servers:
        log_event("TCP Warning", f"No server running on port {port}")
        logger.warning(f"No TCP server running on port {port}")
        return

    try:
        server = tcp_servers[port]
        server.close()
        await server.wait_closed()
        del tcp_servers[port]
        if port in tcp_connections:
            del tcp_connections[port]
        log_event("TCP Server", f"Stopped on port {port}")
        logger.info(f"TCP server stopped on port {port}")
    except Exception as e:
        log_event("TCP Error", f"Failed to stop server on port {port}: {str(e)}")
        logger.error(f"Error stopping TCP server on port {port}: {e}")


async def restart_tcp_servers():
    """Restart all TCP servers based on current configuration."""
    global config_data

    # Stop all existing servers
    ports_to_stop = list(tcp_servers.keys())
    for port in ports_to_stop:
        await stop_tcp_server(port)

    # Start servers for enabled listeners
    for listener in config_data.get("tcp_listeners", []):
        if listener["enabled"]:
            await start_tcp_server(listener["port"])


def check_automator_connection(automator_id: Optional[str] = None) -> dict:
    """Check connection to Automator API (specific Automator by ID)."""
    global config_data

    # Get Automator config
    if automator_id:
        automator_config = get_automator_by_id(automator_id)
    else:
        # If no ID provided, check if there's exactly one Automator
        automators = get_all_automators()
        if len(automators) == 1:
            automator_config = automators[0]
        else:
            return {"connected": False, "last_check": datetime.now().isoformat(), "error": "No Automator specified"}

    if not automator_config:
        return {"connected": False, "last_check": datetime.now().isoformat(), "error": "Automator not found"}

    if not automator_config.get("enabled") or not automator_config.get("url"):
        return {
            "connected": False,
            "last_check": datetime.now().isoformat(),
            "error": "Not configured",
            "automator_id": automator_config["id"],
            "automator_name": automator_config["name"]
        }

    url = automator_config.get("url", "").strip()

    # Ensure URL has protocol
    if url and not url.startswith('http://') and not url.startswith('https://'):
        url = f"http://{url}"

    url = url.rstrip("/")

    try:
        response = requests.get(f"{url}/api/app/webconnection", timeout=5)
        response.raise_for_status()
        return {
            "connected": True,
            "last_check": datetime.now().isoformat(),
            "error": None,
            "automator_id": automator_config["id"],
            "automator_name": automator_config["name"]
        }
    except requests.exceptions.Timeout:
        return {
            "connected": False,
            "last_check": datetime.now().isoformat(),
            "error": "Connection timeout - check if Automator is running",
            "automator_id": automator_config["id"],
            "automator_name": automator_config["name"]
        }
    except requests.exceptions.ConnectionError:
        return {
            "connected": False,
            "last_check": datetime.now().isoformat(),
            "error": "Cannot connect - check URL and port",
            "automator_id": automator_config["id"],
            "automator_name": automator_config["name"]
        }
    except requests.exceptions.HTTPError as e:
        return {
            "connected": False,
            "last_check": datetime.now().isoformat(),
            "error": f"HTTP error: {e.response.status_code}",
            "automator_id": automator_config["id"],
            "automator_name": automator_config["name"]
        }
    except requests.exceptions.RequestException as e:
        error_msg = str(e).split("(")[0].strip() if "(" in str(e) else str(e)
        return {
            "connected": False,
            "last_check": datetime.now().isoformat(),
            "error": error_msg[:100],
            "automator_id": automator_config["id"],
            "automator_name": automator_config["name"]
        }


def fetch_automator_macros(automator_id: Optional[str] = None, force_refresh: bool = False, use_cache_on_failure: bool = True) -> List[Dict[str, Any]]:
    """
    Fetch macros, buttons, and shortcuts from Automator API.

    Args:
        automator_id: Specific Automator ID to fetch from (None = single or first)
        force_refresh: If True, always tries to fetch from Automator. If False, returns cache immediately.
        use_cache_on_failure: If True, returns cached data when fetch fails.

    Returns:
        List of all items (macros, buttons, shortcuts)
    """
    global config_data, automator_data_cache

    # Get Automator config
    if automator_id:
        automator_config = get_automator_by_id(automator_id)
    else:
        # If no ID provided, use first Automator if only one exists
        automators = get_all_automators()
        if len(automators) == 1:
            automator_config = automators[0]
        elif len(automators) == 0:
            logger.info("No Automators configured")
            return []
        else:
            logger.info("Multiple Automators exist, must specify automator_id")
            return []

    if not automator_config:
        logger.info(f"Automator {automator_id} not found")
        return []

    # If not forcing refresh, just return cache (fast!)
    if not force_refresh:
        logger.debug(f"Using cached Automator data for {automator_config['name']} (no refresh requested)")
        return _get_cached_items(automator_config["id"])

    url = automator_config.get("url", "").strip()

    # If no URL configured, return cached data
    if not url:
        logger.info(f"No URL for Automator {automator_config['name']}, using cached data")
        return _get_cached_items(automator_config["id"])

    # Ensure URL has protocol
    if url and not url.startswith('http://') and not url.startswith('https://'):
        url = f"http://{url}"

    url = url.rstrip("/")

    macros = []
    buttons = []
    shortcuts = []
    fetch_success = False

    # Fetch macros
    try:
        response = requests.get(f"{url}/api/macro/", timeout=5)
        response.raise_for_status()
        macros = response.json()
        logger.info(f"Fetched {len(macros)} macros from Automator")
        fetch_success = True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Automator macros: {e}")

    # Fetch buttons
    try:
        response = requests.get(f"{url}/api/trigger/button/", timeout=5)
        response.raise_for_status()
        buttons = response.json()
        logger.info(f"Fetched {len(buttons)} buttons from Automator")
        fetch_success = True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Automator buttons: {e}")

    # Fetch shortcuts
    try:
        response = requests.get(f"{url}/api/trigger/shortcut/", timeout=5)
        response.raise_for_status()
        shortcuts = response.json()
        logger.info(f"Fetched {len(shortcuts)} shortcuts from Automator")

        # Add type and title to shortcuts (they don't have these fields in the API)
        for shortcut in shortcuts:
            shortcut["type"] = "shortcut"

            # Build display title from keyboard shortcut components
            key_parts = []
            if shortcut.get("control"):
                key_parts.append("Ctrl")
            if shortcut.get("alt"):
                key_parts.append("Alt")
            if shortcut.get("shift"):
                key_parts.append("Shift")
            key_parts.append(shortcut.get("key", "Unknown"))

            shortcut["title"] = " + ".join(key_parts)

        fetch_success = True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Automator shortcuts: {e}")

    # If we successfully fetched any data, merge with cache
    if fetch_success:
        new_data = {
            "macros": macros,
            "buttons": buttons,
            "shortcuts": shortcuts
        }
        merge_automator_data(automator_config["id"], new_data)
        logger.info(f"Merged new Automator data for {automator_config['name']} with cache")
        return _get_cached_items(automator_config["id"])

    # If fetch failed and we should use cache, return cached data
    if use_cache_on_failure:
        logger.debug(f"Using cached Automator data for {automator_config['name']} (fetch failed)")
        return _get_cached_items(automator_config["id"])

    return []


def _get_cached_items(automator_id: str) -> List[Dict[str, Any]]:
    """Get all items from cache as a flat list for a specific Automator."""
    cache = get_automator_cache(automator_id)
    all_items = []
    all_items.extend(cache.get("macros", []))
    all_items.extend(cache.get("buttons", []))
    all_items.extend(cache.get("shortcuts", []))
    return all_items


# Application lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global config_data

    # Startup
    logger.info("Starting Sony Automator Controls...")
    log_event("System", f"Starting Elliott's Sony Automator Controls v{__version__}")
    config_data = load_config()

    # Load cached Automator data
    load_automator_cache()
    log_event("System", "Loaded cached Automator data")

    # Start TCP servers for enabled listeners
    for listener in config_data.get("tcp_listeners", []):
        if listener["enabled"]:
            await start_tcp_server(listener["port"])

    log_event("System", "Server startup complete")

    yield

    # Shutdown
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None
    logger.info("Shutting down Sony Automator Controls...")
    log_event("System", "Shutting down server")
    # Stop all TCP servers
    ports_to_stop = list(tcp_servers.keys())
    for port in ports_to_stop:
        await stop_tcp_server(port)


# FastAPI app
app = FastAPI(title="Sony Automator Controls", version=__version__, lifespan=lifespan)

# Mount static files
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# Styling functions
def _get_base_styles() -> str:
    """Return base CSS styles matching Elliott's Singular Control exactly."""
    # Check theme and set colors accordingly
    theme = config_data.get("theme", "dark")
    if theme == "light":
        bg = "#f0f2f5"
        fg = "#1a1a2e"
        card_bg = "#ffffff"
        border = "#e0e0e0"
        accent = "#00bcd4"
        accent_hover = "#0097a7"
        text_muted = "#666666"
        input_bg = "#fafafa"
    else:
        # Modern dark theme - matched to desktop GUI colors
        bg = "#1a1a1a"
        fg = "#ffffff"
        card_bg = "#2d2d2d"
        border = "#3d3d3d"
        accent = "#00bcd4"
        accent_hover = "#0097a7"
        text_muted = "#888888"
        input_bg = "#252525"

    return f"""
    <style>
        @font-face {{
            font-family: 'ITVReem';
            src: url('/static/ITV Reem-Light.ttf') format('truetype');
            font-weight: 300;
            font-style: normal;
        }}
        @font-face {{
            font-family: 'ITVReem';
            src: url('/static/ITV Reem-Regular.ttf') format('truetype');
            font-weight: 400;
            font-style: normal;
        }}
        @font-face {{
            font-family: 'ITVReem';
            src: url('/static/ITV Reem-Medium.ttf') format('truetype');
            font-weight: 500;
            font-style: normal;
        }}
        @font-face {{
            font-family: 'ITVReem';
            src: url('/static/ITV Reem-Bold.ttf') format('truetype');
            font-weight: 700;
            font-style: normal;
        }}

        * {{
            box-sizing: border-box;
        }}

        body {{
            font-family: 'ITVReem', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            background: {bg};
            color: {fg};
            padding: 20px;
            line-height: 1.6;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}

        h1, h2, h3 {{
            font-weight: 500;
            margin-bottom: 20px;
        }}

        h1 {{
            font-size: 28px;
            font-weight: 700;
            margin: 20px 0 8px 0;
            padding-top: 50px;
            color: {fg};
        }}

        h1 + p {{
            color: {text_muted};
            margin-bottom: 24px;
        }}

        h2 {{
            font-size: 20px;
            font-weight: 600;
            margin: 24px 0 12px 0;
            color: {fg};
        }}

        h3 {{
            margin-top: 24px;
            margin-bottom: 8px;
            font-size: 16px;
            color: {fg};
        }}

        h3 small {{
            color: {text_muted};
            font-weight: 400;
        }}

        /* Fixed Navigation - Elliott's style */
        .nav {{
            position: fixed;
            top: 16px;
            left: 16px;
            display: flex;
            gap: 4px;
            z-index: 1000;
            background: {card_bg};
            padding: 6px;
            border-radius: 10px;
            border: 1px solid {accent}40;
            box-shadow: 0 2px 12px rgba(0, 188, 212, 0.15);
        }}

        .nav a {{
            color: {text_muted};
            text-decoration: none;
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
            transition: all 0.2s;
        }}

        .nav a:hover {{
            background: {accent}20;
            color: {accent};
        }}

        .nav a.active {{
            background: {accent};
            color: #fff;
        }}

        /* Sections / Fieldsets - Elliott's style */
        fieldset {{
            margin-bottom: 20px;
            padding: 20px 24px;
            background: {card_bg};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        legend {{
            font-weight: 600;
            padding: 0 12px;
            font-size: 14px;
            color: {text_muted};
        }}

        .section {{
            background: {card_bg};
            border: 1px solid {border};
            border-radius: 12px;
            padding: 20px 24px;
            margin-bottom: 20px;
        }}

        /* Status indicators */
        .status-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .status-card {{
            background: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 8px;
            padding: 20px;
        }}

        .status-card h3 {{
            font-size: 16px;
            margin-bottom: 15px;
            color: #888888;
        }}

        .status-indicator {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 10px;
        }}

        .status-dot {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
            animation: pulse 1.5s ease-in-out infinite;
        }}

        .status-dot.connected {{
            background: #4caf50;
        }}

        .status-dot.disconnected {{
            background: #ef4444;
            animation: none;
        }}

        .status-dot.idle {{
            background: #888888;
            animation: none;
        }}

        @keyframes pulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.6; transform: scale(1.1); }}
        }}

        .status-text {{
            font-size: 16px;
            font-weight: 500;
        }}

        .status-detail {{
            font-size: 12px;
            color: #888888;
            margin-left: 24px;
        }}

        /* Status badges - Elliott's style */
        .status-badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 13px;
        }}

        .status-badge.success {{
            background: #10b98120;
            color: #10b981;
        }}

        .status-badge.error {{
            background: #ef444420;
            color: #ef4444;
        }}

        .status-badge.warning {{
            background: #f59e0b20;
            color: #f59e0b;
        }}

        /* Play button - Elliott's style */
        .play-btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 36px;
            height: 36px;
            padding: 0;
            background: #2196f3;
            color: #fff;
            border-radius: 50%;
            text-decoration: none;
            font-size: 14px;
            transition: all 0.2s;
            border: none;
            cursor: pointer;
            line-height: 1;
            vertical-align: middle;
            margin: 0;
        }}

        .play-btn:hover {{
            background: #1976d2;
            transform: scale(1.1);
            box-shadow: 0 2px 8px #2196f360;
        }}

        /* Buttons - Elliott's style with transform */
        button {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            margin-top: 12px;
            margin-right: 8px;
            padding: 0 20px;
            height: 40px;
            cursor: pointer;
            background: {accent};
            color: #fff;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.2s;
        }}

        button:hover {{
            background: {accent_hover};
            transform: translateY(-1px);
            box-shadow: 0 4px 12px {accent}40;
        }}

        button:active {{
            transform: translateY(0);
        }}

        button.secondary {{
            background: {border};
            color: {fg};
        }}

        button.secondary:hover {{
            background: #4a4a4a;
            box-shadow: none;
            transform: none;
        }}

        button.danger {{
            background: #ef4444;
        }}

        button.danger:hover {{
            background: #dc2626;
        }}

        button.warning {{
            background: #f59e0b;
            color: #000;
        }}

        button.warning:hover {{
            background: #d97706;
        }}

        button.success {{
            background: #22c55e;
        }}

        button.success:hover {{
            background: #16a34a;
        }}

        button.test-btn {{
            background: #238636;
            border: none;
            color: #fff;
            padding: 6px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
        }}

        button.test-btn:hover {{
            background: #2ea043;
        }}

        .btn-row {{
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 16px;
        }}

        .btn-row button,
        .btn-row .status {{
            margin: 0 !important;
            margin-top: 0 !important;
            margin-right: 0 !important;
        }}

        /* Forms - Elliott's style */
        label {{
            display: block;
            margin-top: 12px;
            font-size: 14px;
            color: {text_muted};
        }}

        input,
        select {{
            width: 100%;
            padding: 10px 14px;
            margin-top: 6px;
            background: {input_bg};
            color: {fg};
            border: 1px solid {border};
            border-radius: 8px;
            font-size: 14px;
            transition: border-color 0.2s, box-shadow 0.2s;
        }}

        input:focus,
        select:focus {{
            outline: none;
            border-color: {accent};
            box-shadow: 0 0 0 3px {accent}33;
        }}

        /* Tables - Elliott's style */
        table {{
            border-collapse: collapse;
            width: 100%;
            margin-top: 12px;
            border-radius: 8px;
            overflow: hidden;
        }}

        th,
        td {{
            border: 1px solid {border};
            padding: 10px 14px;
            font-size: 13px;
            text-align: left;
        }}

        th {{
            background: {accent};
            color: #fff;
            font-weight: 600;
        }}

        tr:nth-child(even) td {{
            background: {input_bg};
        }}

        tr:hover td {{
            background: {border};
        }}

        /* Code blocks - Elliott's style */
        pre {{
            background: #000;
            color: {accent};
            padding: 16px;
            white-space: pre-wrap;
            max-height: 250px;
            overflow: auto;
            border-radius: 8px;
            font-size: 13px;
            font-family: 'SF Mono', Monaco, 'Cascadia Code', Consolas, monospace;
            border: 1px solid {border};
        }}

        code {{
            font-family: 'SF Mono', Monaco, 'Cascadia Code', Consolas, monospace;
            background: {input_bg};
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 12px;
            border: 1px solid {border};
            display: inline-block;
            max-width: 450px;
            overflow-x: auto;
            white-space: nowrap;
            vertical-align: middle;
        }}

        /* Lists */
        .item-list {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}

        .item {{
            background: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            padding: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .item-info {{
            flex: 1;
        }}

        .item-title {{
            font-weight: 500;
            margin-bottom: 5px;
        }}

        .item-detail {{
            font-size: 12px;
            color: #888888;
        }}

        .item-actions {{
            display: flex;
            gap: 8px;
        }}

        .item-actions button {{
            padding: 6px 12px;
            font-size: 12px;
        }}

        /* Matrix/Grid */
        .mapping-grid {{
            overflow-x: auto;
        }}

        .mapping-table {{
            min-width: 800px;
        }}

        .mapping-cell {{
            text-align: center;
        }}

        .mapping-cell input[type="checkbox"] {{
            width: auto;
            cursor: pointer;
        }}

        /* Alerts */
        .alert {{
            padding: 15px 20px;
            border-radius: 6px;
            margin-bottom: 20px;
        }}

        .alert.info {{
            background: rgba(0, 188, 212, 0.1);
            border: 1px solid #00bcd4;
            color: #00bcd4;
        }}

        .alert.error {{
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid #ef4444;
            color: #ef4444;
        }}

        .alert.success {{
            background: rgba(34, 197, 94, 0.1);
            border: 1px solid #22c55e;
            color: #22c55e;
        }}

        /* Utility classes */
        .flex {{
            display: flex;
        }}

        .flex-between {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .gap-10 {{
            gap: 10px;
        }}

        .mt-20 {{
            margin-top: 20px;
        }}

        .mb-20 {{
            margin-bottom: 20px;
        }}
    </style>
    """


def _get_nav_html(active_page: str = "home") -> str:
    """Return navigation HTML - fixed top-left style matching Elliott's."""
    pages = [
        ("home", "Home", "/"),
        ("tcp", "TCP Commands", "/tcp-commands"),
        ("automator", "Automator Controls", "/automator-macros"),
        ("mapping", "Command Mapping", "/command-mapping"),
        ("settings", "Settings", "/settings"),
    ]

    nav_items = ""
    for page_id, title, url in pages:
        active_class = ' class="active"' if page_id == active_page else ""
        nav_items += f'<a href="{url}"{active_class}>{title}</a>'

    return f'<div class="nav">{nav_items}</div>'


def _get_base_html(title: str, content: str, active_page: str = "home") -> str:
    """Return complete HTML page."""
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - Elliott's Sony Automator Controls v{_runtime_version()}</title>
        {_get_base_styles()}
    </head>
    <body>
        {_get_nav_html(active_page)}
        <h1>Elliott's Sony Automator Controls</h1>
        <p style="color: #888; font-size: 0.9em; margin-top: -10px;">Version {_runtime_version()}</p>
        <p>{title}</p>
        {content}
    </body>
    </html>
    """


# API Routes
@app.get("/", response_class=HTMLResponse)
async def home():
    """Home page with connection status."""
    global config_data, tcp_servers, automator_status, server_start_time

    # Check for first-run or no Automators configured
    is_first_run = config_data.get("first_run", False)
    automators = get_all_automators()
    show_welcome = is_first_run or len(automators) == 0

    # Welcome banner
    welcome_html = ""
    if show_welcome:
        welcome_html = """
        <div class="section" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 12px; padding: 30px; margin-bottom: 30px;">
            <h2 style="color: white; margin-top: 0;">👋 Welcome to Sony Automator Controls v1.1.0!</h2>
            <p style="font-size: 16px; margin-bottom: 20px;">Let's get you set up in a few easy steps:</p>
            <ol style="font-size: 15px; line-height: 1.8;">
                <li><strong>Add Automator:</strong> Go to <a href="/automator-macros" style="color: #ffd700; text-decoration: underline;">Automator Controls</a> and configure your first Automator connection</li>
                <li><strong>Setup TCP:</strong> Configure <a href="/tcp-commands" style="color: #ffd700; text-decoration: underline;">TCP Listeners and Commands</a></li>
                <li><strong>Create Mappings:</strong> Link commands to macros in <a href="/command-mapping" style="color: #ffd700; text-decoration: underline;">Command Mapping</a></li>
            </ol>
            <button onclick="dismissWelcome()" style="background: white; color: #667eea; border: none; padding: 10px 24px; border-radius: 6px; font-weight: bold; cursor: pointer; margin-top: 15px; font-size: 14px;">Got it, don't show again</button>
        </div>
        """

    # Build TCP listener status
    tcp_status_html = ""
    for listener in config_data.get("tcp_listeners", []):
        port = listener["port"]
        name = listener["name"]
        enabled = listener["enabled"]

        if enabled and port in tcp_servers:
            status_class = "connected"
            status_text = f"Listening on port {port}"
            conn_count = len(tcp_connections.get(port, []))
            detail = f"{conn_count} active connection(s)"
        elif enabled:
            status_class = "disconnected"
            status_text = "Failed to start"
            detail = f"Port {port} unavailable"
        else:
            status_class = "idle"
            status_text = "Disabled"
            detail = f"Port {port}"

        tcp_status_html += f"""
        <div class="status-card">
            <h3>{name}</h3>
            <div class="status-indicator">
                <div class="status-dot {status_class}"></div>
                <span class="status-text">{status_text}</span>
            </div>
            <div class="status-detail">{detail}</div>
        </div>
        """

    # Build Automator status cards (one per Automator)
    automator_status_html = ""
    if len(automators) == 0:
        automator_status_html = """
        <div class="status-card">
            <h3>No Automators</h3>
            <div class="status-indicator">
                <div class="status-dot idle"></div>
                <span class="status-text">Not configured</span>
            </div>
            <div class="status-detail"><a href="/automator-macros">Add Automator</a></div>
        </div>
        """
    else:
        for automator in automators:
            status = check_automator_connection(automator["id"])
            if status["connected"]:
                auto_class = "connected"
                auto_text = "Connected"
                auto_detail = automator.get("url", "")
            else:
                auto_class = "disconnected"
                auto_text = "Disconnected"
                auto_detail = status.get("error", "Not configured")

            automator_status_html += f"""
            <div class="status-card">
                <h3>{automator['name']}</h3>
                <div class="status-indicator">
                    <div class="status-dot {auto_class}"></div>
                    <span class="status-text">{auto_text}</span>
                </div>
                <div class="status-detail">{auto_detail}</div>
            </div>
            """

    # Server uptime
    uptime_seconds = int(time.time() - server_start_time)
    hours = uptime_seconds // 3600
    minutes = (uptime_seconds % 3600) // 60
    uptime_text = f"{hours}h {minutes}m"

    # Event log
    event_log_html = "\\n".join(f"<div>{event}</div>" for event in COMMAND_LOG[-20:])
    if not event_log_html:
        event_log_html = "<div style='color: #888;'>No events yet...</div>"

    content = f"""
    {welcome_html}

    <h1>Dashboard</h1>

    <div class="section">
        <h2>Connection Status</h2>
        <div class="status-grid">
            {tcp_status_html}

            {automator_status_html}

            <div class="status-card">
                <h3>Server Status</h3>
                <div class="status-indicator">
                    <div class="status-dot connected"></div>
                    <span class="status-text">Running</span>
                </div>
                <div class="status-detail">Uptime: {uptime_text}</div>
            </div>
        </div>
    </div>

    <div class="section">
        <h2>Quick Stats</h2>
        <div class="status-grid">
            <div class="status-card">
                <h3>Automators</h3>
                <div style="font-size: 32px; font-weight: 700; color: #00bcd4;">
                    {len(automators)}
                </div>
            </div>
            <div class="status-card">
                <h3>TCP Commands</h3>
                <div style="font-size: 32px; font-weight: 700; color: #00bcd4;">
                    {len(config_data.get('tcp_commands', []))}
                </div>
            </div>
            <div class="status-card">
                <h3>Active Mappings</h3>
                <div style="font-size: 32px; font-weight: 700; color: #00bcd4;">
                    {len(config_data.get('command_mappings', []))}
                </div>
            </div>
            <div class="status-card">
                <h3>TCP Listeners</h3>
                <div style="font-size: 32px; font-weight: 700; color: #00bcd4;">
                    {len([l for l in config_data.get('tcp_listeners', []) if l['enabled']])}
                </div>
            </div>
        </div>
    </div>

    <div class="section">
        <h2>Event Log</h2>
        <p style="color: #888888; margin-bottom: 12px;">Recent commands and system events (last 20 entries)</p>
        <div id="event-log" style="background: #000; color: #00bcd4; padding: 16px; border-radius: 8px; font-family: 'SF Mono', Monaco, 'Cascadia Code', Consolas, monospace; font-size: 13px; max-height: 300px; overflow-y: auto; line-height: 1.8;">
            {event_log_html}
        </div>
    </div>

    <script>
        async function dismissWelcome() {{
            await fetch('/api/config', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{first_run: false}})
            }});
            location.reload();
        }}

        // Auto-refresh every 3 seconds
        setTimeout(() => location.reload(), 3000);
    </script>
    """

    return _get_base_html("Home", content, "home")


@app.get("/tcp-commands", response_class=HTMLResponse)
async def tcp_commands_page():
    """TCP Commands management page."""
    global config_data

    commands = config_data.get("tcp_commands", [])
    listeners = config_data.get("tcp_listeners", [])

    # Build commands list
    commands_html = ""
    for cmd in commands:
        commands_html += f"""
        <div class="item searchable-tcp-command" data-name="{cmd['name'].lower()}" data-trigger="{cmd['tcp_trigger'].lower()}" data-description="{cmd.get('description', '').lower()}">
            <div class="item-info">
                <div class="item-title">{cmd['name']}</div>
                <div class="item-detail">TCP Trigger: <strong>{cmd['tcp_trigger']}</strong></div>
                <div class="item-detail">{cmd.get('description', '')}</div>
            </div>
            <div class="item-actions">
                <button class="secondary" onclick="editCommand('{cmd['id']}')">Edit</button>
                <button class="danger" onclick="deleteCommand('{cmd['id']}')">Delete</button>
            </div>
        </div>
        """

    if not commands_html:
        commands_html = '<div class="alert info">No TCP commands configured yet. Add your first command below.</div>'

    # Build listeners list
    listeners_html = ""
    for listener in listeners:
        enabled_badge = "🟢 Enabled" if listener["enabled"] else "🔴 Disabled"
        listeners_html += f"""
        <div class="item">
            <div class="item-info">
                <div class="item-title">{listener['name']} - Port {listener['port']}</div>
                <div class="item-detail">{enabled_badge}</div>
            </div>
            <div class="item-actions">
                <button class="secondary" onclick="toggleListener({listener['port']})">
                    {'Disable' if listener['enabled'] else 'Enable'}
                </button>
                <button class="danger" onclick="deleteListener({listener['port']})">Delete</button>
            </div>
        </div>
        """

    content = f"""
    <h1>TCP Commands</h1>

    <div class="section">
        <h2>TCP Listeners</h2>
        <p style="color: #888888; margin-bottom: 20px;">Configure which ports to listen for incoming TCP commands.</p>
        <div class="item-list">
            {listeners_html}
        </div>
        <button class="primary mt-20" onclick="showAddListenerForm()">Add TCP Listener</button>
    </div>

    <div class="section">
        <h2>Configured Commands</h2>
        <p style="color: #888888; margin-bottom: 20px;">Define TCP commands that will be recognized by the system.</p>

        <div style="margin-bottom: 20px;">
            <input type="text" id="tcpCommandSearchBox" placeholder="Search commands by name, trigger, or description..." style="width: 100%; padding: 10px 14px; font-size: 14px; border-radius: 8px;" oninput="filterTCPCommands()">
        </div>

        <div class="item-list" id="tcp-commands-list">
            {commands_html}
        </div>
        <div class="btn-row">
            <button class="primary" onclick="showAddCommandForm()">Add TCP Command</button>
            <button class="warning" onclick="startTCPCapture()">Listen for TCP Command</button>
        </div>
        <div id="capture-status" style="margin-top: 16px;"></div>
    </div>

    <script>
        function showAddListenerForm() {{
            const port = prompt("Enter TCP port number:");
            const name = prompt("Enter listener name:");
            if (port && name) {{
                addListener(parseInt(port), name);
            }}
        }}

        async function addListener(port, name) {{
            const listeners = {json.dumps(listeners)};
            listeners.push({{port: port, name: name, enabled: true}});

            const response = await fetch('/api/config', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{tcp_listeners: listeners}})
            }});

            if (response.ok) {{
                location.reload();
            }} else {{
                alert('Error adding listener');
            }}
        }}

        async function deleteListener(port) {{
            if (!confirm('Delete this listener?')) return;

            const listeners = {json.dumps(listeners)}.filter(l => l.port !== port);

            const response = await fetch('/api/config', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{tcp_listeners: listeners}})
            }});

            if (response.ok) {{
                location.reload();
            }} else {{
                alert('Error deleting listener');
            }}
        }}

        async function toggleListener(port) {{
            const listeners = {json.dumps(listeners)}.map(l => {{
                if (l.port === port) {{
                    l.enabled = !l.enabled;
                }}
                return l;
            }});

            const response = await fetch('/api/config', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{tcp_listeners: listeners}})
            }});

            if (response.ok) {{
                location.reload();
            }} else {{
                alert('Error toggling listener');
            }}
        }}

        function showAddCommandForm() {{
            const name = prompt("Command name:");
            const trigger = prompt("TCP trigger string:");
            const description = prompt("Description (optional):");
            if (name && trigger) {{
                addCommand(name, trigger, description || "");
            }}
        }}

        async function addCommand(name, trigger, description) {{
            const commands = {json.dumps(commands)};
            const id = 'cmd_' + Date.now();
            commands.push({{id: id, name: name, tcp_trigger: trigger, description: description}});

            const response = await fetch('/api/config', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{tcp_commands: commands}})
            }});

            if (response.ok) {{
                location.reload();
            }} else {{
                alert('Error adding command');
            }}
        }}

        async function deleteCommand(id) {{
            if (!confirm('Delete this command?')) return;

            const commands = {json.dumps(commands)}.filter(c => c.id !== id);

            const response = await fetch('/api/config', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{tcp_commands: commands}})
            }});

            if (response.ok) {{
                location.reload();
            }} else {{
                alert('Error deleting command');
            }}
        }}

        function editCommand(id) {{
            const commands = {json.dumps(commands)};
            const cmd = commands.find(c => c.id === id);
            if (!cmd) {{
                alert('Command not found');
                return;
            }}

            const name = prompt('Command name:', cmd.name);
            if (name === null) return; // Cancelled

            const trigger = prompt('TCP trigger string:', cmd.tcp_trigger);
            if (trigger === null) return; // Cancelled

            const description = prompt('Description (optional):', cmd.description || '');
            if (description === null) return; // Cancelled

            updateCommand(id, name, trigger, description);
        }}

        async function updateCommand(id, name, trigger, description) {{
            const commands = {json.dumps(commands)};
            const updatedCommands = commands.map(c => {{
                if (c.id === id) {{
                    return {{id: id, name: name, tcp_trigger: trigger, description: description}};
                }}
                return c;
            }});

            const response = await fetch('/api/config', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{tcp_commands: updatedCommands}})
            }});

            if (response.ok) {{
                location.reload();
            }} else {{
                alert('Error updating command');
            }}
        }}

        // TCP Capture functions
        let captureCheckInterval = null;

        async function startTCPCapture() {{
            const statusDiv = document.getElementById('capture-status');
            statusDiv.innerHTML = '<div class="alert info">Starting TCP capture mode... Waiting for next TCP command...</div>';

            try {{
                const response = await fetch('/tcp/capture/start', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}}
                }});

                if (response.ok) {{
                    // Start polling for capture result
                    captureCheckInterval = setInterval(checkCaptureStatus, 500);

                    // Auto-cancel after 30 seconds
                    setTimeout(() => {{
                        if (captureCheckInterval) {{
                            cancelCapture();
                        }}
                    }}, 30000);
                }} else {{
                    statusDiv.innerHTML = '<div class="alert error">Failed to start capture mode</div>';
                }}
            }} catch (e) {{
                statusDiv.innerHTML = '<div class="alert error">Error: ' + e + '</div>';
            }}
        }}

        async function checkCaptureStatus() {{
            try {{
                const response = await fetch('/tcp/capture/status');
                const data = await response.json();

                if (data.status === 'captured') {{
                    // Stop polling
                    clearInterval(captureCheckInterval);
                    captureCheckInterval = null;

                    // Show captured command
                    const cmd = data.data.command;
                    const port = data.data.port;
                    const source = data.data.source;

                    const statusDiv = document.getElementById('capture-status');
                    statusDiv.innerHTML = '<div class="alert success">Captured TCP command: <strong>' + cmd + '</strong> from port ' + port + ' (source: ' + source + ')</div>';

                    // Prompt to add as command
                    if (confirm('Captured command: "' + cmd + '"\\n\\nWould you like to add this as a new TCP command?')) {{
                        const name = prompt('Command name:', cmd);
                        const description = prompt('Description (optional):');
                        if (name) {{
                            addCommand(name, cmd, description || '');
                        }}
                    }}
                }}
            }} catch (e) {{
                console.error('Error checking capture status:', e);
            }}
        }}

        async function cancelCapture() {{
            if (captureCheckInterval) {{
                clearInterval(captureCheckInterval);
                captureCheckInterval = null;
            }}

            await fetch('/tcp/capture/cancel', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}}
            }});

            const statusDiv = document.getElementById('capture-status');
            statusDiv.innerHTML = '<div class="alert warning">Capture mode cancelled</div>';
            setTimeout(() => statusDiv.innerHTML = '', 3000);
        }}

        function filterTCPCommands() {{
            const searchTerm = document.getElementById('tcpCommandSearchBox').value.toLowerCase();
            const items = document.querySelectorAll('.searchable-tcp-command');

            items.forEach(item => {{
                const name = item.getAttribute('data-name');
                const trigger = item.getAttribute('data-trigger');
                const description = item.getAttribute('data-description');
                const matches = name.includes(searchTerm) || trigger.includes(searchTerm) || description.includes(searchTerm);

                if (matches) {{
                    item.style.display = 'flex';
                }} else {{
                    item.style.display = 'none';
                }}
            }});
        }}
    </script>
    """

    return _get_base_html("TCP Commands", content, "tcp")


@app.get("/automator-macros", response_class=HTMLResponse)
async def automator_macros_page():
    """Automator Controls page."""
    global config_data, automator_data_cache

    # Get all Automators
    automators = get_all_automators()

    # Build Automator management section (at the TOP per user request)
    automator_cards_html = ""

    if len(automators) == 0:
        automator_cards_html = """
        <div class="alert info">
            <strong>No Automators configured.</strong><br>
            Click "Add Automator" below to connect your first Automator instance.
        </div>
        """
    else:
        for automator in automators:
            auto_id = automator["id"]
            auto_name = automator["name"]
            auto_url = automator.get("url", "Not configured")
            auto_enabled = automator.get("enabled", False)

            # Check connection status
            status = check_automator_connection(auto_id)
            if status["connected"]:
                status_class = "success"
                status_text = "✓ Connected"
            else:
                status_class = "error"
                status_text = f"✗ {status.get('error', 'Disconnected')}"

            # Get cache info
            cache = get_automator_cache(auto_id)
            total_items = len(cache.get("macros", [])) + len(cache.get("buttons", [])) + len(cache.get("shortcuts", []))
            cache_age = ""
            if cache.get("last_updated"):
                try:
                    last_updated = datetime.fromisoformat(cache["last_updated"])
                    cache_age = last_updated.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    cache_age = "Unknown"
            else:
                cache_age = "No data"

            enabled_badge = '<span style="background: #4caf50; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 8px;">ENABLED</span>' if auto_enabled else '<span style="background: #666; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 8px;">DISABLED</span>'

            automator_cards_html += f"""
            <div class="automator-card" style="background: #1e1e1e; border: 1px solid #333; border-radius: 8px; padding: 20px; margin-bottom: 15px;">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 12px;">
                    <div>
                        <h3 style="margin: 0 0 8px 0; font-size: 18px;">{auto_name}{enabled_badge}</h3>
                        <p style="color: #888; margin: 4px 0; font-size: 13px;">{auto_url}</p>
                        <p style="color: #888; margin: 4px 0; font-size: 12px;">Cached: {total_items} items | Last updated: {cache_age}</p>
                    </div>
                    <div class="alert {status_class}" style="margin: 0; padding: 6px 12px; font-size: 13px;">
                        {status_text}
                    </div>
                </div>
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    <button class="secondary" onclick="testAutomator('{auto_id}')" style="font-size: 13px; padding: 8px 16px;">Test Connection</button>
                    <button class="secondary" onclick="refreshAutomator('{auto_id}')" style="font-size: 13px; padding: 8px 16px;">Refresh Data</button>
                    <button class="secondary" onclick="editAutomator('{auto_id}')" style="font-size: 13px; padding: 8px 16px;">Edit</button>
                    <button class="danger" onclick="deleteAutomator('{auto_id}', '{auto_name}')" style="font-size: 13px; padding: 8px 16px;">Delete</button>
                </div>
                <div id="status-{auto_id}" style="margin-top: 12px;"></div>
            </div>
            """

    automator_management = f"""
    <div class="section">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
            <h2 style="margin: 0;">Automator Connections</h2>
            <button class="success" onclick="showAddAutomatorDialog()" style="font-size: 14px;">+ Add Automator</button>
        </div>

        {automator_cards_html}
    </div>

    <!-- Add/Edit Automator Dialog -->
    <div id="automatorDialog" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 1000; justify-content: center; align-items: center;">
        <div style="background: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 30px; max-width: 500px; width: 90%;">
            <h2 id="dialogTitle">Add Automator</h2>
            <form id="automatorForm" onsubmit="saveAutomator(event)">
                <input type="hidden" id="automatorId">

                <div class="form-group">
                    <label>Name</label>
                    <input type="text" id="automatorName" placeholder="e.g., Primary Automator" required>
                </div>

                <div class="form-group">
                    <label>API URL</label>
                    <input type="text" id="automatorUrl" placeholder="http://127.0.0.1:7070" required>
                    <p style="color: #888; font-size: 12px; margin-top: 6px;">Enter the full URL including protocol and port</p>
                </div>

                <div class="form-group">
                    <label>API Key (optional)</label>
                    <input type="text" id="automatorApiKey" placeholder="Leave blank if not required">
                </div>

                <div class="form-group">
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="checkbox" id="automatorEnabled" checked>
                        <span>Enabled</span>
                    </label>
                </div>

                <div style="display: flex; gap: 10px; margin-top: 20px;">
                    <button type="submit" class="success">Save</button>
                    <button type="button" class="secondary" onclick="closeAutomatorDialog()">Cancel</button>
                </div>

                <div id="dialogStatus" style="margin-top: 15px;"></div>
            </form>
        </div>
    </div>
    """

    # Automator selector for viewing macros
    automator_selector_html = ""
    selected_automator_id = None

    if len(automators) > 0:
        # Default to first Automator
        selected_automator_id = automators[0]["id"]

        options_html = ""
        for auto in automators:
            options_html += f'<option value="{auto["id"]}">{auto["name"]}</option>'

        automator_selector_html = f"""
        <div style="margin-bottom: 20px; padding: 15px; background: #1e1e1e; border-radius: 8px;">
            <label style="display: block; margin-bottom: 8px; font-weight: 600;">Select Automator to view:</label>
            <select id="automatorSelector" onchange="switchAutomator()" style="width: 100%; padding: 10px; font-size: 14px;">
                {options_html}
            </select>
        </div>
        """

    # Fetch and organize macros/buttons/shortcuts for selected Automator
    macros_list = []
    buttons_list = []
    shortcuts_list = []

    if selected_automator_id:
        all_items = fetch_automator_macros(selected_automator_id)
    else:
        all_items = []

    for item in all_items:
        item_type = item.get("type", "")
        if item_type == "button":
            buttons_list.append(item)
        elif item_type == "shortcut":
            shortcuts_list.append(item)
        else:
            macros_list.append(item)

    # Build collapsible sections
    def build_item_section(items, section_title, section_id):
        if not items:
            return f'<p style="color: #888888;">No {section_title.lower()} found.</p>'

        items_html = ""
        for item in items:
            item_id = item.get("id", "")
            item_name = item.get("title", item.get("name", "Unknown"))
            item_type = item.get("type", "macro")  # Get item type, default to macro
            items_html += f"""
            <div class="item searchable-item" data-name="{item_name.lower()}" data-type="{section_id}">
                <div class="item-info">
                    <div class="item-title">{item_name}</div>
                </div>
                <div class="item-actions">
                    <a href="javascript:void(0)" class="play-btn" onclick="testMacro('{item_id}', '{item_name}', '{item_type}')" title="Test {item_name}">▶</a>
                </div>
            </div>
            """

        return f"""
        <details id="{section_id}-section">
            <summary style="cursor: pointer; font-weight: 600; font-size: 16px; margin-bottom: 15px; padding: 10px; background: #252525; border-radius: 6px;">
                {section_title} (<span id="{section_id}-count">{len(items)}</span>)
            </summary>
            <div class="item-list" id="{section_id}-list" style="margin-top: 12px;">
                {items_html}
            </div>
        </details>
        """

    if not all_items:
        if selected_automator_id:
            content_html = '<div class="alert info">No cached data available. Click Refresh to load macros, buttons, and shortcuts from this Automator.</div>'
        else:
            content_html = '<div class="alert info">No Automators configured. Add an Automator above to get started.</div>'
    else:
        # Show cache age if available
        cache_info = ""
        if selected_automator_id:
            cache = get_automator_cache(selected_automator_id)
            if cache.get("last_updated"):
                try:
                    last_updated = datetime.fromisoformat(cache["last_updated"])
                    cache_info = f'<div class="alert info" style="margin-bottom: 15px;">Last updated: {last_updated.strftime("%Y-%m-%d %H:%M:%S")}</div>'
                except:
                    pass

        content_html = f"""
        {cache_info}
        {build_item_section(macros_list, "Macros", "macros")}
        {build_item_section(buttons_list, "Buttons", "buttons")}
        {build_item_section(shortcuts_list, "Shortcuts", "shortcuts")}
        """

    macros_section = f"""
    <div class="section">
        <h2>Available Macros, Buttons & Shortcuts</h2>
        <p style="color: #888888; margin-bottom: 12px;">Items available in your Automator system. Click to expand/collapse sections.</p>

        {automator_selector_html}

        <div style="margin-bottom: 20px;">
            <input type="text" id="searchBox" placeholder="Search across all items..." style="width: 100%; padding: 10px 14px; font-size: 14px; border-radius: 8px;" oninput="filterItems()">
        </div>

        {content_html}
        <button id="refreshBtn" class="secondary mt-20" onclick="refreshMacros()" {'disabled' if not selected_automator_id else ''}>{"Reload Macros" if all_items else "Load Macros"}</button>
        <div id="refreshStatus" class="mt-20"></div>
    </div>
    """

    content = automator_management + macros_section + f"""
    <script>
        // Automator Management Functions
        function showAddAutomatorDialog() {{
            document.getElementById('dialogTitle').textContent = 'Add Automator';
            document.getElementById('automatorId').value = '';
            document.getElementById('automatorName').value = '';
            document.getElementById('automatorUrl').value = '';
            document.getElementById('automatorApiKey').value = '';
            document.getElementById('automatorEnabled').checked = true;
            document.getElementById('dialogStatus').innerHTML = '';
            document.getElementById('automatorDialog').style.display = 'flex';
        }}

        function closeAutomatorDialog() {{
            document.getElementById('automatorDialog').style.display = 'none';
        }}

        async function editAutomator(automatorId) {{
            // Fetch current Automator config
            const response = await fetch('/api/automators');
            const data = await response.json();
            const automator = data.automators.find(a => a.id === automatorId);

            if (!automator) return;

            document.getElementById('dialogTitle').textContent = 'Edit Automator';
            document.getElementById('automatorId').value = automator.id;
            document.getElementById('automatorName').value = automator.name;
            document.getElementById('automatorUrl').value = automator.url;
            document.getElementById('automatorApiKey').value = automator.api_key || '';
            document.getElementById('automatorEnabled').checked = automator.enabled;
            document.getElementById('dialogStatus').innerHTML = '';
            document.getElementById('automatorDialog').style.display = 'flex';
        }}

        async function saveAutomator(event) {{
            event.preventDefault();

            const automatorId = document.getElementById('automatorId').value;
            const isEdit = automatorId !== '';

            let url = document.getElementById('automatorUrl').value.trim();
            if (url && !url.startsWith('http://') && !url.startsWith('https://')) {{
                url = 'http://' + url;
            }}

            const automator = {{
                id: automatorId || `auto_${{Date.now()}}`,
                name: document.getElementById('automatorName').value.trim(),
                url: url,
                api_key: document.getElementById('automatorApiKey').value.trim(),
                enabled: document.getElementById('automatorEnabled').checked
            }};

            const endpoint = isEdit ? `/api/automators/${{automatorId}}` : '/api/automators';
            const method = isEdit ? 'PUT' : 'POST';

            try {{
                const response = await fetch(endpoint, {{
                    method: method,
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify(automator)
                }});

                if (response.ok) {{
                    document.getElementById('dialogStatus').innerHTML = '<div class="alert success">Automator saved successfully!</div>';
                    setTimeout(() => location.reload(), 1000);
                }} else {{
                    const error = await response.json();
                    document.getElementById('dialogStatus').innerHTML = `<div class="alert error">Error: ${{error.detail || 'Failed to save'}}</div>`;
                }}
            }} catch (e) {{
                document.getElementById('dialogStatus').innerHTML = `<div class="alert error">Error: ${{e.message}}</div>`;
            }}
        }}

        async function testAutomator(automatorId) {{
            const statusEl = document.getElementById(`status-${{automatorId}}`);
            statusEl.innerHTML = '<div class="alert info">Testing connection...</div>';

            const response = await fetch(`/api/automator/test?automator_id=${{automatorId}}`);
            const result = await response.json();

            if (result.connected) {{
                statusEl.innerHTML = '<div class="alert success">✓ Connection successful!</div>';
            }} else {{
                statusEl.innerHTML = `<div class="alert error">✗ Connection failed: ${{result.error}}</div>`;
            }}

            setTimeout(() => {{ statusEl.innerHTML = ''; }}, 3000);
        }}

        async function refreshAutomator(automatorId) {{
            const statusEl = document.getElementById(`status-${{automatorId}}`);
            statusEl.innerHTML = '<div class="alert info">Refreshing data...</div>';

            try {{
                const response = await fetch(`/api/automator/refresh?automator_id=${{automatorId}}`, {{method: 'POST'}});
                const result = await response.json();

                if (result.ok) {{
                    statusEl.innerHTML = `<div class="alert success">✓ Loaded ${{result.count}} items</div>`;
                    setTimeout(() => location.reload(), 1500);
                }} else {{
                    statusEl.innerHTML = `<div class="alert error">✗ Failed: ${{result.message || result.error}}</div>`;
                }}
            }} catch (e) {{
                statusEl.innerHTML = `<div class="alert error">✗ Error: ${{e.message}}</div>`;
            }}
        }}

        async function deleteAutomator(automatorId, automatorName) {{
            if (!confirm(`Are you sure you want to delete "${{automatorName}}"?`)) {{
                return;
            }}

            // Check for orphaned mappings first
            const checkResponse = await fetch(`/api/automators/${{automatorId}}`, {{method: 'DELETE'}});
            const checkData = await checkResponse.json();

            if (checkData.requires_confirmation && checkData.count > 0) {{
                const deleteAlso = confirm(`This Automator has ${{checkData.count}} command mapping(s).\\n\\nDo you want to delete these mappings as well?\\n\\nYes = Delete mappings\\nNo = Keep mappings (they will be orphaned)`);

                const confirmResponse = await fetch(`/api/automators/${{automatorId}}/delete?delete_mappings=${{deleteAlso}}`, {{method: 'POST'}});

                if (confirmResponse.ok) {{
                    location.reload();
                }} else {{
                    alert('Error deleting Automator');
                }}
            }} else {{
                // No mappings, proceed with deletion
                const confirmResponse = await fetch(`/api/automators/${{automatorId}}/delete?delete_mappings=false`, {{method: 'POST'}});

                if (confirmResponse.ok) {{
                    location.reload();
                }} else {{
                    alert('Error deleting Automator');
                }}
            }}
        }}

        // Switch Automator for viewing macros
        function switchAutomator() {{
            // Just reload with selected Automator (could be improved with AJAX)
            location.reload();
        }}

        // Test macro/button/shortcut with selected Automator
        async function testMacro(macroId, macroName, itemType = 'macro') {{
            const automatorId = document.getElementById('automatorSelector')?.value || '{selected_automator_id or ""}';

            fetch(`/api/automator/trigger/${{macroId}}?item_type=${{itemType}}&automator_id=${{automatorId}}`, {{method: 'POST'}})
                .then(response => {{
                    if (!response.ok) {{
                        console.error(`Error triggering ${{itemType}}: ${{macroName}}`);
                    }}
                }})
                .catch(err => console.error(`Error triggering ${{itemType}}: ${{macroName}}`, err));
        }}

        async function refreshMacros() {{
            const status = document.getElementById('refreshStatus');
            const btn = document.getElementById('refreshBtn');
            const automatorId = document.getElementById('automatorSelector')?.value || '{selected_automator_id or ""}';

            btn.disabled = true;
            btn.textContent = 'Loading...';
            status.innerHTML = '<div class="alert info">Refreshing data from Automator...</div>';

            try {{
                const response = await fetch(`/api/automator/refresh?automator_id=${{automatorId}}`, {{method: 'POST'}});
                const result = await response.json();

                if (result.ok) {{
                    status.innerHTML = `<div class="alert success">${{result.message}}</div>`;
                    setTimeout(() => location.reload(), 1000);
                }} else {{
                    status.innerHTML = `<div class="alert error">Failed to refresh: ${{result.error || result.message}}</div>`;
                    btn.disabled = false;
                    btn.textContent = 'Reload Macros';
                }}
            }} catch (e) {{
                status.innerHTML = `<div class="alert error">Error: ${{e.message}}</div>`;
                btn.disabled = false;
                btn.textContent = 'Reload Macros';
            }}
        }}

        function filterItems() {{
            const searchTerm = document.getElementById('searchBox').value.toLowerCase();
            const items = document.querySelectorAll('.searchable-item');

            let macrosVisible = 0;
            let buttonsVisible = 0;
            let shortcutsVisible = 0;

            items.forEach(item => {{
                const itemName = item.getAttribute('data-name');
                const itemType = item.getAttribute('data-type');
                const matches = itemName.includes(searchTerm);

                if (matches) {{
                    item.style.display = 'flex';
                    if (itemType === 'macros') macrosVisible++;
                    else if (itemType === 'buttons') buttonsVisible++;
                    else if (itemType === 'shortcuts') shortcutsVisible++;
                }} else {{
                    item.style.display = 'none';
                }}
            }});

            const macrosCount = document.getElementById('macros-count');
            const buttonsCount = document.getElementById('buttons-count');
            const shortcutsCount = document.getElementById('shortcuts-count');

            if (macrosCount) macrosCount.textContent = macrosVisible;
            if (buttonsCount) buttonsCount.textContent = buttonsVisible;
            if (shortcutsCount) shortcutsCount.textContent = shortcutsVisible;

            if (searchTerm) {{
                if (macrosVisible > 0) document.getElementById('macros-section').setAttribute('open', '');
                if (buttonsVisible > 0) document.getElementById('buttons-section').setAttribute('open', '');
                if (shortcutsVisible > 0) document.getElementById('shortcuts-section').setAttribute('open', '');
            }}
        }}
    </script>
    """

    return _get_base_html("Automator Controls", content, "automator")


@app.get("/command-mapping", response_class=HTMLResponse)
async def command_mapping_page():
    """Command Mapping page."""
    global config_data

    tcp_commands = config_data.get("tcp_commands", [])
    mappings = config_data.get("command_mappings", [])
    automators = get_all_automators()

    if not tcp_commands:
        content = """
        <h1>Command Mapping</h1>
        <div class="alert info">
            No TCP commands configured. Please add TCP commands first on the
            <a href="/tcp-commands" style="color: #00bcd4;">TCP Commands page</a>.
        </div>
        """
        return _get_base_html("Command Mapping", content, "mapping")

    if len(automators) == 0:
        content = """
        <h1>Command Mapping</h1>
        <div class="alert info">
            No Automators configured. Please configure Automator integration on the
            <a href="/automator-macros" style="color: #00bcd4;">Automator Controls page</a>.
        </div>
        """
        return _get_base_html("Command Mapping", content, "mapping")

    # Build Automator options HTML
    automator_options_html = ""
    for auto in automators:
        automator_options_html += f'<option value="{auto["id"]}">{auto["name"]}</option>'

    # Collect all macros from all Automators (for JavaScript)
    all_macros_by_automator = {}
    for auto in automators:
        macros = fetch_automator_macros(auto["id"])
        all_macros_by_automator[auto["id"]] = macros

    # Build mapping table
    table_rows = ""
    for tcp_cmd in tcp_commands:
        tcp_id = tcp_cmd["id"]
        tcp_name = tcp_cmd["name"]
        tcp_trigger = tcp_cmd["tcp_trigger"]

        # Find current mapping
        current_mapping = None
        for m in mappings:
            if m["tcp_command_id"] == tcp_id:
                current_mapping = m
                break

        # Get current automator_id and macro
        current_automator_id = current_mapping.get("automator_id", "") if current_mapping else ""
        current_macro_id = current_mapping.get("automator_macro_id", "") if current_mapping else ""
        current_macro_name = current_mapping.get("automator_macro_name", "") if current_mapping else ""
        current_item_type = current_mapping.get("item_type", "macro") if current_mapping else "macro"

        # Build current display value
        type_label = f" [{current_item_type}]" if current_item_type and current_macro_name else ""
        current_value = f"{current_macro_name}{type_label}" if current_macro_name else ""

        # Build datalist for this TCP command (will be dynamically updated by JavaScript)
        options_html = ""
        if current_automator_id:
            macros = all_macros_by_automator.get(current_automator_id, [])
            for macro in macros:
                macro_id = macro.get("id", "")
                macro_name = macro.get("title", macro.get("name", "Unknown"))
                macro_type = macro.get("type", "")
                type_label_opt = f" [{macro_type}]" if macro_type else ""
                display_text = f"{macro_name}{type_label_opt}"
                options_html += f'<option value="{display_text}" data-id="{macro_id}" data-type="{macro_type}">'

        # Build Automator selector with current value
        automator_select_html = f'<select class="automator-select" data-tcp-id="{tcp_id}" onchange="automatorChanged(\'{tcp_id}\')" style="width: 100%; padding: 8px; margin-bottom: 8px;">'
        if not current_automator_id:
            automator_select_html += '<option value="">-- Select Automator --</option>'
        for auto in automators:
            selected = 'selected' if auto["id"] == current_automator_id else ''
            automator_select_html += f'<option value="{auto["id"]}" {selected}>{auto["name"]}</option>'
        automator_select_html += '</select>'

        table_rows += f"""
        <tr class="searchable-mapping-row" data-tcp-name="{tcp_name.lower()}" data-tcp-trigger="{tcp_trigger.lower()}" data-automator-name="{current_value.lower()}">
            <td><strong>{tcp_name}</strong><br><span style="color: #888888; font-size: 12px;">{tcp_trigger}</span></td>
            <td>
                {automator_select_html}
                <input list="macros-{tcp_id}" class="mapping-input" data-tcp-id="{tcp_id}" value="{current_value}"
                       placeholder="Select Automator first, then type to search..." style="width: 100%; padding: 8px;" onchange="saveMapping('{tcp_id}')">
                <datalist id="macros-{tcp_id}">
                    {options_html}
                </datalist>
            </td>
            <td style="text-align: center; vertical-align: middle;">
                <button class="play-btn" onclick="testMapping('{tcp_id}')" title="Test this mapping">▶</button>
            </td>
        </tr>
        """

    content = f"""
    <h1>Command Mapping</h1>

    <div class="section">
        <h2>Map TCP Commands to Automator Macros</h2>
        <p style="color: #888888; margin-bottom: 20px;">
            Link incoming TCP commands to trigger specific Automator macros.
        </p>

        <div style="margin-bottom: 20px;">
            <input type="text" id="mappingSearchBox" placeholder="Search mappings by TCP command or Automator item name..." style="width: 100%; padding: 10px 14px; font-size: 14px; border-radius: 8px;" oninput="filterMappings()">
        </div>

        <div class="mapping-grid">
            <table class="mapping-table">
                <thead>
                    <tr>
                        <th style="width: 25%;">TCP Command</th>
                        <th style="width: 65%;">Automator & Macro</th>
                        <th style="text-align: center; width: 10%;">Test</th>
                    </tr>
                </thead>
                <tbody id="mappings-tbody">
                    {table_rows}
                </tbody>
            </table>
        </div>
    </div>

    <div id="mappingStatus" class="mt-20"></div>

    <script>
        // All macros organized by Automator ID
        const macrosByAutomator = {json.dumps(all_macros_by_automator)};

        // Handle Automator selection change
        function automatorChanged(tcpId) {{
            const automatorSelect = document.querySelector(`select.automator-select[data-tcp-id="${{tcpId}}"]`);
            const automatorId = automatorSelect.value;
            const input = document.querySelector(`input.mapping-input[data-tcp-id="${{tcpId}}"]`);
            const datalist = document.getElementById(`macros-${{tcpId}}`);

            // Clear current macro selection
            input.value = '';

            // Rebuild datalist options for selected Automator
            datalist.innerHTML = '';
            if (automatorId && macrosByAutomator[automatorId]) {{
                const macros = macrosByAutomator[automatorId];
                macros.forEach(macro => {{
                    const macroName = macro.title || macro.name || 'Unknown';
                    const macroType = macro.type || '';
                    const typeLabel = macroType ? ` [${{macroType}}]` : '';
                    const displayText = macroName + typeLabel;

                    const option = document.createElement('option');
                    option.value = displayText;
                    option.setAttribute('data-id', macro.id);
                    option.setAttribute('data-type', macroType);
                    datalist.appendChild(option);
                }});
            }}
        }}

        async function saveMapping(tcpId) {{
            const automatorSelect = document.querySelector(`select.automator-select[data-tcp-id="${{tcpId}}"]`);
            const automatorId = automatorSelect.value;
            const input = document.querySelector(`input[data-tcp-id="${{tcpId}}"]`);
            const displayValue = input.value.trim();
            const status = document.getElementById('mappingStatus');

            if (!automatorId) {{
                status.innerHTML = '<div class="alert error">Please select an Automator first</div>';
                setTimeout(() => status.innerHTML = '', 3000);
                return;
            }}

            if (!displayValue) {{
                // Remove mapping
                await removeMappingForTcpCommand(tcpId);
                status.innerHTML = '<div class="alert info">Mapping removed</div>';
                setTimeout(() => status.innerHTML = '', 2000);
                return;
            }}

            // Find the macro by matching the display text in the selected Automator
            const macros = macrosByAutomator[automatorId] || [];
            const macro = macros.find(m => {{
                const type_label = m.type ? ` [${{m.type}}]` : '';
                return ((m.title || m.name || '') + type_label) === displayValue;
            }});

            if (!macro) {{
                status.innerHTML = '<div class="alert error">Please select a valid macro from the list</div>';
                setTimeout(() => status.innerHTML = '', 3000);
                return;
            }}

            const macroId = macro.id;
            const macroName = macro.title || macro.name || '';
            const macroType = macro.type || 'macro';

            await updateMapping(tcpId, automatorId, macroId, macroName, macroType);
            status.innerHTML = '<div class="alert success">Mapping saved</div>';
            setTimeout(() => status.innerHTML = '', 2000);
        }}

        async function testMapping(tcpId) {{
            const automatorSelect = document.querySelector(`select.automator-select[data-tcp-id="${{tcpId}}"]`);
            const automatorId = automatorSelect.value;
            const input = document.querySelector(`input[data-tcp-id="${{tcpId}}"]`);
            const displayValue = input.value.trim();
            const status = document.getElementById('mappingStatus');

            if (!automatorId) {{
                status.innerHTML = '<div class="alert error">Please select an Automator first</div>';
                setTimeout(() => status.innerHTML = '', 3000);
                return;
            }}

            if (!displayValue) {{
                status.innerHTML = '<div class="alert error">No mapping configured for this command</div>';
                setTimeout(() => status.innerHTML = '', 3000);
                return;
            }}

            // Find the macro by matching the display text
            const macros = macrosByAutomator[automatorId] || [];
            const macro = macros.find(m => {{
                const type_label = m.type ? ` [${{m.type}}]` : '';
                return ((m.title || m.name || '') + type_label) === displayValue;
            }});

            if (!macro) {{
                status.innerHTML = '<div class="alert error">Invalid mapping - please select from the list</div>';
                setTimeout(() => status.innerHTML = '', 3000);
                return;
            }}

            // Trigger the macro with automator_id
            status.innerHTML = '<div class="alert info">Testing mapping...</div>';
            try {{
                const response = await fetch(`/api/automator/trigger/${{macro.id}}?item_type=${{macro.type || 'macro'}}&automator_id=${{automatorId}}`, {{method: 'POST'}});
                if (response.ok) {{
                    status.innerHTML = '<div class="alert success">Mapping tested successfully!</div>';
                }} else {{
                    status.innerHTML = '<div class="alert error">Failed to trigger macro</div>';
                }}
                setTimeout(() => status.innerHTML = '', 3000);
            }} catch (e) {{
                status.innerHTML = `<div class="alert error">Error: ${{e.message}}</div>`;
                setTimeout(() => status.innerHTML = '', 3000);
            }}
        }}

        async function saveAllMappings() {{
            const inputs = document.querySelectorAll('.mapping-input');
            const newMappings = [];

            for (const input of inputs) {{
                const tcpId = input.dataset.tcpId;
                const displayValue = input.value.trim();

                if (displayValue) {{
                    // Find the macro by matching the display text
                    const macro = macros.find(m => {{
                        const type_label = m.type ? ` [${{m.type}}]` : '';
                        return ((m.title || m.name || '') + type_label) === displayValue;
                    }});

                    if (macro) {{
                        newMappings.push({{
                            tcp_command_id: tcpId,
                            automator_macro_id: macro.id,
                            automator_macro_name: macro.title || macro.name || '',
                            automator_macro_type: macro.type || 'macro'
                        }});
                    }}
                }}
            }}

            const response = await fetch('/api/config', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{command_mappings: newMappings}})
            }});

            const status = document.getElementById('mappingStatus');
            if (response.ok) {{
                status.innerHTML = '<div class="alert success">All mappings saved successfully!</div>';
                setTimeout(() => status.innerHTML = '', 3000);
            }} else {{
                status.innerHTML = '<div class="alert error">Error saving mappings.</div>';
            }}
        }}

        async function updateMapping(tcpId, automatorId, macroId, macroName, macroType) {{
            const currentMappings = {json.dumps(mappings)};

            // Remove existing mapping for this TCP command
            const filteredMappings = currentMappings.filter(m => m.tcp_command_id !== tcpId);

            // Add new mapping with automator_id
            filteredMappings.push({{
                tcp_command_id: tcpId,
                automator_id: automatorId,
                automator_macro_id: macroId,
                automator_macro_name: macroName,
                item_type: macroType
            }});

            const response = await fetch('/api/config', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{command_mappings: filteredMappings}})
            }});

            const status = document.getElementById('mappingStatus');
            if (response.ok) {{
                status.innerHTML = '<div class="alert success">Mapping saved!</div>';
                setTimeout(() => status.innerHTML = '', 2000);
            }} else {{
                status.innerHTML = '<div class="alert error">Error saving mapping.</div>';
            }}
        }}

        async function removeMappingForTcpCommand(tcpId) {{
            const currentMappings = {json.dumps(mappings)};
            const filteredMappings = currentMappings.filter(m => m.tcp_command_id !== tcpId);

            const response = await fetch('/api/config', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{command_mappings: filteredMappings}})
            }});

            const status = document.getElementById('mappingStatus');
            if (response.ok) {{
                status.innerHTML = '<div class="alert success">Mapping removed!</div>';
                setTimeout(() => status.innerHTML = '', 2000);
            }}
        }}

        function filterMappings() {{
            const searchTerm = document.getElementById('mappingSearchBox').value.toLowerCase();
            const rows = document.querySelectorAll('.searchable-mapping-row');

            rows.forEach(row => {{
                const tcpName = row.getAttribute('data-tcp-name');
                const tcpTrigger = row.getAttribute('data-tcp-trigger');
                const automatorName = row.getAttribute('data-automator-name');
                const matches = tcpName.includes(searchTerm) || tcpTrigger.includes(searchTerm) || automatorName.includes(searchTerm);

                if (matches) {{
                    row.style.display = '';
                }} else {{
                    row.style.display = 'none';
                }}
            }});
        }}
    </script>
    """

    return _get_base_html("Command Mapping", content, "mapping")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    """Settings page with theme toggle and config backup."""
    global config_data

    theme = config_data.get("theme", "dark")
    is_light = theme == "light"

    parts = []
    parts.append("<!DOCTYPE html>")
    parts.append("<html><head>")
    parts.append("<title>Settings - Elliott's Sony Automator Controls</title>")
    parts.append(_get_base_styles())
    parts.append("</head><body>")
    parts.append(_get_nav_html("settings"))
    parts.append("<h1>Settings</h1>")

    # Theme toggle styles
    parts.append("<style>")
    parts.append("  .theme-toggle { display: flex; align-items: center; gap: 12px; margin: 16px 0; }")
    parts.append("  .theme-toggle-label { font-size: 14px; min-width: 50px; }")
    parts.append("  .toggle-switch { position: relative; width: 50px; height: 26px; }")
    parts.append("  .toggle-switch input { opacity: 0; width: 0; height: 0; }")
    parts.append("  .toggle-slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background: #30363d; border-radius: 26px; transition: 0.3s; }")
    parts.append("  .toggle-slider:before { position: absolute; content: ''; height: 20px; width: 20px; left: 3px; bottom: 3px; background: white; border-radius: 50%; transition: 0.3s; }")
    parts.append("  .toggle-switch input:checked + .toggle-slider { background: #00bcd4; }")
    parts.append("  .toggle-switch input:checked + .toggle-slider:before { transform: translateX(24px); }")
    parts.append("</style>")

    # General section
    parts.append("<fieldset><legend>General</legend>")
    parts.append('<div class="theme-toggle">')
    parts.append('<span class="theme-toggle-label">Dark</span>')
    parts.append(f'<label class="toggle-switch"><input type="checkbox" id="theme-toggle" {"checked" if is_light else ""} onchange="toggleTheme()" /><span class="toggle-slider"></span></label>')
    parts.append('<span class="theme-toggle-label">Light</span>')
    parts.append('</div>')
    parts.append(f"<p><strong>Server Port:</strong> <code>{effective_port()}</code> (change via GUI launcher)</p>")
    parts.append(f"<p><strong>Version:</strong> <code>{__version__}</code></p>")
    parts.append(f"<p><strong>Config file:</strong> <code>{CONFIG_FILE}</code></p>")
    parts.append("</fieldset>")

    # Config Import/Export section
    parts.append("<fieldset><legend>Config Backup</legend>")
    parts.append("<p>Export your current configuration or import a previously saved config.</p>")
    parts.append('<button type="button" onclick="exportConfig()">Export Config</button>')
    parts.append('<input type="file" id="import-file" accept=".json" style="display:none;" onchange="importConfig()" />')
    parts.append('<button type="button" onclick="document.getElementById(\'import-file\').click()">Import Config</button>')
    parts.append('<pre id="import-output"></pre>')
    parts.append("</fieldset>")

    # Updates section
    parts.append("<fieldset><legend>Updates</legend>")
    parts.append(f"<p>Current version: <code>{__version__}</code></p>")
    parts.append('<button type="button" onclick="checkUpdates()">Check GitHub for latest release</button>')
    parts.append('<pre id="update-output">Not checked yet.</pre>')
    parts.append("</fieldset>")

    # JavaScript
    parts.append("<script>")
    parts.append("async function postJSON(url, data) {")
    parts.append("  const res = await fetch(url, {")
    parts.append('    method: "POST",')
    parts.append('    headers: { "Content-Type": "application/json" },')
    parts.append("    body: JSON.stringify(data),")
    parts.append("  });")
    parts.append("  return res.json();")
    parts.append("}")
    parts.append("async function toggleTheme() {")
    parts.append('  const isLight = document.getElementById("theme-toggle").checked;')
    parts.append('  const theme = isLight ? "light" : "dark";')
    parts.append('  await postJSON("/settings", { theme });')
    parts.append("  location.reload();")
    parts.append("}")
    parts.append("async function checkUpdates() {")
    parts.append('  const out = document.getElementById("update-output");')
    parts.append('  out.textContent = "Checking for updates...";')
    parts.append("  try {")
    parts.append('    const res = await fetch("/version/check");')
    parts.append("    const data = await res.json();")
    parts.append("    let msg = 'Current version: ' + data.current;")
    parts.append("    if (data.latest) {")
    parts.append("      msg += '\\nLatest release: ' + data.latest;")
    parts.append("    }")
    parts.append("    msg += '\\n\\n' + data.message;")
    parts.append("    if (data.release_url && !data.up_to_date) {")
    parts.append("      msg += '\\n\\nDownload: ' + data.release_url;")
    parts.append("    }")
    parts.append("    out.textContent = msg;")
    parts.append("  } catch (e) {")
    parts.append("    out.textContent = 'Version check failed: ' + e;")
    parts.append("  }")
    parts.append("}")
    parts.append("async function exportConfig() {")
    parts.append("  try {")
    parts.append('    const res = await fetch("/config/export");')
    parts.append("    const config = await res.json();")
    parts.append("    const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });")
    parts.append("    const url = URL.createObjectURL(blob);")
    parts.append("    const a = document.createElement('a');")
    parts.append("    a.href = url;")
    parts.append("    a.download = 'sony_automator_config.json';")
    parts.append("    a.click();")
    parts.append("    URL.revokeObjectURL(url);")
    parts.append('    document.getElementById("import-output").textContent = "Config exported successfully!";')
    parts.append("  } catch (e) {")
    parts.append('    document.getElementById("import-output").textContent = "Export failed: " + e;')
    parts.append("  }")
    parts.append("}")
    parts.append("async function importConfig() {")
    parts.append('  const fileInput = document.getElementById("import-file");')
    parts.append("  const file = fileInput.files[0];")
    parts.append("  if (!file) return;")
    parts.append("  try {")
    parts.append("    const text = await file.text();")
    parts.append("    const config = JSON.parse(text);")
    parts.append('    const res = await fetch("/config/import", {')
    parts.append('      method: "POST",')
    parts.append('      headers: { "Content-Type": "application/json" },')
    parts.append("      body: JSON.stringify(config),")
    parts.append("    });")
    parts.append("    const data = await res.json();")
    parts.append('    document.getElementById("import-output").textContent = data.message || "Config imported!";')
    parts.append("    setTimeout(() => location.reload(), 2000);")
    parts.append("  } catch (e) {")
    parts.append('    document.getElementById("import-output").textContent = "Import failed: " + e;')
    parts.append("  }")
    parts.append("}")
    parts.append("checkUpdates();")
    parts.append("</script>")
    parts.append("</body></html>")

    return HTMLResponse("".join(parts))


# API Endpoints
@app.get("/api/status")
async def api_status():
    """Get system status."""
    global config_data, tcp_servers, automator_status

    tcp_status = {}
    for listener in config_data.get("tcp_listeners", []):
        port = listener["port"]
        tcp_status[port] = {
            "name": listener["name"],
            "enabled": listener["enabled"],
            "running": port in tcp_servers,
            "connections": len(tcp_connections.get(port, []))
        }

    return {
        "tcp_listeners": tcp_status,
        "automator": automator_status,
        "uptime": int(time.time() - server_start_time)
    }


@app.get("/api/automator/test")
async def api_automator_test(automator_id: Optional[str] = None):
    """Test Automator connection."""
    return check_automator_connection(automator_id)


@app.post("/api/automator/refresh")
async def api_automator_refresh(automator_id: Optional[str] = None):
    """Force refresh Automator data from API."""
    try:
        items = fetch_automator_macros(automator_id, force_refresh=True)
        return {
            "ok": True,
            "count": len(items),
            "message": f"Loaded {len(items)} items"
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "message": "Failed to refresh data"
        }


@app.post("/api/automator/trigger/{macro_id}")
async def api_trigger_macro(macro_id: str, item_type: str = "macro", automator_id: Optional[str] = None):
    """Manually trigger an Automator macro, button, or shortcut."""
    await trigger_automator_macro(macro_id, f"Manual trigger: {macro_id}", item_type, automator_id)
    return {"success": True, "macro_id": macro_id, "type": item_type}


# New Automator Management Endpoints
@app.get("/api/automators")
async def api_get_automators():
    """Get all Automator configurations."""
    return {"automators": get_all_automators()}


@app.post("/api/automators")
async def api_add_automator(automator: AutomatorConfig):
    """Add new Automator."""
    global config_data
    import uuid

    automators = config_data.get("automators", [])

    # Generate ID if not provided
    if not automator.id:
        automator.id = f"auto_{uuid.uuid4().hex[:8]}"

    # Check if ID already exists
    if any(a["id"] == automator.id for a in automators):
        raise HTTPException(400, "Automator ID already exists")

    automators.append(automator.dict())
    config_data["automators"] = automators
    save_config(config_data)

    log_event("Config", f"Added Automator: {automator.name}")
    return {"success": True, "automator": automator.dict()}


@app.put("/api/automators/{automator_id}")
async def api_update_automator(automator_id: str, automator: AutomatorConfig):
    """Update existing Automator."""
    global config_data

    automators = config_data.get("automators", [])
    found = False

    for i, a in enumerate(automators):
        if a["id"] == automator_id:
            automators[i] = automator.dict()
            found = True
            break

    if not found:
        raise HTTPException(404, "Automator not found")

    config_data["automators"] = automators
    save_config(config_data)

    log_event("Config", f"Updated Automator: {automator.name}")
    return {"success": True, "automator": automator.dict()}


@app.delete("/api/automators/{automator_id}")
async def api_delete_automator(automator_id: str):
    """Check for orphaned mappings before deletion."""
    global config_data

    automator = get_automator_by_id(automator_id)
    if not automator:
        raise HTTPException(404, "Automator not found")

    # Check for orphaned mappings
    mappings = config_data.get("command_mappings", [])
    orphaned = [m for m in mappings if m.get("automator_id") == automator_id]

    return {
        "automator": automator,
        "orphaned_mappings": orphaned,
        "count": len(orphaned),
        "requires_confirmation": len(orphaned) > 0
    }


@app.post("/api/automators/{automator_id}/delete")
async def api_delete_automator_confirm(automator_id: str, delete_mappings: bool = True):
    """Confirm deletion of Automator and handle orphaned mappings."""
    global config_data

    # Remove Automator
    automators = config_data.get("automators", [])
    config_data["automators"] = [a for a in automators if a["id"] != automator_id]

    # Handle mappings
    deleted_count = 0
    if delete_mappings:
        mappings = config_data.get("command_mappings", [])
        old_count = len(mappings)
        config_data["command_mappings"] = [m for m in mappings if m.get("automator_id") != automator_id]
        deleted_count = old_count - len(config_data["command_mappings"])

    save_config(config_data)
    log_event("Config", f"Deleted Automator: {automator_id} ({deleted_count} mappings removed)")

    return {"success": True, "deleted_mappings": deleted_count}


@app.post("/api/config")
async def api_update_config(config_update: ConfigUpdate):
    """Update configuration."""
    global config_data

    # Update config
    if config_update.tcp_listeners is not None:
        config_data["tcp_listeners"] = [l.dict() for l in config_update.tcp_listeners]
        log_event("Config", f"Updated TCP listeners ({len(config_update.tcp_listeners)} listeners)")

    if config_update.tcp_commands is not None:
        config_data["tcp_commands"] = [c.dict() for c in config_update.tcp_commands]
        log_event("Config", f"Updated TCP commands ({len(config_update.tcp_commands)} commands)")

    if config_update.automators is not None:
        config_data["automators"] = [a.dict() for a in config_update.automators]
        log_event("Config", f"Updated Automators ({len(config_update.automators)} configured)")

    if config_update.first_run is not None:
        config_data["first_run"] = config_update.first_run
        if not config_update.first_run:
            log_event("Config", "Welcome banner dismissed")

    if config_update.command_mappings is not None:
        config_data["command_mappings"] = [m.dict() for m in config_update.command_mappings]
        log_event("Config", f"Updated command mappings ({len(config_update.command_mappings)} mappings)")

    if config_update.web_port is not None:
        config_data["web_port"] = config_update.web_port
        log_event("Config", f"Updated web port to {config_update.web_port}")

    # Save config
    save_config(config_data)

    # Restart TCP servers if listeners changed
    if config_update.tcp_listeners is not None:
        await restart_tcp_servers()

    return {"success": True}


@app.get("/api/config")
async def api_get_config():
    """Get current configuration."""
    return config_data


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": _runtime_version(),
        "port": effective_port(),
        "log_file": str(_log_file_path)
    }


@app.get("/events")
async def get_events():
    """Get recent command/event log entries."""
    return {"events": COMMAND_LOG[-100:]}


@app.get("/logs/export")
async def export_logs():
    """Export full log file for download."""
    if not _log_file_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    try:
        with open(_log_file_path, 'r', encoding='utf-8') as f:
            log_content = f.read()

        from fastapi.responses import Response
        return Response(
            content=log_content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename=sony_automator_controls_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            }
        )
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading log file: {str(e)}")


@app.get("/logs/view")
async def view_logs(lines: int = 500):
    """View last N lines of log file."""
    if not _log_file_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    try:
        with open(_log_file_path, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

        return {
            "log_file": str(_log_file_path),
            "total_lines": len(all_lines),
            "showing_lines": len(last_lines),
            "logs": ''.join(last_lines)
        }
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading log file: {str(e)}")


@app.post("/tcp/capture/start")
async def start_tcp_capture():
    """Start listening for the next TCP command."""
    global tcp_capture_active, tcp_capture_result
    tcp_capture_active = True
    tcp_capture_result = None
    log_event("TCP Capture", "Started listening for TCP command")
    return {"status": "listening", "message": "Waiting for next TCP command..."}


@app.get("/tcp/capture/status")
async def get_tcp_capture_status():
    """Get current TCP capture status."""
    global tcp_capture_active, tcp_capture_result
    if tcp_capture_result:
        result = tcp_capture_result
        tcp_capture_result = None  # Clear after reading
        return {"status": "captured", "data": result}
    elif tcp_capture_active:
        return {"status": "listening", "data": None}
    else:
        return {"status": "idle", "data": None}


@app.post("/tcp/capture/cancel")
async def cancel_tcp_capture():
    """Cancel TCP capture mode."""
    global tcp_capture_active, tcp_capture_result
    tcp_capture_active = False
    tcp_capture_result = None
    log_event("TCP Capture", "Cancelled")
    return {"status": "cancelled"}


@app.get("/settings/json")
async def get_settings_json():
    """Get current settings as JSON."""
    return {
        "port": effective_port(),
        "raw_port": config_data.get("web_port", 3114),
        "theme": config_data.get("theme", "dark"),
        "config_path": str(CONFIG_FILE),
    }


@app.post("/settings")
async def update_settings(settings: SettingsIn):
    """Update settings."""
    if settings.web_port is not None:
        config_data["web_port"] = settings.web_port
        log_event("CONFIG", f"Web port updated to {settings.web_port}")
    if settings.theme is not None:
        config_data["theme"] = settings.theme
        log_event("CONFIG", f"Theme changed to {settings.theme}")

    save_config(config_data)

    return {
        "ok": True,
        "message": "Settings updated.",
        "port": effective_port(),
        "theme": config_data.get("theme", "dark"),
    }


@app.get("/config/export")
async def export_config():
    """Export current configuration as JSON for backup."""
    return config_data


@app.post("/config/import")
async def import_config(config: Dict[str, Any]):
    """Import configuration from JSON backup."""
    try:
        # Update config_data with imported data
        if "theme" in config:
            config_data["theme"] = config["theme"]
        if "web_port" in config:
            config_data["web_port"] = config["web_port"]
        if "tcp_listeners" in config:
            config_data["tcp_listeners"] = config["tcp_listeners"]
        if "tcp_commands" in config:
            config_data["tcp_commands"] = config["tcp_commands"]
        if "automator" in config:
            config_data["automator"] = config["automator"]
        if "command_mappings" in config:
            config_data["command_mappings"] = config["command_mappings"]

        save_config(config_data)
        log_event("CONFIG", "Configuration imported successfully")

        return {
            "ok": True,
            "message": "Configuration imported successfully. Some changes may require restart.",
        }
    except Exception as e:
        logger.error(f"Config import failed: {e}")
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")


@app.get("/version/check")
async def check_version():
    """Check for updates against GitHub releases."""
    current = __version__
    try:
        resp = requests.get(
            "https://api.github.com/repos/BlueElliott/Elliotts-Sony-Automator-Controls/releases/latest",
            timeout=5
        )
        if resp.status_code == 404:
            return {
                "current": current,
                "latest": None,
                "up_to_date": True,
                "message": "Repository is private or has no public releases",
            }
        resp.raise_for_status()
        data = resp.json()
        latest = data.get("tag_name", "unknown")
        release_url = data.get("html_url", "")

        # Normalize versions for comparison (remove 'v' prefix if present)
        current_normalized = current.lstrip('v')
        latest_normalized = latest.lstrip('v')
        up_to_date = current_normalized == latest_normalized

        return {
            "current": current,
            "latest": latest,
            "up_to_date": up_to_date,
            "release_url": release_url,
            "message": "You are up to date" if up_to_date else "A newer version is available",
        }
    except requests.RequestException as e:
        logger.error("Version check failed: %s", e)
        return {
            "current": current,
            "latest": None,
            "up_to_date": True,
            "message": f"Version check failed: {str(e)}",
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=3114)
