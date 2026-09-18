#!/usr/bin/env bash
# Run one Terminal-Bench task with Claude Code, but with the built-in Bash tool
# replaced by our MCP server (mcp_bash/server.py).
#
# Before running, export your auth (see README "Using a subscription"):
#   export CLAUDE_CODE_OAUTH_TOKEN='sk-ant-oat...' ; export CLAUDE_FORCE_OAUTH=1
# Usage: ./run_mcp_bash.sh [task-glob] [job-name]
set -euo pipefail
cd "$(dirname "$0")"

TASK="${1:-*html-js-filter}"
JOB="${2:-mcpbash-html-js-filter}"
MODEL="${MODEL:-anthropic/claude-sonnet-5}"

PYTHONPATH=. harbor run -d terminal-bench/terminal-bench@latest -i "$TASK" -n 1 \
  -a mcp_bash_agent:ClaudeCodeMcpBash -m "$MODEL" \
  --ak disallowed_tools=Bash \
  --ak append_system_prompt="The Bash tool has been renamed mcp__mcpbash__bash." \
  --job-name "$JOB"
