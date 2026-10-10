#!/bin/sh
set -eu
exec .venv/bin/python -m uvicorn core.secretary.app:app --host 127.0.0.1 --port 8765
