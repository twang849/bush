# CLAUDE.md

## What this repo is

An experiment: run Claude Code on Terminal-Bench tasks with its built-in `Bash` tool
swapped for our own MCP (Model Context Protocol) `bash` tool, and compare scores against
the unmodified agent.

- **Terminal-Bench** is a set of 66 coding tasks, each with a Docker image and hidden tests.
- **Harbor** is the CLI that runs the benchmark: builds the container, installs the agent,
  gives it the task, runs the tests, and writes results to `jobs/`.

Claude Code is closed source, so we cannot edit its Bash tool. Instead we turn it off
(`--ak disallowed_tools=Bash`), register an MCP server that offers one tool named
`mcp__mcpbash__bash`, and tell the model the Bash tool was renamed.

## Architecture

```
run_mcp_bash.sh
  └─ harbor run -a mcp_bash_agent:ClaudeCodeMcpBash ...
       └─ ClaudeCodeMcpBash (subclass of Harbor's built-in ClaudeCode agent)
            ├─ install(): installs Claude Code in the container as usual,
            │             then uploads mcp_bash/server.py to /opt/mcp_bash/
            └─ registers "mcpbash" as a stdio MCP server (python3 /opt/mcp_bash/server.py)
                 └─ Claude Code sees tool mcp__mcpbash__bash and uses it instead of Bash
```

## Files

- `README.md` – full Harbor/Terminal-Bench cheat sheet: install, auth (API key or subscription),
  flags, reading results, gotchas, first benchmark numbers. Read this first.
- `SHORT_TASKS.md` – the three shortest tasks, with run commands and current scores.
- `run_mcp_bash.sh` – one-liner to run a task with the MCP Bash agent.
  Usage: `./run_mcp_bash.sh [task-glob] [job-name]` (defaults to `*html-js-filter`).
- `mcp_bash_agent.py` – the custom Harbor agent (`ClaudeCodeMcpBash`).
- `mcp_bash/server.py` – the MCP server. Stdlib only, JSON-RPC over stdin/stdout, one `bash`
  tool that mimics the real one (persistent cwd, timeout, stdout+stderr, exit code).
- `jobs/` – Harbor run outputs (gitignored). One folder per `--job-name`.
- `.env.local`, `*.log` – local auth and run logs (gitignored).

## Running

```bash
export CLAUDE_CODE_OAUTH_TOKEN='sk-ant-oat...'; export CLAUDE_FORCE_OAUTH=1   # or ANTHROPIC_API_KEY
./run_mcp_bash.sh                                   # default task
./run_mcp_bash.sh '*photonic-waveguide-routing' mcpbash-photonic
harbor view jobs                                    # browse results at http://127.0.0.1:8080
```
