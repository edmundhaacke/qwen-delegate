# Qwen Delegate: Gemini $\rightarrow$ Qwen Coding & Decision Bridge

A dedicated local bridge that lets **Gemini (The Architect)** delegate code implementation, file edits, and bash verification to **Qwen (The Builder)**, and zero-generation factual verification to the **LiquidAI d1-2B** decision model on Apple Silicon.

## Key Architecture

```
┌────────────────────────────────────────────────────────┐
│  Gemini (Antigravity CLI / IDE)                        │
│  Role: Architect & Planner                             │
│  • High-level reasoning & system design                │
│  • Defines function signatures & interfaces            │
│  • Reviews diffs and verifies edge cases               │
└──────────────────────────┬─────────────────────────────┘
                           │ delegates via MCP tool: qwen_implement_task
                           ▼
┌────────────────────────────────────────────────────────┐
│  Qwen Builder (via Pi CLI)                             │
│  Flags: --no-mcp --tools read,edit,write,bash          │
│  • 0 MCP schema tokens wasted (~25k saved!)            │
│  • 100% of context window dedicated to code            │
│  • Autonomously reads files, edits diffs, runs tests   │
└────────────────────────────────────────────────────────┘
```

## Available MCP Tools Exposed to Gemini

1. **`qwen_implement_task(task, files, working_dir, allow_terminal, background)`**:
   - Runs Qwen in autonomous coding mode via `pi --no-mcp`.
   - **`background=False` (default)**: Synchronous execution up to 160s (ideal for quick function writing, refactoring, unit tests).
   - **`background=True`**: Asynchronous execution. Dispatches immediately, returns a `task_id` in 0.1s, and runs in the background for 5–30+ minutes without ever hitting Antigravity's 180s MCP client timeout.
2. **`qwen_check_task(task_id)`**:
   - Inspects the status (`RUNNING`, `COMPLETED`, `FAILED`), elapsed time, and streams the latest output logs.
3. **`qwen_list_tasks(limit)`**:
   - Lists recent background tasks and their current execution state.
4. **`qwen_cancel_task(task_id)`**:
   - Gracefully terminates a running background task process group.
5. **`qwen_raw_complete(prompt, system_prompt, max_tokens)`**:
   - Direct high-speed API call to `https://test.edmundhaacke.com/v1/chat/completions`.
   - Used when Gemini needs a quick algorithm, regex, or code snippet without file I/O.
6. **`d1_verify_claim(claim, context)`**:
   - Zero-generation empirical claim verifier using native MLX d1-2B on the M1 Mac mini (`100.126.106.26:8004`).
   - Returns calibrated probabilities and exact extracted span.
7. **`d1_score_document(text, metrics, criteria)`**:
   - Zero-generation ordinal scoring along custom dimensions.

## Installation & Setup

To install dependencies and register the server with Gemini:

```bash
cd /Users/edmundnhs/repos/qwen-delegate
./install.sh
```

This will automatically update `~/.gemini/config/mcp_config.json`:
- Adds `qwen-delegate` (local stdio server)
- Adds `d1-decision` (remote Streamable HTTP server on the Mac mini)

## Standalone Terminal & Background Delegation Usage

You can run Qwen as a builder directly from your shell or delegate via Antigravity background tasks:

```bash
cd /Users/edmundnhs/repos/qwen-delegate

# 1. Standard Code Implementation (preset: coding, temp=0.2)
./run_cli.sh "Refactor calculate_scores to handle empty lists" src/metrics.py

# 2. File / Artifact spec instruction (Zero Token Duplication)
./run_cli.sh -f spec.md src/metrics.py

# 3. Code Review & Reasoning Mode (preset: thinking, temp=1.0)
./run_cli.sh -p thinking "Review this module for race conditions and explain thread safety" src/worker.py

# 4. With Live Popup Window on macOS
./run_cli.sh --popup -f spec.md src/metrics.py
# (Or set `export QWEN_POPUP=1` to always pop up automatically)
```

### Visibility & Live Streaming
- **Live Popup Window (Default: Active)**: Automatically pops up an active Terminal.app window tailing `/tmp/qwen_live.log`, displaying every token and tool call in real time while Qwen generates (disable via `--no-popup` or `export QWEN_POPUP=0`).
- **Local Inspection File**: Every dispatch writes the complete instruction payload to `~/.gemini/last_delegation.md` for instant zero-token inspection.
- **Zero Wakeup Bloat**: Process `stdout` returns only the concise completion output and diff, avoiding prompt re-echoing into Gemini's context window.
