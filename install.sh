#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== [1/4] Checking Python & uv ==="
if ! command -v uv &> /dev/null; then
    echo "uv not found, using standard python3 -m venv..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip "mcp<2" httpx pydantic
else
    echo "uv found: $(uv --version)"
    if [ ! -d ".venv" ]; then
        uv venv .venv
    fi
    uv pip install --python .venv/bin/python "mcp<2" httpx pydantic
fi

echo ""
echo "=== [2/4] Testing Qwen & d1 Endpoints ==="
.venv/bin/python -c '
import httpx, json
from config import load_qwen_config, D1_URL

base_url, api_key, model = load_qwen_config()
print(f"Testing Qwen endpoint ({base_url})...")
try:
    resp = httpx.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=5.0)
    print(f"  [Qwen OK] HTTP {resp.status_code}")
except Exception as e:
    print(f"  [Qwen Warning] {e}")

print(f"Testing d1 decision endpoint ({D1_URL})...")
try:
    resp = httpx.post(D1_URL, json={"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}, timeout=5.0)
    print(f"  [d1 OK] HTTP {resp.status_code}")
except Exception as e:
    print(f"  [d1 Warning] {e}")
'

echo ""
echo "=== [3/4] Registering with Gemini MCP Config ==="
.venv/bin/python setup_config.py

echo ""
echo "=== [4/4] Done! ==="
echo "The qwen-delegate server is installed and registered."
echo "Whenever Antigravity / Gemini connects, it will now have:"
echo "  - qwen_implement_task (Qwen Builder via Pi with 0 MCP bloat)"
echo "  - qwen_raw_complete (Instant direct Qwen chat completion)"
echo "  - d1_verify_claim (Zero-generation claim verification)"
echo "  - d1_score_document (Zero-generation rubric scoring)"
