#!/usr/bin/env python3
"""NeuroMaestro GUI Launcher"""

import logging
import os
import argparse
import secrets
import socket
from pathlib import Path

logging.getLogger("werkzeug").setLevel(logging.ERROR)

def main():
    parser = argparse.ArgumentParser(description="Launch NeuroMaestro GUI")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host to bind to (use 0.0.0.0 to accept remote connections)")
    parser.add_argument("--port", type=int, default=8050, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--config-dir", default="./config", help="Configuration directory")
    
    args = parser.parse_args()
    
    # Create config directory
    config_dir = Path(args.config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    os.environ['CONFIG_DIR'] = str(config_dir)
    
    # The debug reloader re-runs main() in a child process, which must keep the printed token.
    token = os.environ.setdefault("_NEUROMAESTRO_GUI_TOKEN", secrets.token_urlsafe(32))
    shown_host = socket.gethostname() if args.host == "0.0.0.0" else args.host

    try:
        from neuromaestro.interface.app import app
        from neuromaestro.interface.auth import install_token_auth
        install_token_auth(app.server, token, f"neuromaestro_token_{args.port}")

        print("Starting NeuroMaestro GUI...")
        print(f"Access the GUI at: http://{shown_host}:{args.port}/?token={token}")
        app.run(
            debug=args.debug,
            host=args.host,
            port=args.port,
            use_reloader=args.debug
        )
    except KeyboardInterrupt:
        print("\nShutting down GUI server...")
    except Exception as e:
        print(f"Error starting GUI: {e}")
        import traceback
        traceback.print_exc()
        raise SystemExit(1)

if __name__ == "__main__":
    main()