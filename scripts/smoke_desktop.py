"""Check the frozen app against empty user data, without opening a browser."""
from __future__ import annotations

import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def main() -> None:
    executable = Path(sys.argv[1]).resolve()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="secondbrain-smoke-") as temporary:
        root = Path(temporary) / "user-data-unicode-测试"
        env = dict(os.environ, SECOND_BRAIN_ROOT=str(root), SECOND_BRAIN_PORT=str(port),
                   SECOND_BRAIN_HOST="127.0.0.1", SECOND_BRAIN_NO_OPEN="1")
        process = subprocess.Popen([str(executable)], env=env)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(f"App exited with status {process.returncode}")
                try:
                    with opener.open(url + "/api/health", timeout=1) as response:
                        health = json.load(response)
                    break
                except OSError:
                    time.sleep(0.2)
            else:
                raise RuntimeError("App startup timed out")
            assert health["ok"] and health["version"] == "0.8.1", health
            with opener.open(url, timeout=5) as response:
                assert "第二大脑" in response.read().decode("utf-8")
            for path in ("/assets/app.js", "/api/providers"):
                with opener.open(url + path, timeout=5) as response:
                    assert response.status == 200 and response.read(), path
            assert (root / "data/second-brain.db").is_file()
            print("Frozen app: startup, version, Web assets, authentication and Unicode data path OK")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
