"""TCP Test Client - Send test commands to Sony Automator Controls."""

import socket
import tkinter as tk
from tkinter import messagebox, scrolledtext
import threading
import time

class TCPTestClient:
    """Simple GUI application to send TCP commands for testing."""

    def __init__(self):
        """Initialize the test client GUI."""
        self.root = tk.Tk()
        self.root.title("TCP Test Client - Sony Automator Controls Tester")
        self.root.geometry("600x700")
        self.root.resizable(False, False)

        # Styling
        self.bg_dark = "#1a1a1a"
        self.bg_card = "#2d2d2d"
        self.accent_teal = "#00bcd4"
        self.text_light = "#ffffff"

        self.root.configure(bg=self.bg_dark)

        # Default settings
        self.host = "localhost"
        self.port = 9001

        self.create_widgets()

    def create_widgets(self):
        """Create all GUI widgets."""

        # Header
        header = tk.Label(
            self.root,
            text="TCP Test Client",
            font=("Segoe UI", 20, "bold"),
            bg=self.bg_dark,
            fg=self.accent_teal
        )
        header.pack(pady=20)

        # Connection settings frame
        settings_frame = tk.Frame(self.root, bg=self.bg_card)
        settings_frame.pack(padx=20, pady=10, fill=tk.X)

        tk.Label(
            settings_frame,
            text="Target Settings",
            font=("Segoe UI", 12, "bold"),
            bg=self.bg_card,
            fg=self.text_light
        ).grid(row=0, column=0, columnspan=3, pady=10, sticky=tk.W, padx=10)

        tk.Label(
            settings_frame,
            text="Host:",
            bg=self.bg_card,
            fg=self.text_light
        ).grid(row=1, column=0, padx=10, pady=5, sticky=tk.W)

        self.host_entry = tk.Entry(settings_frame, width=20)
        self.host_entry.insert(0, self.host)
        self.host_entry.grid(row=1, column=1, padx=5, pady=5)

        tk.Label(
            settings_frame,
            text="Port:",
            bg=self.bg_card,
            fg=self.text_light
        ).grid(row=1, column=2, padx=10, pady=5, sticky=tk.W)

        self.port_entry = tk.Entry(settings_frame, width=10)
        self.port_entry.insert(0, str(self.port))
        self.port_entry.grid(row=1, column=3, padx=5, pady=5)

        # Predefined commands frame
        commands_frame = tk.Frame(self.root, bg=self.bg_card)
        commands_frame.pack(padx=20, pady=10, fill=tk.BOTH, expand=True)

        tk.Label(
            commands_frame,
            text="Quick Test Commands",
            font=("Segoe UI", 12, "bold"),
            bg=self.bg_card,
            fg=self.text_light
        ).pack(pady=10)

        # Button grid for test commands
        button_frame = tk.Frame(commands_frame, bg=self.bg_card)
        button_frame.pack(pady=10)

        # Define test commands
        test_commands = [
            ("TEST1", "#4caf50"),
            ("TEST2", "#2196f3"),
            ("TEST3", "#ff9800"),
            ("CAMERA_ON", "#9c27b0"),
            ("CAMERA_OFF", "#f44336"),
            ("LIGHT_ON", "#ffeb3b"),
            ("LIGHT_OFF", "#607d8b"),
            ("RECORD_START", "#e91e63"),
            ("RECORD_STOP", "#795548"),
            ("POWER_ON", "#00bcd4"),
            ("POWER_OFF", "#ff5722"),
            ("RESET", "#009688"),
        ]

        # Create buttons in a grid
        row = 0
        col = 0
        for cmd, color in test_commands:
            btn = tk.Button(
                button_frame,
                text=cmd,
                width=15,
                height=2,
                bg=color,
                fg="white",
                font=("Segoe UI", 10, "bold"),
                cursor="hand2",
                command=lambda c=cmd: self.send_command(c)
            )
            btn.grid(row=row, column=col, padx=5, pady=5)
            col += 1
            if col > 2:
                col = 0
                row += 1

        # Custom command frame
        custom_frame = tk.Frame(self.root, bg=self.bg_card)
        custom_frame.pack(padx=20, pady=10, fill=tk.X)

        tk.Label(
            custom_frame,
            text="Custom Command:",
            bg=self.bg_card,
            fg=self.text_light,
            font=("Segoe UI", 10)
        ).pack(side=tk.LEFT, padx=10)

        self.custom_entry = tk.Entry(custom_frame, width=30, font=("Segoe UI", 10))
        self.custom_entry.pack(side=tk.LEFT, padx=5)
        self.custom_entry.bind('<Return>', lambda e: self.send_custom_command())

        tk.Button(
            custom_frame,
            text="Send",
            bg=self.accent_teal,
            fg="white",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            command=self.send_custom_command
        ).pack(side=tk.LEFT, padx=5)

        # Log frame
        log_frame = tk.Frame(self.root, bg=self.bg_card)
        log_frame.pack(padx=20, pady=10, fill=tk.BOTH, expand=True)

        tk.Label(
            log_frame,
            text="Activity Log",
            font=("Segoe UI", 10, "bold"),
            bg=self.bg_card,
            fg=self.text_light
        ).pack(pady=5)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=10,
            bg="#000000",
            fg=self.accent_teal,
            font=("Consolas", 9),
            wrap=tk.WORD
        )
        self.log_text.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        # Clear log button
        tk.Button(
            log_frame,
            text="Clear Log",
            bg="#607d8b",
            fg="white",
            font=("Segoe UI", 9),
            cursor="hand2",
            command=self.clear_log
        ).pack(pady=5)

        self.log(f"TCP Test Client started")
        self.log(f"Target: {self.host}:{self.port}")
        self.log("-" * 60)

    def log(self, message):
        """Add message to log."""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def clear_log(self):
        """Clear the log."""
        self.log_text.delete(1.0, tk.END)
        self.log("Log cleared")

    def send_command(self, command):
        """Send a TCP command in a separate thread."""
        threading.Thread(target=self._send_tcp, args=(command,), daemon=True).start()

    def send_custom_command(self):
        """Send custom command from entry field."""
        command = self.custom_entry.get().strip()
        if command:
            self.send_command(command)
            self.custom_entry.delete(0, tk.END)

    def _send_tcp(self, command):
        """Actually send the TCP command."""
        # Get current host and port
        host = self.host_entry.get().strip()
        try:
            port = int(self.port_entry.get().strip())
        except ValueError:
            self.log(f"ERROR: Invalid port number")
            return

        self.log(f"Sending '{command}' to {host}:{port}...")

        try:
            # Create socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)

            # Connect
            sock.connect((host, port))
            self.log(f"✓ Connected to {host}:{port}")

            # Send command (with newline as Sony Automator uses readline)
            sock.sendall((command + "\n").encode())
            self.log(f"✓ Sent: '{command}'")

            # Close connection
            sock.close()
            self.log(f"✓ Connection closed")
            self.log("-" * 60)

        except socket.timeout:
            self.log(f"✗ ERROR: Connection timeout")
        except ConnectionRefusedError:
            self.log(f"✗ ERROR: Connection refused - Is the server running?")
        except Exception as e:
            self.log(f"✗ ERROR: {str(e)}")

    def run(self):
        """Run the GUI application."""
        self.root.mainloop()


if __name__ == "__main__":
    app = TCPTestClient()
    app.run()
