"""Core application logic for Sony Automator Controls."""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Version
__version__ = "1.0.0"

# Global state
tcp_servers: Dict[int, asyncio.Server] = {}
tcp_connections: Dict[int, List[tuple]] = {}
automator_status = {"connected": False, "last_check": None, "error": None}
config_data = {}
server_start_time = time.time()

# Configuration file path
CONFIG_DIR = Path.home() / ".sony_automator_controls"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Default configuration
DEFAULT_CONFIG = {
    "version": __version__,
    "theme": "dark",
    "web_port": 3114,
    "tcp_listeners": [
        {"port": 9001, "name": "Default TCP Listener", "enabled": True}
    ],
    "tcp_commands": [
        {"id": "cmd_1", "name": "Test Command 1", "tcp_trigger": "TEST1", "description": "Test command 1"},
        {"id": "cmd_2", "name": "Test Command 2", "tcp_trigger": "TEST2", "description": "Test command 2"}
    ],
    "automator": {
        "url": "",
        "api_key": "",
        "enabled": False
    },
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
    url: str
    api_key: str = ""
    enabled: bool


class CommandMapping(BaseModel):
    tcp_command_id: str
    automator_macro_id: str
    automator_macro_name: str = ""


class ConfigUpdate(BaseModel):
    tcp_listeners: Optional[List[TCPListener]] = None
    tcp_commands: Optional[List[TCPCommand]] = None
    automator: Optional[AutomatorConfig] = None
    command_mappings: Optional[List[CommandMapping]] = None
    web_port: Optional[int] = None


# Configuration management
def ensure_config_dir():
    """Ensure configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load configuration from file."""
    ensure_config_dir()

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"Configuration loaded from {CONFIG_FILE}")
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


# TCP Server implementation
async def handle_tcp_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, port: int):
    """Handle individual TCP client connection."""
    addr = writer.get_extra_info('peername')
    logger.info(f"TCP client connected from {addr} on port {port}")

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
            logger.info(f"Received TCP command on port {port}: {message}")

            # Process the command
            await process_tcp_command(message, port)

    except Exception as e:
        logger.error(f"Error handling TCP client {addr}: {e}")
    finally:
        logger.info(f"TCP client disconnected: {addr}")
        tcp_connections[port] = [conn for conn in tcp_connections[port] if conn[0] != addr]
        writer.close()
        await writer.wait_closed()


async def process_tcp_command(command: str, port: int):
    """Process incoming TCP command and trigger corresponding HTTP action."""
    global config_data

    logger.info(f"Processing TCP command: {command} from port {port}")

    # Find matching TCP command in config
    tcp_cmd = None
    for cmd in config_data.get("tcp_commands", []):
        if cmd["tcp_trigger"].upper() == command.upper():
            tcp_cmd = cmd
            break

    if not tcp_cmd:
        logger.warning(f"No TCP command definition found for: {command}")
        return

    logger.info(f"Matched TCP command: {tcp_cmd['name']} (ID: {tcp_cmd['id']})")

    # Find command mapping
    mapping = None
    for m in config_data.get("command_mappings", []):
        if m["tcp_command_id"] == tcp_cmd["id"]:
            mapping = m
            break

    if not mapping:
        logger.warning(f"No mapping found for TCP command: {tcp_cmd['name']}")
        return

    logger.info(f"Found mapping to Automator macro: {mapping['automator_macro_name']} (ID: {mapping['automator_macro_id']})")

    # Trigger HTTP request to Automator
    await trigger_automator_macro(mapping["automator_macro_id"], mapping["automator_macro_name"])


async def trigger_automator_macro(macro_id: str, macro_name: str):
    """Trigger an Automator macro via HTTP."""
    global config_data

    automator_config = config_data.get("automator", {})

    if not automator_config.get("enabled"):
        logger.warning("Automator integration is disabled")
        return

    url = automator_config.get("url", "").rstrip("/")
    api_key = automator_config.get("api_key", "")

    if not url:
        logger.error("Automator URL not configured")
        return

    # Construct HTTP request (adjust based on your Automator API)
    endpoint = f"{url}/api/macro/{macro_id}/trigger"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        logger.info(f"Triggering Automator macro: {macro_name} at {endpoint}")
        response = requests.post(endpoint, headers=headers, timeout=5)
        response.raise_for_status()
        logger.info(f"Successfully triggered macro: {macro_name}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error triggering Automator macro {macro_name}: {e}")


