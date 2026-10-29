#!/usr/bin/env bash
# Quick CLI runner to delegate a task to Qwen directly from terminal
# Usage: ./run_cli.sh "Task description" [@optional_file.py]

if [ -z "$1" ]; then
    echo "Usage: ./run_cli.sh \"Task description\" [@optional_file.py]"
    exit 1
fi

pi --no-mcp --tools read,edit,write,bash "$@"
