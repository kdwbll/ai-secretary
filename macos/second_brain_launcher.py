"""Self-contained macOS application entry point."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def health(url: str) -> dict | None:
    try:
        # Local application traffic must not pass through the user's proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "/api/health", timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return None


def open_page(url: str) -> None:
    if os.environ.get("SECOND_BRAIN_NO_OPEN") != "1":
        subprocess.run(["/usr/bin/open", url], check=True)


def show_error(message: str) -> None:
    # Arguments, rather than interpolated AppleScript, keep paths safely quoted.
    subprocess.run([
        "/usr/bin/osascript", "-e",
        'on run argv\ndisplay dialog (item 1 of argv) with title "SecondBrain" '
        'buttons {"OK"} default button "OK" with icon stop\nend run', message,
    ], check=False)


def main() -> None:
    root = Path(os.environ.get("SECOND_BRAIN_ROOT", str(
        Path.home() / "Library" / "Application Support" / "SecondBrain"
    )))
    root.mkdir(parents=True, exist_ok=True)
    os.environ["SECOND_BRAIN_ROOT"] = str(root)
    log_path = root / "second-brain.log"
    logging.basicConfig(filename=log_path, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        import uvicorn
        from core.secretary.app import APP_VERSION, app

        port = int(os.environ.get("SECOND_BRAIN_PORT", "8765"))
        url = f"http://127.0.0.1:{port}"
        running = health(url)
        if running and running.get("ok"):
            if running.get("version") != APP_VERSION:
                raise RuntimeError("An older SecondBrain service is running. "
                                   "Stop it using Settings > Terminate service, then open this app again.")
            open_page(url)
            return

        server = uvicorn.Server(uvicorn.Config(
            app, host=os.environ.get("SECOND_BRAIN_HOST", "0.0.0.0"), port=port,
            log_config=None, access_log=False,
        ))
        thread = threading.Thread(target=server.run, name="SecondBrainServer", daemon=False)
        thread.start()
        for _ in range(100):
            if server.started and health(url):
                open_page(url)
                thread.join()
                return
            if not thread.is_alive():
                raise RuntimeError("The local service stopped during startup.")
            time.sleep(0.1)
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("The local service did not start within 10 seconds.")
    except Exception as exc:
        logging.exception("SecondBrain failed to start")
        if os.environ.get("SECOND_BRAIN_NO_OPEN") != "1":
            show_error(f"SecondBrain could not start.\n\n{exc}\n\nLog: {log_path}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
