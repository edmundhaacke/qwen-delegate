import json
import os
import subprocess
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
        "Enables Gemini (Architect) to delegate concrete coding tasks to Qwen (Builder) "
        "without 178 MCP tool schema tokens bloating the context window."
    )
)

QWEN_BASE_URL, QWEN_API_KEY, QWEN_MODEL = load_qwen_config()


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
                # If explicit cwd wasn't provided, infer from file path
                if not explicit_cwd:
                    # Look for git root or parent dir
                    curr = p.parent
                    while curr != curr.parent:
                        if (curr / ".git").exists():
                            base_dir = curr
                            break
                        curr = curr.parent
            else:
                # Check in current base_dir
                local_path = base_dir / f
                if local_path.exists():
                    resolved_files.append(str(local_path))
                elif repos_dir.exists():
                    # Search across local repositories
                    matches = list(repos_dir.glob(f"*/{f}"))
                    if matches:
                        match = matches[0]
                        resolved_files.append(str(match))
                        if not explicit_cwd:
                            # Set base_dir to the matched repo
                            curr = match.parent
                            while curr != curr.parent and curr != repos_dir:
                                if (curr / ".git").exists():
                                    base_dir = curr
                                    break
                                curr = curr.parent

    return str(base_dir), resolved_files


@mcp.tool()
def qwen_implement_task(
    task: str,
    files: Optional[list[str]] = None,
    working_dir: Optional[str] = None,
    allow_terminal: bool = True,
    timeout_seconds: int = 150,
) -> str:
    """Delegate an autonomous code implementation task to Qwen.

    Qwen runs with standard file editing tools (read, edit, write, bash) but with
    --no-mcp enabled, ensuring 0 MCP schema tokens are wasted. Qwen can inspect
    files, write diffs/code, run tests, and refine changes.

    Args:
        task: Detailed instructions for the task (interfaces, requirements, edge cases).
        files: Optional list of relevant file paths to explicitly mount into Qwen's prompt.
        working_dir: Directory where the task should execute (auto-detected from files if omitted).
        allow_terminal: Whether to allow Qwen to run bash commands (e.g. pytest, linters).
        timeout_seconds: Timeout before terminating the process (capped at 160s to stay within client limits).
    """
    # Cap timeout to 160s max to prevent Antigravity client-side 180s hard disconnect
    safe_timeout = min(max(timeout_seconds, 10), 160)
    cwd, target_files = resolve_workspace(files, working_dir)
    tools = "read,edit,write,bash" if allow_terminal else "read,edit,write"

    cmd = [
        PI_BIN,
        "--no-mcp",                     # Critical: strips 25k+ tokens of research MCP schemas
        "--tools", tools,               # Only code manipulation tools
        "--no-session",                 # Ephemeral clean run
        "-p",                           # Print/non-interactive mode
    ]

    for f_path in target_files:
        cmd.append(f"@{f_path}")

    cmd.append(task)

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
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
            f"Notice: Qwen implementation hit the safety timeout ({safe_timeout}s).\n"
            f"Target Directory: {cwd}\n"
            f"Partial output before timeout:\n{partial or '[No partial output captured]'}\n\n"
            "Tip: For heavy scripts or data processing, delegate isolated code edits rather than long-running data execution."
        )
    except Exception as e:
        return f"Error executing Qwen task: {type(e).__name__}: {str(e)}"


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
    # FastMCP supports stdio mode by default with mcp.run()
    # If run with --sse or --http, can run web transport
    if "--http" in sys.argv:
        port = 8005
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        print(f"Starting qwen-delegate Streamable HTTP server on port {port}...")
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
