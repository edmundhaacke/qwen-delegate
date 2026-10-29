#!/usr/bin/env python3
import json
import os
import shutil
from pathlib import Path

CONFIG_PATH = Path.home() / ".gemini" / "config" / "mcp_config.json"
REPO_DIR = Path(__file__).resolve().parent
PYTHON_BIN = REPO_DIR / ".venv" / "bin" / "python"
SERVER_SCRIPT = REPO_DIR / "server.py"
D1_URL = "http://100.126.106.26:8004/mcp"


def main():
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        config_data = {"mcpServers": {}}
    else:
        # Backup existing config
        backup_path = CONFIG_PATH.with_suffix(".json.bak")
        shutil.copyfile(CONFIG_PATH, backup_path)
        print(f"Backed up existing config to {backup_path}")
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            try:
                config_data = json.load(f)
            except Exception:
                config_data = {"mcpServers": {}}

    servers = config_data.setdefault("mcpServers", {})

    # Register local qwen-delegate stdio server
    servers["qwen-delegate"] = {
        "command": str(PYTHON_BIN),
        "args": [str(SERVER_SCRIPT)],
    }
    print(f"Configured 'qwen-delegate' -> {PYTHON_BIN} {SERVER_SCRIPT}")

    # Register remote d1-decision streamable HTTP server
    servers["d1-decision"] = {
        "url": D1_URL,
    }
    print(f"Configured 'd1-decision' -> {D1_URL}")

    # Write back
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

    print(f"\nSuccessfully updated {CONFIG_PATH}")
    print("\nRegistered servers:")
    for name, srv in servers.items():
        desc = srv.get("url") or f"{srv.get('command')} {' '.join(srv.get('args', []))}"
        print(f"  • {name}: {desc}")


if __name__ == "__main__":
    main()
