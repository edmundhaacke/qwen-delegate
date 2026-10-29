#!/usr/bin/env bash
# Standalone CLI runner with auto-workspace resolution and native background callback support
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/.venv/bin/python" "$DIR/cli.py" "$@"
