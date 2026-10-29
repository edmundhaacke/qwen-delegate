#!/usr/bin/env python3
"""Standalone CLI runner for Qwen delegation.

Designed to be executed directly via Antigravity's `run_command` with
WaitMsBeforeAsync=500. This triggers Antigravity's native background task
reactive wakeup (callback) upon completion, requiring zero polling and zero
tokens while waiting.
"""

import os
import subprocess
import sys
from pathlib import Path

# Add repo dir to sys.path
REPO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_DIR))

from config import PI_BIN
from server import resolve_workspace


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 cli.py \"<task description>\" [file1 file2 ...]")
        sys.exit(1)

    task = sys.argv[1]
    raw_files = sys.argv[2:] if len(sys.argv) > 2 else []

    # Clean file arguments (remove leading @ if passed)
    clean_files = [f[1:] if f.startswith("@") else f for f in raw_files]

    cwd, target_files = resolve_workspace(clean_files if clean_files else None, None)

    cmd = [
        PI_BIN,
        "--no-mcp",                     # 0 MCP schema bloat (~25k tokens saved)
        "--tools", "read,edit,write,bash",
        "--no-session",
        "-p",
    ]

    for f_path in target_files:
        cmd.append(f"@{f_path}")

    cmd.append(task)

    print(f"=== Qwen Builder Dispatch ===")
    print(f"• Working Directory: {cwd}")
    if target_files:
        print(f"• Target Files: {', '.join(target_files)}")
    print(f"• Execution Mode: Antigravity Background Reactive Callback")
    print(f"• Status: Actively generating via remote Qwen (20-30 tok/s)...\n")
    sys.stdout.flush()

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        if proc.stdout:
            print("--- Output from Qwen ---")
            print(proc.stdout.strip())
        if proc.stderr:
            print("\n--- Diagnostic Stderr ---")
            print(proc.stderr.strip())
        sys.exit(proc.returncode)
    except Exception as e:
        print(f"Execution Error: {type(e).__name__}: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
