import json
import os
import signal
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

from config import D1_URL, PI_BIN, load_qwen_config

# Initialize FastMCP Server
mcp = FastMCP(
    "qwen-delegate",
    instructions=(
        "Delegation bridge to run Qwen as an autonomous coding implementation worker "
        "and LiquidAI d1-2B as a zero-generation decision & verification engine. "
        "Supports synchronous execution for fast tasks (15-45s) and async background "
        "execution for heavy, long-running tasks without hitting client timeouts."
    ),
)

QWEN_BASE_URL, QWEN_API_KEY, QWEN_MODEL = load_qwen_config()

TASKS_DIR = Path.home() / ".cache" / "qwen-delegate" / "tasks"
TASKS_DIR.mkdir(parents=True, exist_ok=True)


def resolve_workspace(files: Optional[list[str]], explicit_cwd: Optional[str]) -> tuple[str, list[str]]:
    """Automatically resolves the correct working directory and file attachments."""
    if explicit_cwd and os.path.exists(explicit_cwd):
        base_dir = Path(explicit_cwd).resolve()
    else:
        base_dir = Path(os.getcwd()).resolve()

    resolved_files = []
    repos_dir = Path.home() / "repos"

    if files:
        for f in files:
            p = Path(f)
            if p.is_absolute() and p.exists():
                resolved_files.append(str(p))
                if not explicit_cwd:
                    curr = p.parent
                    while curr != curr.parent:
                        if (curr / ".git").exists():
                            base_dir = curr
                            break
                        curr = curr.parent
            else:
                local_path = base_dir / f
                if local_path.exists():
                    resolved_files.append(str(local_path))
                elif repos_dir.exists():
                    matches = list(repos_dir.glob(f"*/{f}"))
                    if matches:
                        match = matches[0]
                        resolved_files.append(str(match))
                        if not explicit_cwd:
                            curr = match.parent
                            while curr != curr.parent and curr != repos_dir:
                                if (curr / ".git").exists():
                                    base_dir = curr
                                    break
                                curr = curr.parent

    return str(base_dir), resolved_files


