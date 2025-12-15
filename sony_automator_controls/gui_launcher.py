"""GUI Launcher for Sony Automator Controls with system tray support."""

import sys
import time
import threading
import webbrowser
import logging
import tkinter as tk
from tkinter import scrolledtext
from io import StringIO
import socket
import pystray
from PIL import Image, ImageDraw, ImageTk
import uvicorn
from pathlib import Path
import psutil

from sony_automator_controls import core
from sony_automator_controls.core import _runtime_version

# Set Windows app ID for taskbar icon (must be done before tkinter)
try:
    import ctypes
    myappid = 'elliott.sonyautomatorcontrols.sac.1'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except:
    pass  # Not on Windows or ctypes not available

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Get the local network IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def kill_process_on_port(port: int) -> bool:
    """Kill any process using the specified port."""
    killed = False
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.connections():
                if conn.laddr.port == port:
                    logger.info(f"Killing process {proc.info['name']} (PID: {proc.info['pid']}) on port {port}")
                    proc.kill()
                    killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return killed


class SonyAutomatorGUI:
    """Main GUI application for Sony Automator Controls."""

    def __init__(self):
        """Initialize the GUI application."""
        self.root = tk.Tk()
        self.root.title(f"Elliott's Sony Automator Controls - v{_runtime_version()}")
        self.root.geometry("750x650")
        self.root.resizable(False, False)

        # Modern dark theme colors matching Elliott's Singular Control
        self.bg_dark = "#1a1a1a"
        self.bg_medium = "#252525"
        self.bg_card = "#2d2d2d"
        self.accent_teal = "#00bcd4"
        self.accent_teal_dark = "#0097a7"
        self.text_light = "#ffffff"
        self.text_gray = "#888888"
        self.button_blue = "#2196f3"
        self.button_green = "#4caf50"
        self.button_red = "#ff5252"
        self.button_gray = "#3d3d3d"
        self.button_orange = "#e67e22"
        self.button_red_dark = "#c0392b"

        self.root.configure(bg=self.bg_dark)

        # Load fonts
        self._load_fonts()

        # Server state
        self.server_thread = None
        self.server_running = False
        self.console_window = None
        self.console_text = None
        self.console_visible = False
        self.log_handler = None
        self.tray_icon = None

        # Load configuration
        self.config = core.load_config()
        self.server_port = self.config.get("web_port", 3114)

        # Runtime tracking
        self.start_time = time.time()
        self.pulse_angle = 0

        # Pulse rendering
        self.pulse_size = 40
        self.pulse_scale = 4
        self.pulse_image = None

        # Set window icon
        self._set_window_icon()

        # Setup UI
        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _set_window_icon(self):
        """Set the window icon from file or generate it."""
        try:
            # Try to load from static folder
            icon_path = Path(__file__).parent.parent / "static" / "sac_icon.ico"
            if icon_path.exists():
                self.root.iconbitmap(str(icon_path))
            else:
                # Try relative to exe location
                from sony_automator_controls.core import _app_root
                icon_path = _app_root() / "static" / "sac_icon.ico"
                if icon_path.exists():
                    self.root.iconbitmap(str(icon_path))
        except Exception:
            pass  # Icon not critical

    def _load_fonts(self):
        """Load ITV Reem fonts for the GUI."""
        try:
            static_path = Path(__file__).parent.parent / "static"
            regular_path = static_path / "ITV Reem-Regular.ttf"

            if regular_path.exists():
                self.font_regular = ("ITV Reem", 10)
                self.font_regular_11 = ("ITV Reem", 11)
                self.font_regular_24 = ("ITV Reem", 24)
                self.font_bold = ("ITV Reem", 10, "bold")
                self.font_bold_11 = ("ITV Reem", 11, "bold")
                self.font_bold_24 = ("ITV Reem", 24, "bold")
                self.font_bold_32 = ("ITV Reem", 32, "bold")
            else:
                self.font_regular = ("Segoe UI", 10)
                self.font_regular_11 = ("Segoe UI", 11)
                self.font_regular_24 = ("Segoe UI", 24)
                self.font_bold = ("Segoe UI", 10, "bold")
                self.font_bold_11 = ("Segoe UI", 11, "bold")
                self.font_bold_24 = ("Segoe UI", 24, "bold")
                self.font_bold_32 = ("Segoe UI", 32, "bold")
        except Exception:
            self.font_regular = ("Segoe UI", 10)
            self.font_regular_11 = ("Segoe UI", 11)
            self.font_regular_24 = ("Segoe UI", 24)
            self.font_bold = ("Segoe UI", 10, "bold")
            self.font_bold_11 = ("Segoe UI", 11, "bold")
            self.font_bold_24 = ("Segoe UI", 24, "bold")
            self.font_bold_32 = ("Segoe UI", 32, "bold")

    def _draw_rounded_rect(self, canvas, x1, y1, x2, y2, radius, fill):
        """Draw a rounded rectangle on canvas with smooth edges."""
        canvas.create_oval(x1, y1, x1 + radius*2, y1 + radius*2, fill=fill, outline=fill)
        canvas.create_oval(x2 - radius*2, y1, x2, y1 + radius*2, fill=fill, outline=fill)
        canvas.create_oval(x1, y2 - radius*2, x1 + radius*2, y2, fill=fill, outline=fill)
        canvas.create_oval(x2 - radius*2, y2 - radius*2, x2, y2, fill=fill, outline=fill)
        canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=fill)
        canvas.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline=fill)

    def _draw_smooth_rounded_rect(self, canvas, x1, y1, x2, y2, radius, fill):
        """Draw a smooth rounded rectangle using arcs and rectangles."""
        canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=fill)
        canvas.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline=fill)
        canvas.create_oval(x1, y1, x1 + radius*2, y1 + radius*2, fill=fill, outline=fill)
        canvas.create_oval(x2 - radius*2, y1, x2, y1 + radius*2, fill=fill, outline=fill)
        canvas.create_oval(x1, y2 - radius*2, x1 + radius*2, y2, fill=fill, outline=fill)
        canvas.create_oval(x2 - radius*2, y2 - radius*2, x2, y2, fill=fill, outline=fill)

    def create_rounded_button(self, parent, text, command, bg_color, width=180, height=50, state=tk.NORMAL):
        """Create a modern rounded button using canvas with smooth edges."""
        canvas = tk.Canvas(
            parent,
            width=width,
            height=height,
            bg=self.bg_dark,
            highlightthickness=0,
            bd=0
        )

        # Draw rounded rectangle
        radius = 10
        self._draw_smooth_rounded_rect(canvas, 0, 0, width, height, radius, bg_color)

        # Add text
        canvas.create_text(
            width/2, height/2,
            text=text,
            fill=self.text_light if state == tk.NORMAL else self.text_gray,
            font=self.font_bold_11
        )

        # Bind click event
        if state == tk.NORMAL:
            canvas.bind("<Button-1>", lambda e: command())
            canvas.bind("<Enter>", lambda e: canvas.configure(cursor="hand2"))
            canvas.bind("<Leave>", lambda e: canvas.configure(cursor=""))

        canvas.button_state = state
        canvas.bg_color = bg_color
        return canvas

    def setup_ui(self):
        """Setup the main UI with modern dark theme."""
        # Top section with branding
        top_frame = tk.Frame(self.root, bg=self.bg_dark, height=70)
        top_frame.pack(fill=tk.X, padx=40, pady=(30, 0))
        top_frame.pack_propagate(False)

        # Branding text - centered with version
        brand_frame = tk.Frame(top_frame, bg=self.bg_dark)
        brand_frame.pack(expand=True)

        brand_label = tk.Label(
            brand_frame,
            text="Elliott's Sony Automator Controls",
            font=self.font_bold_24,
            bg=self.bg_dark,
            fg=self.text_light
        )
        brand_label.pack()

        version_label = tk.Label(
            brand_frame,
            text=f"Version {_runtime_version()}",
            font=self.font_regular,
            bg=self.bg_dark,
            fg=self.text_gray
        )
        version_label.pack()

        # Main content area
        content_frame = tk.Frame(self.root, bg=self.bg_dark)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=(20, 30))

        # Port card with rounded corners using Canvas
        port_card_canvas = tk.Canvas(
            content_frame,
            width=670,
            height=140,
            bg=self.bg_dark,
            highlightthickness=0
        )
        port_card_canvas.pack(pady=(0, 20))

        # Draw rounded rectangle for card background
        self._draw_rounded_rect(port_card_canvas, 0, 0, 670, 140, 20, self.bg_card)

        # SERVER PORT label
        port_card_canvas.create_text(335, 25, text="SERVER PORT", fill=self.text_gray, font=self.font_bold)

        # Port number with teal background (rounded)
        self._draw_rounded_rect(port_card_canvas, 235, 40, 435, 95, 12, self.accent_teal)
        self.port_text_id = port_card_canvas.create_text(335, 67, text=str(self.server_port), fill=self.text_light, font=self.font_bold_32)

        # Change port button (small, rounded)
        self._draw_rounded_rect(port_card_canvas, 275, 105, 395, 132, 14, self.bg_medium)
        port_card_canvas.create_text(335, 118, text="Change Port", fill=self.text_gray, font=("ITV Reem", 9))

        # Bind click on change port area
        port_card_canvas.tag_bind("change_port", "<Button-1>", lambda e: self.change_port())
        port_card_canvas.addtag_overlapping("change_port", 275, 105, 395, 132)
        port_card_canvas.bind("<Button-1>", self._handle_port_card_click)
        port_card_canvas.bind("<Enter>", lambda e: port_card_canvas.configure(cursor="hand2"))
        port_card_canvas.bind("<Leave>", lambda e: port_card_canvas.configure(cursor=""))

        self.port_card_canvas = port_card_canvas

        # Network IP display
        network_ip = get_local_ip()
        self.network_url = f"http://{network_ip}:{self.server_port}"

        network_label = tk.Label(
            content_frame,
            text=f"Network: {self.network_url}",
            font=("ITV Reem", 10),
            bg=self.bg_dark,
            fg=self.accent_teal,
            cursor="hand2"
        )
        network_label.pack(pady=(0, 10))

        # Status frame with pulse indicator and runtime
        status_frame = tk.Frame(content_frame, bg=self.bg_dark)
        status_frame.pack(pady=(0, 5))

        # Pulse indicator using PIL for anti-aliased smooth graphics
        self.pulse_label = tk.Label(status_frame, bg=self.bg_dark, bd=0, highlightthickness=0)
        self.pulse_label.pack(side=tk.LEFT, padx=(0, 8))

        # Status message
        self.status_label = tk.Label(
            status_frame,
            text="Starting server...",
            font=self.font_regular_11,
            bg=self.bg_dark,
            fg=self.text_gray
        )
        self.status_label.pack(side=tk.LEFT)

        # Runtime label
        self.runtime_label = tk.Label(
            status_frame,
            text="",
            font=self.font_regular,
            bg=self.bg_dark,
            fg=self.text_gray
        )
        self.runtime_label.pack(side=tk.LEFT, padx=(15, 0))

        # Action buttons (2 per row, full-width quit)
        btn_container = tk.Frame(content_frame, bg=self.bg_dark)
        btn_container.pack(pady=(20, 0))

        # Row 1
        row1 = tk.Frame(btn_container, bg=self.bg_dark)
        row1.pack(pady=6)

        self.launch_btn = self.create_rounded_button(
            row1, "Open Web GUI", self.launch_browser,
            self.button_blue, width=290, height=50
        )
        self.launch_btn.pack(side=tk.LEFT, padx=6)

        self.console_toggle_btn = self.create_rounded_button(
            row1, "Open Console", self.toggle_console,
            self.button_gray, width=290, height=50
        )
        self.console_toggle_btn.pack(side=tk.LEFT, padx=6)

        # Row 2
        row2 = tk.Frame(btn_container, bg=self.bg_dark)
        row2.pack(pady=6)

        self.restart_btn = self.create_rounded_button(
            row2, "Restart Server", self.restart_application,
            self.button_orange, width=290, height=50
        )
        self.restart_btn.pack(side=tk.LEFT, padx=6)

        self.hide_btn = self.create_rounded_button(
            row2, "Hide to Tray", self.minimize_to_tray,
            self.button_gray, width=290, height=50
        )
        self.hide_btn.pack(side=tk.LEFT, padx=6)

        # Row 3 (Update and Quit)
        row3 = tk.Frame(btn_container, bg=self.bg_dark)
        row3.pack(pady=6)

        self.update_btn = self.create_rounded_button(
            row3, "Check for Updates", self.check_for_updates,
            self.accent_teal, width=290, height=50
        )
        self.update_btn.pack(side=tk.LEFT, padx=6)

        self.quit_btn = self.create_rounded_button(
            row3, "Quit Server", self.on_closing,
            self.button_red_dark, width=290, height=50
        )
        self.quit_btn.pack(side=tk.LEFT, padx=6)

        # Start pulse animation and runtime update
        self._update_pulse()
        self._update_runtime()

        # Auto-start server on launch
        self.root.after(500, self.start_server)

    def _update_pulse(self):
        """Update the pulse indicator animation with smooth anti-aliased PIL rendering."""
        import math

        size = self.pulse_size
        scale = self.pulse_scale
        big_size = size * scale

        # Background color must match exactly: #1a1a1a = rgb(26, 26, 26)
        bg_color = (26, 26, 26)

        # Blue color for active state
        blue_r, blue_g, blue_b = 80, 180, 255

        if self.server_running:
            # Animate - ripple flows outward from center
            self.pulse_angle = (self.pulse_angle + 8) % 360

            center_phase = self.pulse_angle
            inner_phase = self.pulse_angle - 90
            outer_phase = self.pulse_angle - 180

            # Calculate opacity (0 to 1) for each element
            center_opacity = (math.sin(math.radians(center_phase)) + 1) / 2
            inner_opacity = (math.sin(math.radians(inner_phase)) + 1) / 2
            outer_opacity = (math.sin(math.radians(outer_phase)) + 1) / 2

            # Blend colors with background based on opacity
            def blend(opacity):
                return (
                    int(bg_color[0] + (blue_r - bg_color[0]) * opacity),
                    int(bg_color[1] + (blue_g - bg_color[1]) * opacity),
                    int(bg_color[2] + (blue_b - bg_color[2]) * opacity)
                )

            center_color = blend(center_opacity)
            inner_color = blend(inner_opacity)
            outer_color = blend(outer_opacity)
        else:
            # Server not running - gray static
            gray = (100, 100, 100)
            center_color = gray
            inner_color = gray
            outer_color = gray

        # Create image at high resolution
        img = Image.new('RGB', (big_size, big_size), bg_color)
        draw = ImageDraw.Draw(img)

        cx, cy = big_size // 2, big_size // 2

        # Draw outer ring (scaled up)
        outer_radius = 18 * scale
        ring_width = 3 * scale
        draw.ellipse(
            [cx - outer_radius, cy - outer_radius, cx + outer_radius, cy + outer_radius],
            outline=outer_color, width=ring_width
        )

        # Draw inner ring
        inner_radius = 11 * scale
        draw.ellipse(
            [cx - inner_radius, cy - inner_radius, cx + inner_radius, cy + inner_radius],
            outline=inner_color, width=ring_width
        )

        # Draw center dot (filled)
        center_radius = 5 * scale
        draw.ellipse(
            [cx - center_radius, cy - center_radius, cx + center_radius, cy + center_radius],
            fill=center_color
        )

        # Resize down with anti-aliasing
        img = img.resize((size, size), Image.LANCZOS)

        # Convert to PhotoImage and display
        self.pulse_image = ImageTk.PhotoImage(img)
        self.pulse_label.configure(image=self.pulse_image)

        self.root.after(40, self._update_pulse)

    def _update_runtime(self):
        """Update the runtime display."""
        if self.server_running:
            elapsed = int(time.time() - self.start_time)
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                runtime_str = f"Runtime: {hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                runtime_str = f"Runtime: {minutes}m {seconds}s"
            else:
                runtime_str = f"Runtime: {seconds}s"
            self.runtime_label.config(text=runtime_str)
        self.root.after(1000, self._update_runtime)

    def _handle_port_card_click(self, event):
        """Handle clicks on the port card canvas."""
        # Check if click is in the "Change Port" button area
        if 275 <= event.x <= 395 and 105 <= event.y <= 132:
            self.change_port()

    def change_port(self):
        """Open dialog to change port."""
        from tkinter import simpledialog
        new_port = simpledialog.askinteger(
            "Change Port",
            "Enter new port number:",
            initialvalue=self.server_port,
            minvalue=1024,
            maxvalue=65535
        )
        if new_port and new_port != self.server_port:
            # Update config
            self.config["web_port"] = new_port
            core.save_config(self.config)

            # Update UI
            self.port_card_canvas.itemconfig(self.port_text_id, text=str(new_port))
            self.server_port = new_port
            logger.info(f"Port changed to {new_port}. Please restart the application for changes to take effect.")

    def start_server(self):
        """Start the FastAPI server."""
        if self.server_running:
            logger.warning("Server already running")
            return

        # Automatically kill any existing instance on the port
        if is_port_in_use(self.server_port):
            logger.info(f"Port {self.server_port} in use, closing existing instance...")
            kill_process_on_port(self.server_port)
            # Wait a moment for the port to be released
            time.sleep(0.5)

        def run_server():
            try:
                logger.info(f"Starting server on port {self.server_port}")

                # Custom log config to suppress /health endpoint
                import logging

                class HealthCheckFilter(logging.Filter):
                    def filter(self, record):
                        # Filter out /health endpoint requests
                        return '/health' not in record.getMessage()

                # Apply filter to uvicorn access logger
                logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())

                config = uvicorn.Config(
                    core.app,
                    host="0.0.0.0",
                    port=self.server_port,
                    log_level="info",
                    access_log=True,
                    log_config=None
                )
                server = uvicorn.Server(config)
                server.run()
            except Exception as e:
                logger.error(f"Error running server: {e}")

        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        self.server_running = True
        self.status_label.config(text="Server running")

        logger.info("Server thread started")

    def launch_browser(self):
        """Open web interface in browser."""
        url = f"http://127.0.0.1:{self.server_port}"
        webbrowser.open(url)
        logger.info(f"Opening web interface: {url}")

    def toggle_console(self):
        """Toggle console window visibility."""
        try:
            window_exists = self.console_window is not None and self.console_window.winfo_exists()
        except:
            window_exists = False

        if not window_exists:
            # Create console window
            self.console_window = tk.Toplevel(self.root)
            self.console_window.title("Console Output")
            self.console_window.geometry("800x400")
            self.console_window.configure(bg=self.bg_dark)

            # Handle window close via X button
            self.console_window.protocol("WM_DELETE_WINDOW", self._on_console_close)

            # Console output
            self.console_text = scrolledtext.ScrolledText(
                self.console_window,
                bg="#1e1e1e",
                fg="#d4d4d4",
                font=("Consolas", 9),
                relief=tk.FLAT,
                wrap=tk.WORD
            )
            self.console_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            # Add initial status message
            local_ip = get_local_ip()
            self.console_text.insert(tk.END, f"Elliott's Sony Automator Controls v{_runtime_version()}\n")
            self.console_text.insert(tk.END, "=" * 60 + "\n")
            if self.server_running:
                self.console_text.insert(tk.END, f"✓ Server running on http://0.0.0.0:{self.server_port}\n")
                self.console_text.insert(tk.END, f"  Network: http://{local_ip}:{self.server_port}\n")
            else:
                self.console_text.insert(tk.END, "⚠ Server not running\n")
            self.console_text.insert(tk.END, "=" * 60 + "\n\n")
            self.console_text.insert(tk.END, "Console output will appear here...\n\n")

            # Redirect stdout to console
            sys.stdout = ConsoleRedirector(self.console_text)
            sys.stderr = ConsoleRedirector(self.console_text)

            # Set up logging handler for the root logger
            self.log_handler = TkinterLogHandler(self.console_text)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
            self.log_handler.setFormatter(formatter)
            logging.getLogger().addHandler(self.log_handler)
            logging.getLogger().setLevel(logging.INFO)

            # Write a test message
            print(f"[Console] Console window opened at {time.strftime('%H:%M:%S')}")

            self._update_console_button(True)
            self.console_visible = True
        else:
            self._close_console()

    def _on_console_close(self):
        """Handle console window being closed via X button."""
        self._close_console()

    def _close_console(self):
        """Close the console window and clean up."""
        # First, mark text widget as None to stop logging
        if hasattr(self, 'log_handler') and self.log_handler:
            self.log_handler.text_widget = None
            logging.getLogger().removeHandler(self.log_handler)
            self.log_handler = None

        # Restore stdout/stderr
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

        # Destroy window
        if self.console_window:
            try:
                self.console_window.destroy()
            except:
                pass

        self.console_window = None
        self.console_text = None
        self._update_console_button(False)
        self.console_visible = False

    def _update_console_button(self, is_open):
        """Update the console button text based on state."""
        if hasattr(self, 'console_toggle_btn') and self.console_toggle_btn:
            try:
                # Find the text item in the canvas and update it
                text_items = self.console_toggle_btn.find_all()
                for item in text_items:
                    if self.console_toggle_btn.type(item) == "text":
                        new_text = "Close Console" if is_open else "Open Console"
                        self.console_toggle_btn.itemconfig(item, text=new_text)
                        break
            except:
                pass

    def restart_application(self):
        """Perform a soft restart of the application."""
        # Show restart notification
        self.status_label.config(text="Restarting...", fg=self.button_orange)
        self.root.update()

        # Close console if open
        if self.console_visible:
            self._close_console()

        # Reload configuration
        try:
            # Reload config from file
            new_config = core.load_config()
            self.config.update(new_config)
            core.config_data.update(new_config)
            print("[Restart] Configuration reloaded")
        except Exception as e:
            print(f"[Restart] Config reload error: {e}")

        # Clear event log
        core.COMMAND_LOG.clear()
        print("[Restart] Event log cleared")

        # Reset runtime counter
        self.start_time = time.time()
        self.runtime_label.config(text="Runtime: 0s")

        # Update status
        self.status_label.config(text="Server running", fg=self.accent_teal)

        # Show completion message in console only (no popup)
        print(f"[Restart] Soft restart completed at {time.strftime('%H:%M:%S')}")
        print("[Restart] • Configuration reloaded")
        print("[Restart] • Event log cleared")
        print("[Restart] • Runtime counter reset")

    def minimize_to_tray(self):
        """Hide window to system tray."""
        self.root.withdraw()
        self._create_tray_icon()

    def _create_tray_icon(self):
        """Create system tray icon."""
        if self.tray_icon:
            return

        # Create icon image matching Elliott's style
        icon_image = self._generate_icon_image()

        # Create menu
        menu = pystray.Menu(
            pystray.MenuItem("Open", self._show_window),
            pystray.MenuItem("Open Web Interface", self.launch_browser),
            pystray.MenuItem("Quit", self.on_closing)
        )

        # Create tray icon
        self.tray_icon = pystray.Icon(
            "sony_automator",
            icon_image,
            "Elliott's Sony Automator Controls",
            menu
        )

        # Run in separate thread
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _generate_icon_image(self):
        """Generate tray icon image matching Elliott's style."""
        size = 64
        image = Image.new('RGBA', (size, size), (26, 26, 26, 255))
        dc = ImageDraw.Draw(image)

        cx, cy = size // 2, size // 2
        color = (0, 188, 212, 255)  # #00bcd4
        line_width = max(2, size // 32)

        # Draw concentric circles
        for radius_factor in [0.35, 0.24, 0.13]:
            r = int(size * radius_factor)
            dc.ellipse([cx-r, cy-r, cx+r, cy+r], outline=color, width=line_width)

        # Draw lines to S, A, C letters positions
        outer_r = int(size * 0.35)

        # Line to S (top)
        dc.line([(cx, cy - outer_r), (cx, 2)], fill=color, width=line_width)

        # Line to A (bottom-left)
        dc.line([(cx - 4, cy + outer_r - 2), (8, size - 4)], fill=color, width=line_width)

        # Line to C (right)
        dc.line([(cx + outer_r, cy), (size - 2, cy)], fill=color, width=line_width)

        # Draw small checkmark in center
        check_size = int(size * 0.08)
        dc.line([(cx - check_size, cy), (cx - 2, cy + check_size//2)], fill=color, width=line_width)
        dc.line([(cx - 2, cy + check_size//2), (cx + check_size, cy - check_size//2)], fill=color, width=line_width)

        return image

    def _show_window(self, icon=None, item=None):
        """Show the main window."""
        self.root.deiconify()
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None

    def check_for_updates(self):
        """Check for updates and prompt to install if available."""
        from sony_automator_controls import updater

        # Disable button and show checking status
        self.update_btn.button_state = tk.DISABLED
        self._update_button_text(self.update_btn, "Checking...")

        def do_check():
            try:
                update_info = updater.check_for_updates()

                if update_info:
                    # Update available
                    version = update_info['version']
                    self.root.after(0, lambda: self._show_update_available(update_info))
                else:
                    # No update available
                    self.root.after(0, lambda: self._show_no_update())
            except Exception as e:
                logger.error(f"Error checking for updates: {e}")
                self.root.after(0, lambda: self._show_update_error(str(e)))

        # Run check in background thread
        import threading
        threading.Thread(target=do_check, daemon=True).start()

    def _update_button_text(self, button_canvas, new_text):
        """Update the text on a button canvas."""
        button_canvas.delete("all")
        width = button_canvas.winfo_width() or 290
        height = button_canvas.winfo_height() or 50
        radius = 10
        self._draw_smooth_rounded_rect(button_canvas, 0, 0, width, height, radius, button_canvas.bg_color)
        button_canvas.create_text(
            width/2, height/2,
            text=new_text,
            fill=self.text_light if button_canvas.button_state == tk.NORMAL else self.text_gray,
            font=self.font_bold_11
        )

    def _show_update_available(self, update_info):
        """Show that an update is available and offer to install."""
        version = update_info['version']
        logger.info(f"Update available: v{version}")

        # Update button to show install option
        self.update_btn.button_state = tk.NORMAL
        self._update_button_text(self.update_btn, f"Install v{version}")

        # Rebind to install instead of check
        self.update_btn.unbind("<Button-1>")
        self.update_btn.bind("<Button-1>", lambda e: self._install_update(update_info))

        self.status_label.config(text=f"Update available: v{version}")

    def _show_no_update(self):
        """Show that no update is available."""
        logger.info("No updates available")
        self.update_btn.button_state = tk.NORMAL
        self._update_button_text(self.update_btn, "Up to date ✓")

        # Reset after 3 seconds
        self.root.after(3000, lambda: self._reset_update_button())

    def _show_update_error(self, error):
        """Show update check error."""
        logger.error(f"Update check failed: {error}")
        self.update_btn.button_state = tk.NORMAL
        self._update_button_text(self.update_btn, "Check Failed")

        # Reset after 3 seconds
        self.root.after(3000, lambda: self._reset_update_button())

    def _reset_update_button(self):
        """Reset update button to original state."""
        self.update_btn.button_state = tk.NORMAL
        self._update_button_text(self.update_btn, "Check for Updates")
        self.update_btn.unbind("<Button-1>")
        self.update_btn.bind("<Button-1>", lambda e: self.check_for_updates())

    def _install_update(self, update_info):
        """Download and install the update."""
        from sony_automator_controls import updater

        # Disable button and show downloading status
        self.update_btn.button_state = tk.DISABLED
        self._update_button_text(self.update_btn, "Downloading...")
        self.status_label.config(text="Downloading update...")

        def do_download():
            try:
                download_url = update_info['download_url']
                asset_name = update_info['asset_name']

                # Download
                new_exe = updater.download_update(download_url, asset_name)

                if new_exe:
                    self.root.after(0, lambda: self._finish_update(new_exe))
                else:
                    self.root.after(0, lambda: self._show_download_error())
            except Exception as e:
                logger.error(f"Error downloading update: {e}")
                self.root.after(0, lambda: self._show_download_error())

        # Run download in background thread
        import threading
        threading.Thread(target=do_download, daemon=True).start()

    def _finish_update(self, new_exe_path):
        """Finish the update by installing and restarting."""
        from sony_automator_controls import updater

        self.status_label.config(text="Installing update...")
        logger.info("Update downloaded, installing...")

        # Install update (this will restart the app)
        if updater.install_update(new_exe_path):
            logger.info("Update installed, restarting...")
            self.quit_application()
        else:
            self._show_install_error()

    def _show_download_error(self):
        """Show download error."""
        self.update_btn.button_state = tk.NORMAL
        self._update_button_text(self.update_btn, "Download Failed")
        self.status_label.config(text="Download failed")
        self.root.after(3000, lambda: self._reset_update_button())

    def _show_install_error(self):
        """Show install error."""
        self.update_btn.button_state = tk.NORMAL
        self._update_button_text(self.update_btn, "Install Failed")
        self.status_label.config(text="Install failed")
        self.root.after(3000, lambda: self._reset_update_button())

    def on_closing(self):
        """Handle window close event."""
        self.quit_application()

    def quit_application(self, icon=None, item=None):
        """Quit the application."""
        logger.info("Shutting down...")

        if self.tray_icon:
            self.tray_icon.stop()

        self.server_running = False
        self.root.quit()
        self.root.destroy()

    def run(self):
        """Run the GUI application."""
        self.root.mainloop()


class ConsoleRedirector:
    """Redirect stdout/stderr to a Text widget."""

    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.buffer = StringIO()

    def write(self, message):
        try:
            self.text_widget.insert(tk.END, message)
            self.text_widget.see(tk.END)
        except:
            pass  # Widget may be destroyed
        self.buffer.write(message)

    def flush(self):
        pass


class TkinterLogHandler(logging.Handler):
    """Custom logging handler that writes to a Tkinter Text widget."""

    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        # Check if widget still exists and is valid
        if self.text_widget is None:
            return
        try:
            # Additional check to ensure widget wasn't destroyed
            if not self.text_widget.winfo_exists():
                return
            msg = self.format(record) + '\n'
            self.text_widget.insert(tk.END, msg)
            self.text_widget.see(tk.END)
        except (AttributeError, tk.TclError):
            # Widget was destroyed or became invalid
            self.text_widget = None


def main():
    """Main entry point for GUI launcher."""
    app = SonyAutomatorGUI()
    app.run()


if __name__ == "__main__":
    main()
