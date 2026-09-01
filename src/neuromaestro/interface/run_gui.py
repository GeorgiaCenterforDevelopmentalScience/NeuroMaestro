#!/usr/bin/env python3
"""GCDS Neuro Pipeline GUI Launcher"""

import logging
import os
import argparse
from pathlib import Path

logging.getLogger("werkzeug").setLevel(logging.ERROR)

def main():
    parser = argparse.ArgumentParser(description="Launch GCDS Neuro Pipeline GUI")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8050, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--config-dir", default="./config", help="Configuration directory")
    
    args = parser.parse_args()
    
    # Create config directory
    config_dir = Path(args.config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    os.environ['CONFIG_DIR'] = str(config_dir)
    
    print(f"Starting GCDS Neuro Pipeline GUI...")
    print(f"Access the GUI at: http://{args.host}:{args.port}")
    
    try:
        from neuro_pipeline.interface.app import app
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