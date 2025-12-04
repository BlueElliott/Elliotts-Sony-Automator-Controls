"""Main entry point for Sony Automator Controls."""

import sys
import argparse
from sony_automator_controls.gui_launcher import main as gui_main


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Sony Automator Controls")
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run without GUI (server only)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3114,
        help="Web server port (default: 3114)"
    )

    args = parser.parse_args()

    if args.no_gui:
        # Import and run server directly
        from sony_automator_controls import core
        import uvicorn
        uvicorn.run(core.app, host="127.0.0.1", port=args.port)
    else:
        # Launch GUI which will start server
        gui_main()


if __name__ == "__main__":
    main()
