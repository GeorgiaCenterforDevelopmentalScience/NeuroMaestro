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
    parser.add_argument("--config-dir", default=None,
                        help="Configuration directory. Defaults to $NEUROMAESTRO_CONFIG_DIR.")

    args = parser.parse_args()

    # Prefills the GUI's config directory field. Left unset, the user enters one in the GUI.
    config_dir = args.config_dir or os.environ.get("NEUROMAESTRO_CONFIG_DIR")
    if config_dir:
        os.environ['CONFIG_DIR'] = str(Path(config_dir))
    else:
        os.environ.pop('CONFIG_DIR', None)
    
    # The debug reloader re-runs main() in a child process, which must keep the printed token.
    token = os.environ.setdefault("_NEUROMAESTRO_GUI_TOKEN", secrets.token_urlsafe(32))
    shown_host = socket.gethostname() if args.host == "0.0.0.0" else args.host

    try:
        from neuromaestro.interface.app import app
        from neuromaestro.interface.auth import install_token_auth
        install_token_auth(app.server, token, f"neuromaestro_token_{args.port}")
        # Dash would also print the bare address, which the token check rejects.
        app.logger.setLevel(logging.WARNING)

        print("Starting NeuroMaestro GUI...")
        print(f"Access the GUI at: http://{shown_host}:{args.port}/?token={token}")
        app.run(
            debug=args.debug,
            host=args.host,
            port=args.port,
            use_reloader=args.debug,
            # The Werkzeug console sits outside Flask, so the token check would not cover it.
            use_debugger=False,
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