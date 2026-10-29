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


import argparse
import os
import subprocess
import sys
from pathlib import Path

# Add repo dir to sys.path
REPO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_DIR))

from config import PI_BIN
from server import resolve_workspace


def print_tty(msg: str) -> None:
    """Print directly to controlling terminal if available, bypassing stdout capture.
    
    This provides immediate human visibility in the terminal without polluting
    the process stdout buffer that Antigravity captures and injects back into
    Gemini's context window on task wakeup (saving input tokens).
    """
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(msg)
            tty.flush()
    except (OSError, IOError):
        pass


LIVE_LOG_FILE = Path("/tmp/qwen_live.log")


def spawn_popup_terminal(log_path: Path) -> None:
    """Spawns an interactive Terminal.app window tailing the live Qwen generation."""
    script = f'''
    tell application "Terminal"
        activate
        do script "clear; echo -e '\\033[1;36m┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\\033[0m'; echo -e '\\033[1;36m┃         ⚡ QWEN BUILDER LIVE STREAM (Architect -> Builder)   ┃\\033[0m'; echo -e '\\033[1;36m┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\\033[0m\\n'; tail -n +1 -f '{log_path}'"
    end tell
    '''
    try:
        subprocess.run(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Standalone CLI runner for Qwen delegation."
    )
    parser.add_argument(
        "-f",
        "--task-file",
        dest="task_file",
        help="Path to file or artifact containing task instructions",
    )
    parser.add_argument(
        "-p",
        "--preset",
        dest="preset",
        default=None,
        help="Generation preset: 'coding' (default), 'thinking' (for code review/reasoning), 'instruct'",
    )
    parser.add_argument(
        "--popup",
        dest="popup",
        action="store_true",
        default=True,
        help="Open an active Terminal.app window streaming Qwen's generation (default: True)",
    )
    parser.add_argument(
        "--no-popup",
        dest="popup",
        action="store_false",
        help="Disable automatic popup Terminal window",
    )
    parser.add_argument(
        "args",
        nargs="*",
        help="[task description] [file1 file2 ...] (if -f not specified, first arg is task)",
    )

    parsed = parser.parse_args()

    task = ""
    task_source = None
    raw_files = []

    if parsed.task_file:
        task_path = Path(parsed.task_file).expanduser().resolve()
        if not task_path.exists():
            print(f"Error: Specified task file does not exist: {parsed.task_file}", file=sys.stderr)
            sys.exit(1)
        task = task_path.read_text(encoding="utf-8")
        task_source = str(task_path)
        raw_files = parsed.args
    else:
        if not parsed.args:
            parser.print_help()
            sys.exit(1)
        task = parsed.args[0]
        raw_files = parsed.args[1:]

    # Clean file arguments (remove leading @ if passed)
    clean_files = [f[1:] if f.startswith("@") else f for f in raw_files]

    cwd, target_files = resolve_workspace(clean_files if clean_files else None, None)

    cmd = [
        PI_BIN,
        "--no-mcp",                     # 0 MCP schema bloat (~25k tokens saved)
        "--tools", "read,edit,write",
        "--no-session",
        "-p",
    ]

    for f_path in target_files:
        cmd.append(f"@{f_path}")

    # Determine preset: explicit flag > tag in prompt > default 'coding'
    preset = parsed.preset or "coding"
    pi_task = task
    if not pi_task.lstrip().startswith("["):
        pi_task = f"[preset: {preset}]\n{pi_task}"

    cmd.append(pi_task)

    # 1. Save dispatch to persistent local inspection file (~/.gemini/last_delegation.md)
    try:
        inspect_path = Path.home() / ".gemini" / "last_delegation.md"
        inspect_content = (
            f"# Qwen Builder Delegation Dispatch\n\n"
            f"- **Workspace**: `{cwd}`\n"
            f"- **Preset**: `{preset}`\n"
        )
        if target_files:
            inspect_content += f"- **Target Files**: {', '.join(f'`{f}`' for f in target_files)}\n"
        if task_source:
            inspect_content += f"- **Spec Source**: `{task_source}`\n"
        inspect_content += f"\n## Instructions Sent to Qwen:\n\n```markdown\n{task.strip()}\n```\n"
        inspect_path.write_text(inspect_content, encoding="utf-8")
    except Exception:
        pass

    # 2. Initialize live streaming log
    try:
        live_header = (
            f"\033[1;33m• Workspace:\033[0m {cwd}\n"
            f"\033[1;33m• Preset:\033[0m {preset}\n"
        )
        if target_files:
            live_header += f"\033[1;33m• Target Files:\033[0m {', '.join(target_files)}\n"
        if task_source:
            live_header += f"\033[1;33m• Spec Source:\033[0m {task_source}\n"
        live_header += f"\n\033[1;32m• Instructions Dispatched to Qwen:\033[0m\n\033[0;37m{task.strip()}\033[0m\n\n"
        live_header += "\033[1;36m--- Output from Qwen (Live Stream) ---\033[0m\n\n"
        LIVE_LOG_FILE.write_text(live_header, encoding="utf-8")
    except Exception:
        pass

    # 3. Check if popup terminal should be launched (default: True, disable via --no-popup or QWEN_POPUP=0)
    should_popup = parsed.popup
    if os.environ.get("QWEN_POPUP", "").lower() in ("0", "false", "no"):
        should_popup = False
    if should_popup:
        spawn_popup_terminal(LIVE_LOG_FILE)

    # 4. Process stdout for Antigravity (concise metadata on start)
    print("=== Qwen Builder Dispatch ===")
    print(f"• Working Directory: {cwd}")
    if target_files:
        print(f"• Target Files: {', '.join(target_files)}")
    if task_source:
        print(f"• Spec File: {task_source}")
    print(f"• Preset: {preset}")
    print("• Execution Mode: Antigravity Background Reactive Callback")
    print("• Status: Actively generating via remote Qwen (20-30 tok/s)...\n")
    sys.stdout.flush()

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        collected_output = []
        with open(LIVE_LOG_FILE, "a", encoding="utf-8") as f:
            for line in iter(proc.stdout.readline, ""):
                f.write(line)
                f.flush()
                collected_output.append(line)

        proc.wait()

        with open(LIVE_LOG_FILE, "a", encoding="utf-8") as f:
            status_text = (
                f"\n\n\033[1;32m[✓ Qwen Task Finished with exit code {proc.returncode}]\033[0m\n"
                if proc.returncode == 0
                else f"\n\n\033[1;31m[✗ Qwen Task Failed with exit code {proc.returncode}]\033[0m\n"
            )
            f.write(status_text)
            f.flush()

        full_output = "".join(collected_output).strip()
        if full_output:
            print("--- Output from Qwen ---")
            print(full_output)
        sys.exit(proc.returncode)
    except Exception as e:
        print(f"Execution Error: {type(e).__name__}: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
