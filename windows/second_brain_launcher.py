"""Frozen Windows entry point for SecondBrain.

The installer owns program files; this launcher keeps every private user file
under %LOCALAPPDATA%\\SecondBrain so updating or uninstalling the app does not
silently delete the user's data.
"""
from __future__ import annotations

import ctypes
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


PORT = int(os.environ.get("SECOND_BRAIN_PORT", "8765"))
HOST = os.environ.get("SECOND_BRAIN_HOST", "0.0.0.0")
LOCAL_URL = f"http://127.0.0.1:{PORT}"


def data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("Windows LOCALAPPDATA directory is unavailable.")
    root = Path(local_app_data) / "SecondBrain"
    root.mkdir(parents=True, exist_ok=True)
    return root


def can_connect() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
            return True
    except OSError:
        return False


def show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, "SecondBrain", 0x10)


def main() -> None:
    if can_connect():
        webbrowser.open(LOCAL_URL)
        return

    root = data_root()
    os.environ["SECOND_BRAIN_ROOT"] = str(root)
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    logging.basicConfig(
        filename=root / "second-brain.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        import uvicorn
        from core.secretary.app import app

        # The packaged launcher is a windowed executable, so Windows does not
        # provide stdout/stderr.  Uvicorn's default logging configuration uses
        # those streams while creating its formatter and crashes before the
        # server starts.  Application errors continue to go to LOG_PATH via
        # the file logging configured above.
        config = uvicorn.Config(
            app,
            host=HOST,
            port=PORT,
            log_config=None,
            access_log=False,
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, name="SecondBrainServer", daemon=False)
        thread.start()
        for _ in range(100):
            if can_connect():
                webbrowser.open(LOCAL_URL)
                thread.join()
                return
            if not thread.is_alive():
                raise RuntimeError("The local service stopped during startup. See second-brain.log.")
            time.sleep(0.1)
        raise RuntimeError("The local service did not start within 10 seconds. See second-brain.log.")
    except Exception as exc:  # Keep a double-click launch diagnosable.
        logging.exception("SecondBrain failed to start")
        show_error(f"SecondBrain could not start.\n\n{exc}\n\nLog: {root / 'second-brain.log'}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
