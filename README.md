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

1. **`qwen_implement_task(task, files, working_dir, allow_terminal)`**:
   - Runs Qwen in autonomous coding mode via `pi`.
   - Strips all 178 research MCP tools so no context is wasted.
   - Modifies files directly on disk, runs unit tests, and returns summary output.
2. **`qwen_raw_complete(prompt, system_prompt, max_tokens)`**:
   - Direct high-speed API call to `https://test.edmundhaacke.com/v1/chat/completions`.
   - Used when Gemini needs a quick algorithm, regex, or code snippet without file I/O.
3. **`d1_verify_claim(claim, context)`**:
   - Zero-generation empirical claim verifier using native MLX d1-2B on the M1 Mac mini (`100.126.106.26:8004`).
   - Returns calibrated probabilities and exact extracted span.
4. **`d1_score_document(text, metrics, criteria)`**:
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

## Standalone Terminal Usage

You can also run Qwen as a builder directly from your shell without launching an interactive UI:

```bash
cd /Users/edmundnhs/repos/qwen-delegate
./run_cli.sh "Refactor calculate_scores to handle empty lists" @src/metrics.py
```
