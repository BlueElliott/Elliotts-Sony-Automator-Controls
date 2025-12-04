"""GUI Launcher for Sony Automator Controls using Tkinter."""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import webbrowser
import subprocess
import sys
import time
import logging
from pathlib import Path

import pystray
from PIL import Image, ImageDraw
import uvicorn

from sony_automator_controls import core

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Colors matching Elliott's house style
COLORS = {
    "bg_dark": "#1a1a1a",
    "bg_medium": "#252525",
    "bg_card": "#2d2d2d",
    "accent_cyan": "#00bcd4",
    "accent_cyan_dark": "#0097a7",
    "text_light": "#ffffff",
    "text_gray": "#888888",
    "button_blue": "#2196f3",
    "button_green": "#4caf50",
    "button_red": "#ff5252",
    "button_orange": "#e67e22",
    "button_red_dark": "#c0392b",
    "button_gray": "#3d3d3d",
    "border": "#3d3d3d",
}


class SonyAutomatorGUI:
    """Main GUI application for Sony Automator Controls."""

    def __init__(self):
        """Initialize the GUI application."""
        self.root = tk.Tk()
        self.root.title("Sony Automator Controls")
        self.root.geometry("800x700")
        self.root.resizable(False, False)
        self.root.configure(bg=COLORS["bg_dark"])

        # Server state
        self.server_thread = None
        self.server_running = False
        self.server_port = 3114
        self.console_window = None
        self.tray_icon = None

        # Load configuration
        self.config = core.load_config()
        self.server_port = self.config.get("web_port", 3114)

        # Setup GUI
        self._setup_gui()

        # Start server
        self.start_server()

        # Protocol for window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _setup_gui(self):
        """Setup the GUI components."""
        # Header
        header_frame = tk.Frame(self.root, bg=COLORS["bg_medium"], height=80)
        header_frame.pack(fill=tk.X, padx=0, pady=0)
        header_frame.pack_propagate(False)

        title_label = tk.Label(
            header_frame,
            text="Sony Automator Controls",
            font=("Segoe UI", 24, "bold"),
            bg=COLORS["bg_medium"],
            fg=COLORS["accent_cyan"]
        )
        title_label.pack(pady=15)

        version_label = tk.Label(
            header_frame,
            text=f"v{core.__version__}",
            font=("Segoe UI", 10),
            bg=COLORS["bg_medium"],
            fg=COLORS["text_gray"]
        )
        version_label.pack()

        # Main content area
        content_frame = tk.Frame(self.root, bg=COLORS["bg_dark"])
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Status section
        self._create_status_section(content_frame)

        # Control buttons section
        self._create_buttons_section(content_frame)

        # Info section
        self._create_info_section(content_frame)

    def _create_status_section(self, parent):
        """Create status indicator section."""
        status_frame = tk.Frame(parent, bg=COLORS["bg_card"], relief=tk.FLAT, bd=1)
        status_frame.pack(fill=tk.X, pady=(0, 20))

        # Section title
        title_label = tk.Label(
            status_frame,
            text="Server Status",
            font=("Segoe UI", 14, "bold"),
            bg=COLORS["bg_card"],
            fg=COLORS["text_light"]
        )
        title_label.pack(pady=(15, 10))

        # Status indicator
        indicator_frame = tk.Frame(status_frame, bg=COLORS["bg_card"])
        indicator_frame.pack(pady=10)

        self.status_canvas = tk.Canvas(
            indicator_frame,
            width=20,
            height=20,
            bg=COLORS["bg_card"],
            highlightthickness=0
        )
        self.status_canvas.pack(side=tk.LEFT, padx=(0, 10))

        self.status_label = tk.Label(
            indicator_frame,
            text="Starting...",
            font=("Segoe UI", 12),
            bg=COLORS["bg_card"],
            fg=COLORS["text_light"]
        )
        self.status_label.pack(side=tk.LEFT)

        # Draw initial status dot
        self._draw_status_dot("yellow")

        # Status details
        self.details_label = tk.Label(
            status_frame,
            text=f"Port: {self.server_port}",
            font=("Segoe UI", 10),
            bg=COLORS["bg_card"],
            fg=COLORS["text_gray"]
        )
        self.details_label.pack(pady=(0, 15))

        # Start status update loop
        self._update_status()

    def _draw_status_dot(self, color):
        """Draw status indicator dot."""
        self.status_canvas.delete("all")
        color_map = {
            "green": COLORS["button_green"],
            "red": COLORS["button_red"],
            "yellow": COLORS["button_orange"]
        }
        fill_color = color_map.get(color, COLORS["text_gray"])

        self.status_canvas.create_oval(2, 2, 18, 18, fill=fill_color, outline="")

    def _create_buttons_section(self, parent):
        """Create control buttons section."""
        buttons_frame = tk.Frame(parent, bg=COLORS["bg_dark"])
        buttons_frame.pack(fill=tk.BOTH, expand=True)

        # Open Web GUI button
        web_btn = self._create_button(
            buttons_frame,
            "Open Web Interface",
            COLORS["accent_cyan"],
            COLORS["accent_cyan_dark"],
            self.open_web_gui
        )
        web_btn.pack(fill=tk.X, pady=5)

        # Open Console button
        console_btn = self._create_button(
            buttons_frame,
            "Open Console Log",
            COLORS["button_gray"],
            COLORS["bg_card"],
            self.open_console
        )
        console_btn.pack(fill=tk.X, pady=5)

        # Restart Server button
        restart_btn = self._create_button(
            buttons_frame,
            "Restart Server",
            COLORS["button_orange"],
            COLORS["button_red_dark"],
            self.restart_server
        )
        restart_btn.pack(fill=tk.X, pady=5)

        # Hide to Tray button
        tray_btn = self._create_button(
            buttons_frame,
            "Hide to System Tray",
            COLORS["button_gray"],
            COLORS["bg_card"],
            self.hide_to_tray
        )
        tray_btn.pack(fill=tk.X, pady=5)

        # Separator
        separator = tk.Frame(buttons_frame, bg=COLORS["border"], height=2)
        separator.pack(fill=tk.X, pady=15)

        # Quit button
        quit_btn = self._create_button(
            buttons_frame,
            "Quit Application",
            COLORS["button_red_dark"],
            COLORS["button_red"],
            self.quit_application
        )
        quit_btn.pack(fill=tk.X, pady=5)

    def _create_button(self, parent, text, bg_color, hover_color, command):
        """Create a styled button."""
        btn = tk.Button(
            parent,
            text=text,
            font=("Segoe UI", 11, "bold"),
            bg=bg_color,
            fg=COLORS["text_light"],
            activebackground=hover_color,
            activeforeground=COLORS["text_light"],
            relief=tk.FLAT,
            cursor="hand2",
            command=command,
            padx=20,
            pady=12
        )

        # Bind hover events
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover_color))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg_color))

        return btn

    def _create_info_section(self, parent):
        """Create info section."""
        info_frame = tk.Frame(parent, bg=COLORS["bg_card"], relief=tk.FLAT, bd=1)
        info_frame.pack(fill=tk.X, pady=(20, 0))

        info_label = tk.Label(
            info_frame,
            text="TCP to HTTP Command Bridge for Sony Automator",
            font=("Segoe UI", 10),
            bg=COLORS["bg_card"],
            fg=COLORS["text_gray"]
        )
        info_label.pack(pady=15)

    def start_server(self):
        """Start the FastAPI server."""
        if self.server_running:
            logger.warning("Server already running")
            return

        def run_server():
            try:
                logger.info(f"Starting server on port {self.server_port}")
                uvicorn.run(
                    core.app,
                    host="127.0.0.1",
                    port=self.server_port,
                    log_level="info"
                )
            except Exception as e:
                logger.error(f"Error running server: {e}")

        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        self.server_running = True

        logger.info("Server thread started")

    def restart_server(self):
        """Restart the server."""
        messagebox.showinfo(
            "Restart Required",
            "To restart the server, please quit and restart the application."
        )

    def open_web_gui(self):
        """Open web interface in browser."""
        url = f"http://127.0.0.1:{self.server_port}"
        webbrowser.open(url)
        logger.info(f"Opening web interface: {url}")

    def open_console(self):
        """Open console window showing logs."""
        if self.console_window and tk.Toplevel.winfo_exists(self.console_window):
            self.console_window.lift()
            return

        self.console_window = tk.Toplevel(self.root)
        self.console_window.title("Console Log")
        self.console_window.geometry("800x600")
        self.console_window.configure(bg=COLORS["bg_dark"])

        # Console text area
        console_text = scrolledtext.ScrolledText(
            self.console_window,
            font=("Consolas", 10),
            bg=COLORS["bg_dark"],
            fg=COLORS["text_light"],
            insertbackground=COLORS["text_light"],
            wrap=tk.WORD
        )
        console_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        console_text.insert(tk.END, "Sony Automator Controls - Console Log\n")
        console_text.insert(tk.END, "=" * 60 + "\n\n")
        console_text.insert(tk.END, f"Server running on port {self.server_port}\n")
        console_text.insert(tk.END, f"Web interface: http://127.0.0.1:{self.server_port}\n\n")
        console_text.insert(tk.END, "Logs will appear here...\n")

        console_text.configure(state=tk.DISABLED)

    def hide_to_tray(self):
        """Hide window to system tray."""
        self.root.withdraw()
        self._create_tray_icon()

    def _create_tray_icon(self):
        """Create system tray icon."""
        if self.tray_icon:
            return

        # Create icon image
        icon_image = self._generate_icon_image()

        # Create menu
        menu = pystray.Menu(
            pystray.MenuItem("Open", self._show_window),
            pystray.MenuItem("Open Web Interface", self.open_web_gui),
            pystray.MenuItem("Quit", self.quit_application)
        )

        # Create tray icon
        self.tray_icon = pystray.Icon(
            "sony_automator",
            icon_image,
            "Sony Automator Controls",
            menu
        )

        # Run in separate thread
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _generate_icon_image(self):
        """Generate tray icon image."""
        # Create 64x64 icon
        size = 64
        image = Image.new("RGB", (size, size), COLORS["bg_dark"])
        draw = ImageDraw.Draw(image)

        # Draw circle
        padding = 10
        draw.ellipse(
            [padding, padding, size - padding, size - padding],
            fill=COLORS["accent_cyan"]
        )

        # Draw "S" letter (simplified)
        draw.text(
            (size // 2, size // 2),
            "S",
            fill=COLORS["text_light"],
            anchor="mm"
        )

        return image

    def _show_window(self, icon=None, item=None):
        """Show the main window."""
        self.root.deiconify()
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None

    def _update_status(self):
        """Update status indicator."""
        if self.server_running:
            self._draw_status_dot("green")
            self.status_label.configure(text="Running")

            # Calculate uptime
            uptime_seconds = int(time.time() - core.server_start_time)
            hours = uptime_seconds // 3600
            minutes = (uptime_seconds % 3600) // 60
            uptime_text = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

            self.details_label.configure(
                text=f"Port: {self.server_port} | Uptime: {uptime_text}"
            )
        else:
            self._draw_status_dot("red")
            self.status_label.configure(text="Stopped")
            self.details_label.configure(text=f"Port: {self.server_port}")

        # Schedule next update
        self.root.after(2000, self._update_status)

    def on_closing(self):
        """Handle window close event."""
        if messagebox.askokcancel("Quit", "Do you want to quit Sony Automator Controls?"):
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


def main():
    """Main entry point for GUI launcher."""
    app = SonyAutomatorGUI()
    app.run()


if __name__ == "__main__":
    main()