def is_pid_alive(pid: int) -> bool:
    """Checks if a process ID is currently running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def get_task_meta(task_id: str) -> Optional[dict]:
    meta_path = TASKS_DIR / f"{task_id}.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_task_meta(meta: dict):
    task_id = meta["task_id"]
    meta_path = TASKS_DIR / f"{task_id}.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


@mcp.tool()
def qwen_implement_task(
    task: str,
    files: Optional[list[str]] = None,
    working_dir: Optional[str] = None,
    allow_terminal: bool = True,
    background: bool = True,
    timeout_seconds: int = 150,
) -> str:
    """Delegate an autonomous code implementation task to Qwen (The Builder).

    Qwen runs with standard file editing tools (read, edit, write, bash) with
    --no-mcp enabled (0 research schema tokens wasted). Qwen inspects files,
    writes diffs/code, runs tests, and refines changes.

    IMPORTANT TIMING EXPECTATION:
    Remote Qwen inference runs at ~20-30 tokens/second. A full implementation
    with unit tests typically takes 1.5 to 3.5 minutes. When background=True
    is used (default), BE PATIENT: check status every 45-60s and DO NOT take
    over the coding task prematurely.

    Args:
        task: Detailed instructions for the task (interfaces, requirements, edge cases).
        files: Optional list of relevant file paths to mount into Qwen's prompt.
        working_dir: Directory where the task should execute (auto-detected if omitted).
        allow_terminal: Whether to allow Qwen to run bash commands (e.g. pytest, linters).
        background: If True (default), spawns Qwen in the background immediately and returns
                    a task_id so tasks can run for 2-5+ minutes without hitting MCP socket limits.
        timeout_seconds: Sync timeout if background=False (capped at 160s).
    """
    cwd, target_files = resolve_workspace(files, working_dir)
    tools = "read,edit,write,bash" if allow_terminal else "read,edit,write"

    cmd = [
        PI_BIN,
        "--no-mcp",                     # Strips 25k+ tokens of research MCP schemas
        "--tools", tools,               # Only code manipulation tools
        "--no-session",                 # Ephemeral clean run
        "-p",                           # Print/non-interactive mode
    ]

    for f_path in target_files:
        cmd.append(f"@{f_path}")

    cmd.append(task)

    # --- ASYNC BACKGROUND MODE ---
    if background:
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        log_path = TASKS_DIR / f"{task_id}.log"
        log_file = open(log_path, "w", encoding="utf-8")

        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.DEVNULL,     # Critical: signals EOF to pi so it terminates after -p
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,       # Detach process group so it lives independently
        )
        log_file.close()                  # Process holds the duplicate file descriptor

        meta = {
            "task_id": task_id,
            "pid": proc.pid,
            "status": "running",
            "start_time": datetime.now().isoformat(),
            "working_dir": cwd,
            "target_files": target_files,
            "task": task[:300],
            "log_path": str(log_path),
        }
        save_task_meta(meta)

        return (
            f"Task dispatched to Qwen in background.\n"
            f"• Task ID: {task_id}\n"
            f"• PID: {proc.pid}\n"
            f"• Working Directory: {cwd}\n"
            f"• Log File: {log_path}\n\n"
            f"Check status anytime using: qwen_check_task(task_id='{task_id}')"
        )

    # --- SYNCHRONOUS MODE ---
    safe_timeout = min(max(timeout_seconds, 10), 160)
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=safe_timeout,
        )
        output = proc.stdout.strip()
        if proc.returncode != 0 and proc.stderr:
            output += f"\n[Process stderr (exit {proc.returncode})]:\n{proc.stderr.strip()}"
        return output or "Task completed with no standard output."
    except subprocess.TimeoutExpired as te:
        partial = (te.stdout.decode() if isinstance(te.stdout, bytes) else str(te.stdout or "")).strip()
        return (
            f"Notice: Synchronous execution reached safety timeout ({safe_timeout}s).\n"
            f"Target Directory: {cwd}\n"
            f"Partial output before timeout:\n{partial or '[No partial output captured]'}\n\n"
            f"Tip: For heavy jobs, pass background=True to run asynchronously without time limits."
        )
    except Exception as e:
        return f"Error executing Qwen task: {type(e).__name__}: {str(e)}"


@mcp.tool()
def qwen_check_task(task_id: str) -> str:
    """Check the status, output, and progress of an asynchronous background Qwen task.

    Args:
        task_id: The task ID returned by qwen_implement_task(background=True).
    """
    meta = get_task_meta(task_id)
    if not meta:
        return f"Error: No task found with ID '{task_id}'."

    pid = meta.get("pid")
    log_path = Path(meta.get("log_path", ""))
    is_alive = is_pid_alive(pid) if pid else False

    # Read log file
    log_content = ""
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                log_content = "".join(lines[-150:])  # Last 150 lines
        except Exception as e:
            log_content = f"[Error reading log: {e}]"

    if is_alive:
        status_str = "RUNNING"
        meta["status"] = "running"
        guidance = (
            "• Progress Guidance: Remote Qwen inference runs at ~20-30 tokens/sec. "
            "A standard coding task takes 1.5 to 3.5 minutes. The process is actively running. "
            "Please schedule a check in 45-60s using the schedule tool; do NOT abort or author the code directly."
        )
    else:
        status_str = "COMPLETED"
        meta["status"] = "completed"
        guidance = "• Task has finished execution. Review the output below."
        if "end_time" not in meta:
            meta["end_time"] = datetime.now().isoformat()
        save_task_meta(meta)

    return (
        f"=== Task {task_id} [{status_str}] ===\n"
        f"• Working Directory: {meta.get('working_dir')}\n"
        f"• Started: {meta.get('start_time')}\n"
        f"• Status: {status_str} (PID: {pid})\n"
        f"• Log Path: {log_path}\n"
        f"{guidance}\n\n"
        f"--- Output (last 150 lines) ---\n"
        f"{log_content or '[No output yet]'}"
    )


@mcp.tool()
def qwen_list_tasks(limit: int = 10) -> str:
    """List recent background tasks dispatched to Qwen.

    Args:
        limit: Number of recent tasks to return (default: 10).
    """
    task_files = sorted(TASKS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True)
    if not task_files:
        return "No background tasks found."

    results = []
    for tf in task_files[:limit]:
        try:
            with open(tf, "r", encoding="utf-8") as f:
                meta = json.load(f)
                tid = meta.get("task_id", tf.stem)
                pid = meta.get("pid")
                alive = is_pid_alive(pid) if pid else False
                status = "RUNNING" if alive else meta.get("status", "COMPLETED").upper()
                results.append(
                    f"• {tid} | Status: {status} | Started: {meta.get('start_time')} | Dir: {meta.get('working_dir')}\n"
                    f"  Task: {meta.get('task', '')[:120]}"
                )
        except Exception:
            continue

    return "\n\n".join(results) or "No valid tasks found."


@mcp.tool()
def qwen_cancel_task(task_id: str) -> str:
    """Terminate a running background Qwen task.

    Args:
        task_id: The task ID to cancel.
    """
    meta = get_task_meta(task_id)
    if not meta:
        return f"Error: No task found with ID '{task_id}'."

    pid = meta.get("pid")
    if not pid or not is_pid_alive(pid):
        return f"Task '{task_id}' is not running."

    try:
        # Kill the entire process group
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        time.sleep(0.5)
        if is_pid_alive(pid):
            os.killpg(pgid, signal.SIGKILL)
        meta["status"] = "cancelled"
        save_task_meta(meta)
        return f"Task '{task_id}' (PID {pid}, PGID {pgid}) successfully terminated."
    except Exception as e:
        return f"Error terminating task: {type(e).__name__}: {str(e)}"


@mcp.tool()
def qwen_raw_complete(
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> str:
    """Direct high-speed completion from remote Qwen model without tool loops or file I/O.

    Useful when Gemini just needs a raw code snippet, regex, algorithm, or translation
    without touching the local disk.

    Args:
        prompt: The user query or code generation prompt.
        system_prompt: Optional custom system prompt.
        max_tokens: Maximum tokens to generate (default: 4096).
        temperature: Sampling temperature (default: 0.2).
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": f"Bearer {QWEN_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": QWEN_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(f"{QWEN_BASE_URL}/chat/completions", headers=headers, json=payload)
            if resp.status_code != 200:
                return f"Error from Qwen server (HTTP {resp.status_code}): {resp.text}"

            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return "Qwen server returned an empty choices list."

            message = choices[0].get("message", {})
            content = message.get("content") or ""
            reasoning = message.get("reasoning_content") or ""

            if reasoning and content:
                return f"<thinking>\n{reasoning}\n</thinking>\n\n{content}"
            elif content:
                return content
            elif reasoning:
                return f"<thinking>\n{reasoning}\n</thinking>"
            return "No content returned by model."
    except Exception as e:
        return f"Network error communicating with Qwen: {type(e).__name__}: {str(e)}"


@mcp.tool()
def d1_verify_claim(claim: str, context: str) -> str:
    """Fact-check and verify empirical claims against text using LiquidAI d1-2B on the Mac mini.

    Returns supported verdict, calibrated probabilities, and exact extracted evidence span.
    Generates 0 output tokens via continuous state evaluation.

    Args:
        claim: The claim statement to verify.
        context: Reference source text to verify against.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "verify_claim_d1",
            "arguments": {
                "claim": claim,
                "context": context,
            },
        },
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(D1_URL, json=payload)
            if resp.status_code != 200:
                return f"Error from d1 server (HTTP {resp.status_code}): {resp.text}"

            data = resp.json()
            if "result" in data and "content" in data["result"]:
                items = data["result"]["content"]
                if items and isinstance(items, list):
                    return items[0].get("text", json.dumps(data["result"]))
            return json.dumps(data)
    except Exception as e:
        return f"Error communicating with d1 decision server: {type(e).__name__}: {str(e)}"


@mcp.tool()
def d1_score_document(
    text: str,
    metrics: dict[str, Any],
    criteria: Optional[list[str]] = None,
) -> str:
    """Compute calibrated continuous/ordinal scores along specified dimensions using d1-2B.

    Args:
        text: Target document or snippet to evaluate.
        metrics: Dictionary of metric names to instructions (e.g. {"clarity": "Rate readability"}).
        criteria: Optional ordinal score levels (e.g. ["poor", "fair", "good", "excellent"]).
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "score_document",
            "arguments": {
                "text": text,
                "metrics": metrics,
                "criteria": criteria,
            },
        },
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(D1_URL, json=payload)
            if resp.status_code != 200:
                return f"Error from d1 server (HTTP {resp.status_code}): {resp.text}"

            data = resp.json()
            if "result" in data and "content" in data["result"]:
                items = data["result"]["content"]
                if items and isinstance(items, list):
                    return items[0].get("text", json.dumps(data["result"]))
            return json.dumps(data)
    except Exception as e:
        return f"Error communicating with d1 decision server: {type(e).__name__}: {str(e)}"


if __name__ == "__main__":
    import sys

    if "--http" in sys.argv:
        port = 8005
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        print(f"Starting qwen-delegate Streamable HTTP server on port {port}...")
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