async def start_tcp_server(port: int):
    """Start a TCP server on specified port."""
    global tcp_servers

    if port in tcp_servers:
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
        logger.info(f"TCP server started on port {port}")

        # Start serving in background
        asyncio.create_task(server.serve_forever())

    except Exception as e:
        logger.error(f"Error starting TCP server on port {port}: {e}")


async def stop_tcp_server(port: int):
    """Stop TCP server on specified port."""
    global tcp_servers

    if port not in tcp_servers:
        logger.warning(f"No TCP server running on port {port}")
        return

    try:
        server = tcp_servers[port]
        server.close()
        await server.wait_closed()
        del tcp_servers[port]
        if port in tcp_connections:
            del tcp_connections[port]
        logger.info(f"TCP server stopped on port {port}")
    except Exception as e:
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


def check_automator_connection() -> dict:
    """Check connection to Automator API."""
    global config_data, automator_status

    automator_config = config_data.get("automator", {})

    if not automator_config.get("enabled") or not automator_config.get("url"):
        automator_status = {"connected": False, "last_check": datetime.now().isoformat(), "error": "Not configured"}
        return automator_status

    url = automator_config.get("url", "").rstrip("/")
    api_key = automator_config.get("api_key", "")

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.get(f"{url}/api/status", headers=headers, timeout=3)
        response.raise_for_status()
        automator_status = {"connected": True, "last_check": datetime.now().isoformat(), "error": None}
    except requests.exceptions.RequestException as e:
        automator_status = {"connected": False, "last_check": datetime.now().isoformat(), "error": str(e)}

    return automator_status


def fetch_automator_macros() -> List[Dict[str, Any]]:
    """Fetch macros and shortcuts from Automator API."""
    global config_data

    automator_config = config_data.get("automator", {})

    if not automator_config.get("enabled") or not automator_config.get("url"):
        return []

    url = automator_config.get("url", "").rstrip("/")
    api_key = automator_config.get("api_key", "")

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.get(f"{url}/api/macros", headers=headers, timeout=5)
        response.raise_for_status()
        macros = response.json()
        logger.info(f"Fetched {len(macros)} macros from Automator")
        return macros
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Automator macros: {e}")
        return []


