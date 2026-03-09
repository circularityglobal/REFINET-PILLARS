"""
REFInet Pillar — Android Background Service

Runs the Pillar server as a foreground Android service so it persists
when the app is in the background. Launched by main.py via pyjnius.
"""

import asyncio
import os
import sys


def main():
    """Entry point for the Android service."""
    # Configure data directory
    if hasattr(sys, "getandroidapilevel"):
        from android.storage import app_storage_path
        os.environ["REFINET_HOME"] = os.path.join(app_storage_path(), ".refinet")

    # Import pillar after environment is configured
    from pillar import main as pillar_main

    # Run the async server
    try:
        asyncio.run(pillar_main(
            host="0.0.0.0",
            port=7070,
            gopher_port=0,         # Disable port 70 (needs root on Android)
            enable_mesh=True,
            enable_gopher=False,   # Standard Gopher disabled (port 70 restricted)
        ))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
