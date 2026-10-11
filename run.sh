#!/bin/sh
set -eu
exec .venv/bin/python -m uvicorn core.secretary.app:app --host "${SECOND_BRAIN_HOST:-0.0.0.0}" --port "${SECOND_BRAIN_PORT:-8765}"