# Application lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global config_data

    # Startup
    logger.info("Starting Sony Automator Controls...")
    config_data = load_config()

    # Start TCP servers for enabled listeners
    for listener in config_data.get("tcp_listeners", []):
        if listener["enabled"]:
            await start_tcp_server(listener["port"])

    yield

    # Shutdown
    logger.info("Shutting down Sony Automator Controls...")
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

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }

        h1, h2, h3 {
            font-weight: 500;
            margin-bottom: 20px;
        }

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
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .status-card {
            background: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 8px;
            padding: 20px;
        }

        .status-card h3 {
            font-size: 16px;
            margin-bottom: 15px;
            color: #888888;
        }

        .status-indicator {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 10px;
        }

        .status-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            animation: pulse 1.5s ease-in-out infinite;
        }

        .status-dot.connected {
            background: #4caf50;
        }

        .status-dot.disconnected {
            background: #ef4444;
            animation: none;
        }

        .status-dot.idle {
            background: #888888;
            animation: none;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.6; transform: scale(1.1); }
        }

        .status-text {
            font-size: 16px;
            font-weight: 500;
        }

        .status-detail {
            font-size: 12px;
            color: #888888;
            margin-left: 24px;
        }

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

        /* Lists */
        .item-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .item {
            background: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            padding: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .item-info {
            flex: 1;
        }

        .item-title {
            font-weight: 500;
            margin-bottom: 5px;
        }

        .item-detail {
            font-size: 12px;
            color: #888888;
        }

        .item-actions {
            display: flex;
            gap: 8px;
        }

        .item-actions button {
            padding: 6px 12px;
            font-size: 12px;
        }

        /* Matrix/Grid */
        .mapping-grid {
            overflow-x: auto;
        }

        .mapping-table {
            min-width: 800px;
        }

        .mapping-cell {
            text-align: center;
        }

        .mapping-cell input[type="checkbox"] {
            width: auto;
            cursor: pointer;
        }

        /* Alerts */
        .alert {
            padding: 15px 20px;
            border-radius: 6px;
            margin-bottom: 20px;
        }

        .alert.info {
            background: rgba(0, 188, 212, 0.1);
            border: 1px solid #00bcd4;
            color: #00bcd4;
        }

        .alert.error {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid #ef4444;
            color: #ef4444;
        }

        .alert.success {
            background: rgba(34, 197, 94, 0.1);
            border: 1px solid #22c55e;
            color: #22c55e;
        }

        /* Utility classes */
        .flex {
            display: flex;
        }

        .flex-between {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .gap-10 {
            gap: 10px;
        }

        .mt-20 {
            margin-top: 20px;
        }

        .mb-20 {
            margin-bottom: 20px;
        }
    </style>
    """


def _get_nav_html(active_page: str = "home") -> str:
    """Return navigation HTML - fixed top-left style matching Elliott's."""
    pages = [
        ("home", "Home", "/"),
        ("tcp", "TCP Commands", "/tcp-commands"),
        ("automator", "Automator Macros", "/automator-macros"),
        ("mapping", "Command Mapping", "/command-mapping"),
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
        <title>{title} - Elliott's Sony Automator Controls</title>
        {_get_base_styles()}
    </head>
    <body>
        {_get_nav_html(active_page)}
        <h1>Elliott's Sony Automator Controls</h1>
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

    # Check Automator connection
    automator_status = check_automator_connection()

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

    # Automator status
    if automator_status["connected"]:
        auto_class = "connected"
        auto_text = "Connected"
        auto_detail = config_data.get("automator", {}).get("url", "")
    else:
        auto_class = "disconnected"
        auto_text = "Disconnected"
        auto_detail = automator_status.get("error", "Not configured")

    # Server uptime
    uptime_seconds = int(time.time() - server_start_time)
    hours = uptime_seconds // 3600
    minutes = (uptime_seconds % 3600) // 60
    uptime_text = f"{hours}h {minutes}m"

    content = f"""
    <h1>Dashboard</h1>

    <div class="section">
        <h2>Connection Status</h2>
        <div class="status-grid">
            {tcp_status_html}

            <div class="status-card">
                <h3>Automator API</h3>
                <div class="status-indicator">
                    <div class="status-dot {auto_class}"></div>
                    <span class="status-text">{auto_text}</span>
                </div>
                <div class="status-detail">{auto_detail}</div>
            </div>

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

    <script>
        // Auto-refresh every 5 seconds
        setTimeout(() => location.reload(), 5000);
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
        <div class="item">
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
        <div class="item-list">
            {commands_html}
        </div>
        <button class="primary mt-20" onclick="showAddCommandForm()">Add TCP Command</button>
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
            alert('Edit functionality coming soon!');
        }}
    </script>
    """

    return _get_base_html("TCP Commands", content, "tcp")


@app.get("/automator-macros", response_class=HTMLResponse)
async def automator_macros_page():
    """Automator Macros page."""
    global config_data

    automator_config = config_data.get("automator", {})

    # Configuration form
    url_value = automator_config.get("url", "")
    api_key_value = automator_config.get("api_key", "")
    enabled_checked = "checked" if automator_config.get("enabled") else ""

    config_form = f"""
    <div class="section">
        <h2>Automator Configuration</h2>
        <form id="automatorConfigForm">
            <div class="form-group">
                <label>Automator API URL</label>
                <input type="text" id="automatorUrl" value="{url_value}" placeholder="http://your-automator-server:port">
            </div>
            <div class="form-group">
                <label>API Key (if required)</label>
                <input type="text" id="automatorApiKey" value="{api_key_value}" placeholder="Optional API key">
            </div>
            <div class="form-group">
                <label>
                    <input type="checkbox" id="automatorEnabled" {enabled_checked} style="width: auto; margin-right: 8px;">
                    Enable Automator Integration
                </label>
            </div>
            <button type="submit" class="primary">Save Configuration</button>
            <button type="button" class="secondary" onclick="testConnection()">Test Connection</button>
        </form>
        <div id="configStatus" class="mt-20"></div>
    </div>
    """

    # Fetch macros if configured
    macros_html = ""
    if automator_config.get("enabled") and automator_config.get("url"):
        macros = fetch_automator_macros()

        if macros:
            for macro in macros:
                macro_id = macro.get("id", "")
                macro_name = macro.get("name", "Unknown")
                macro_type = macro.get("type", "macro")

                macros_html += f"""
                <div class="item">
                    <div class="item-info">
                        <div class="item-title">{macro_name}</div>
                        <div class="item-detail">ID: {macro_id} | Type: {macro_type}</div>
                    </div>
                    <div class="item-actions">
                        <button class="success" onclick="testMacro('{macro_id}', '{macro_name}')">Test</button>
                    </div>
                </div>
                """
        else:
            macros_html = '<div class="alert info">No macros found or unable to connect to Automator.</div>'
    else:
        macros_html = '<div class="alert info">Configure and enable Automator integration to see macros.</div>'

    macros_section = f"""
    <div class="section">
        <h2>Available Macros & Shortcuts</h2>
        <p style="color: #888888; margin-bottom: 20px;">Macros and shortcuts available in your Automator system.</p>
        <div class="item-list">
            {macros_html}
        </div>
        <button class="secondary mt-20" onclick="location.reload()">Refresh Macros</button>
    </div>
    """

    content = config_form + macros_section + """
    <script>
        document.getElementById('automatorConfigForm').addEventListener('submit', async (e) => {
            e.preventDefault();

            const url = document.getElementById('automatorUrl').value;
            const apiKey = document.getElementById('automatorApiKey').value;
            const enabled = document.getElementById('automatorEnabled').checked;

            const response = await fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    automator: {
                        url: url,
                        api_key: apiKey,
                        enabled: enabled
                    }
                })
            });

            const status = document.getElementById('configStatus');
            if (response.ok) {
                status.innerHTML = '<div class="alert success">Configuration saved successfully!</div>';
                setTimeout(() => location.reload(), 1500);
            } else {
                status.innerHTML = '<div class="alert error">Error saving configuration.</div>';
            }
        });

        async function testConnection() {
            const status = document.getElementById('configStatus');
            status.innerHTML = '<div class="alert info">Testing connection...</div>';

            const response = await fetch('/api/automator/test');
            const result = await response.json();

            if (result.connected) {
                status.innerHTML = '<div class="alert success">Connection successful!</div>';
            } else {
                status.innerHTML = `<div class="alert error">Connection failed: ${result.error}</div>`;
            }
        }

        async function testMacro(macroId, macroName) {
            if (!confirm(`Test trigger macro: ${macroName}?`)) return;

            const response = await fetch(`/api/automator/trigger/${macroId}`, {method: 'POST'});

            if (response.ok) {
                alert(`Successfully triggered: ${macroName}`);
            } else {
                alert(`Error triggering macro: ${macroName}`);
            }
        }
    </script>
    """

    return _get_base_html("Automator Macros", content, "automator")


@app.get("/command-mapping", response_class=HTMLResponse)
async def command_mapping_page():
    """Command Mapping page."""
    global config_data

    tcp_commands = config_data.get("tcp_commands", [])
    mappings = config_data.get("command_mappings", [])

    # Fetch automator macros
    macros = []
    automator_config = config_data.get("automator", {})
    if automator_config.get("enabled") and automator_config.get("url"):
        macros = fetch_automator_macros()

    if not tcp_commands:
        content = """
        <h1>Command Mapping</h1>
        <div class="alert info">
            No TCP commands configured. Please add TCP commands first on the
            <a href="/tcp-commands" style="color: #00bcd4;">TCP Commands page</a>.
        </div>
        """
        return _get_base_html("Command Mapping", content, "mapping")

    if not macros:
        content = """
        <h1>Command Mapping</h1>
        <div class="alert info">
            No Automator macros available. Please configure Automator integration on the
            <a href="/automator-macros" style="color: #00bcd4;">Automator Macros page</a>.
        </div>
        """
        return _get_base_html("Command Mapping", content, "mapping")

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

        # Build select options
        options_html = '<option value="">-- Not Mapped --</option>'
        for macro in macros:
            macro_id = macro.get("id", "")
            macro_name = macro.get("name", "Unknown")
            selected = "selected" if current_mapping and current_mapping["automator_macro_id"] == macro_id else ""
            options_html += f'<option value="{macro_id}" {selected}>{macro_name}</option>'

        table_rows += f"""
        <tr>
            <td><strong>{tcp_name}</strong><br><span style="color: #888888; font-size: 12px;">{tcp_trigger}</span></td>
            <td>
                <select class="mapping-select" data-tcp-id="{tcp_id}" style="width: 100%;">
                    {options_html}
                </select>
            </td>
            <td style="text-align: center;">
                <button class="success" onclick="saveMapping('{tcp_id}')">Save</button>
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

        <div class="mapping-grid">
            <table class="mapping-table">
                <thead>
                    <tr>
                        <th>TCP Command</th>
                        <th>Automator Macro</th>
                        <th style="text-align: center;">Action</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>

        <button class="primary mt-20" onclick="saveAllMappings()">Save All Mappings</button>
    </div>

    <div id="mappingStatus" class="mt-20"></div>

    <script>
        const macros = {json.dumps(macros)};

        async function saveMapping(tcpId) {{
            const select = document.querySelector(`select[data-tcp-id="${{tcpId}}"]`);
            const macroId = select.value;

            if (!macroId) {{
                // Remove mapping
                await removeMappingForTcpCommand(tcpId);
                return;
            }}

            const macro = macros.find(m => m.id === macroId);
            const macroName = macro ? macro.name : '';

            await updateMapping(tcpId, macroId, macroName);
        }}

        async function saveAllMappings() {{
            const selects = document.querySelectorAll('.mapping-select');
            const newMappings = [];

            for (const select of selects) {{
                const tcpId = select.dataset.tcpId;
                const macroId = select.value;

                if (macroId) {{
                    const macro = macros.find(m => m.id === macroId);
                    newMappings.push({{
                        tcp_command_id: tcpId,
                        automator_macro_id: macroId,
                        automator_macro_name: macro ? macro.name : ''
                    }});
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

        async function updateMapping(tcpId, macroId, macroName) {{
            const currentMappings = {json.dumps(mappings)};

            // Remove existing mapping for this TCP command
            const filteredMappings = currentMappings.filter(m => m.tcp_command_id !== tcpId);

            // Add new mapping
            filteredMappings.push({{
                tcp_command_id: tcpId,
                automator_macro_id: macroId,
                automator_macro_name: macroName
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
    </script>
    """

    return _get_base_html("Command Mapping", content, "mapping")


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
async def api_automator_test():
    """Test Automator connection."""
    return check_automator_connection()


@app.post("/api/automator/trigger/{macro_id}")
async def api_trigger_macro(macro_id: str):
    """Manually trigger an Automator macro."""
    await trigger_automator_macro(macro_id, f"Manual trigger: {macro_id}")
    return {"success": True, "macro_id": macro_id}


@app.post("/api/config")
async def api_update_config(config_update: ConfigUpdate):
    """Update configuration."""
    global config_data

    # Update config
    if config_update.tcp_listeners is not None:
        config_data["tcp_listeners"] = [l.dict() for l in config_update.tcp_listeners]

    if config_update.tcp_commands is not None:
        config_data["tcp_commands"] = [c.dict() for c in config_update.tcp_commands]

    if config_update.automator is not None:
        config_data["automator"] = config_update.automator.dict()

    if config_update.command_mappings is not None:
        config_data["command_mappings"] = [m.dict() for m in config_update.command_mappings]

    if config_update.web_port is not None:
        config_data["web_port"] = config_update.web_port

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=3114)
