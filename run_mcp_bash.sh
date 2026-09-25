#!/usr/bin/env bash
# Run one Terminal-Bench task with Claude Code, but with the built-in Bash tool
# replaced by our MCP server (mcp_bash/server.py).
#
# Before running, export your auth (see README "Using a subscription"):
#   export CLAUDE_CODE_OAUTH_TOKEN='sk-ant-oat...' ; export CLAUDE_FORCE_OAUTH=1
# Usage: ./run_mcp_bash.sh [task-glob] [job-name]
#   DATASET=swe-bench/swe-bench-verified@latest ./run_mcp_bash.sh '*scikit-learn-14141' mcpbash-sklearn-14141
set -euo pipefail
cd "$(dirname "$0")"

TASK="${1:-*html-js-filter}"
JOB="${2:-mcpbash-html-js-filter}"
MODEL="${MODEL:-anthropic/claude-sonnet-5}"
DATASET="${DATASET:-terminal-bench/terminal-bench@latest}"   # e.g. DATASET=swe-bench/swe-bench-verified@latest
# Built-in Claude Code tools to switch off (comma-separated). By default the agent loses
# every tool that reads, searches or edits files, so all file work goes through our MCP
# bash tool (cat, grep, sed, ...). DISALLOWED=Bash gives the old setup (only Bash swapped).
DISALLOWED="${DISALLOWED:-Bash,Read,Edit,Write,Grep,Glob,NotebookEdit}"
# SWE-bench images are Intel-only (x86_64). On Apple Silicon Docker refuses to pull them
# ("no match for platform in manifest") unless we ask for the Intel platform; Docker then
# runs them under emulation. Harmless for Terminal-Bench images, which have arm64 builds.
export DOCKER_DEFAULT_PLATFORM="${DOCKER_DEFAULT_PLATFORM:-linux/amd64}"

# Record which version of this repo produced the run. Everything printed below goes
# to the terminal AND to jobs/<job-name>/run.log (Harbor is fine with the folder
# existing as long as it holds no config.json from a different run).
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then COMMIT="$COMMIT (uncommitted changes)"; fi
mkdir -p "jobs/$JOB"
{
  echo "=== run_mcp_bash.sh ==="
  echo "date:    $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "commit:  $COMMIT"
  echo "task:    $TASK"
  echo "job:     $JOB"
  echo "model:   $MODEL"
  echo "dataset: $DATASET"
  echo "disallowed: $DISALLOWED"
  echo "======================="
  PYTHONPATH=. harbor run -d "$DATASET" -i "$TASK" -n 1 \
    -a mcp_bash_agent:ClaudeCodeMcpBash -m "$MODEL" \
    --ak disallowed_tools="$DISALLOWED" \
    --ak append_system_prompt="The Bash tool has been renamed mcp__mcpbash__bash. The tools $DISALLOWED are disabled; use shell commands through mcp__mcpbash__bash for them (cat, grep, find, sed, heredocs, ...). If a command prints more than 2000 characters, the output is saved to a file under /tmp/mcp_bash_results and you get the path; read it with sed -n, head, tail or grep." \
    --job-name "$JOB"
} 2>&1 | tee -a "jobs/$JOB/run.log"
