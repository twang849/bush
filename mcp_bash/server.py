#!/usr/bin/env python3
"""
A minimal MCP (Model Context Protocol) server that offers ONE tool: `bash`.

It is a stand-in for Claude Code's built-in Bash tool so we can experiment with
how shell commands are run. Version 0.1 tries to behave exactly like the real
tool: same inputs (command, timeout in ms, description), runs the command in
bash, remembers the working directory between calls, returns stdout + stderr,
reports a non-zero exit code, and kills the command after the timeout.

Version 0.2 adds an output cache (in memory, so one per session). If the exact
same command text was run before, the model gets a short "unchanged" note when
the output (including exit code) is the same, or a unified diff when it is not.
If more than half the lines changed, it gets the full output instead of a diff.

Protocol: JSON-RPC 2.0, one JSON object per line on stdin -> one per line on
stdout. Only stdlib is used so it runs inside any container that has python3.
Never print to stdout except protocol replies; use stderr for logging.
"""
import difflib
import json
import os
import subprocess
import sys

DEFAULT_TIMEOUT_MS = 120_000
MAX_TIMEOUT_MS = 600_000
MAX_OUTPUT_CHARS = 30_000
CWD_MARKER = "__MCP_BASH_CWD__"

TOOL = {
    "name": "bash",
    "description": (
        "Executes a bash command and returns its output. The working directory "
        "persists between calls. `timeout` is in milliseconds (default 120000, "
        "max 600000). If a command was run before in this session, you get "
        "either a note that the output is unchanged, or a unified diff against "
        "the previous output (or the full output if more than half the lines changed)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to execute"},
            "timeout": {
                "type": "number",
                "description": "Optional timeout in milliseconds (max 600000)",
            },
            "description": {
                "type": "string",
                "description": "Clear, concise description of what this command does",
            },
        },
        "required": ["command"],
    },
}


def log(msg: str) -> None:
    print(f"[mcp-bash] {msg}", file=sys.stderr, flush=True)


class BashRunner:
    def __init__(self) -> None:
        self.cwd = os.environ.get("MCP_BASH_CWD") or os.getcwd()
        # Exact command text -> full (untruncated) text of its last run.
        self.cache: dict[str, str] = {}

    def run_cached(self, command: str, timeout_ms: int | None) -> tuple[str, bool]:
        """Like run(), but replaces repeated output with an "unchanged" note or a diff."""
        full, exit_code = self.run(command, timeout_ms)
        is_error = exit_code != 0
        if exit_code is None:
            # Timeout or no bash: never cached.
            return _truncate(full), True

        old = self.cache.get(command)
        self.cache[command] = full
        if old is None:
            status, text = "miss", _truncate(full)
        elif old == full:
            status = "hit"
            text = f"Output unchanged since the last run of this exact command (exit code {exit_code})."
        elif _changed_fraction(old, full) > 0.5:
            # Mostly different output: a diff would be harder to read than the output itself.
            status, text = "rewrite", _truncate(full)
        else:
            status = "diff"
            diff = difflib.unified_diff(
                old.splitlines(), full.splitlines(),
                fromfile="previous", tofile="current", lineterm="", n=2,
            )
            text = _truncate(
                "Output changed since the last run of this exact command. "
                "Unified diff (previous -> current):\n" + "\n".join(diff)
            )
        log(f"cache={status} full_chars={len(full)} sent_chars={len(text)}")
        return text, is_error

    def run(self, command: str, timeout_ms: int | None) -> tuple[str, int | None]:
        """Run `command` in bash. Returns (full untruncated text, exit code or None on timeout/no bash)."""
        if timeout_ms is None:
            timeout_ms = DEFAULT_TIMEOUT_MS
        timeout_ms = int(min(max(timeout_ms, 1), MAX_TIMEOUT_MS))

        # After the user's command, print the final working directory on its
        # own line so we can remember it for the next call (like the real tool).
        wrapped = f"{command}\n__rc=$?; printf '\\n{CWD_MARKER}%s\\n' \"$PWD\"; exit $__rc"
        try:
            proc = subprocess.run(
                ["bash", "-c", wrapped],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout_ms / 1000,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as exc:
            partial = _decode(exc.stdout) + _decode(exc.stderr)
            text = f"Command timed out after {timeout_ms}ms"
            if partial.strip():
                text += "\n" + partial
            return text, None
        except FileNotFoundError:
            return "bash not found in this environment", None

        stdout, new_cwd = _split_cwd_marker(proc.stdout)
        if new_cwd and os.path.isdir(new_cwd):
            self.cwd = new_cwd

        parts = []
        if stdout.strip():
            parts.append(stdout.rstrip("\n"))
        if proc.stderr.strip():
            parts.append(proc.stderr.rstrip("\n"))
        if proc.returncode != 0:
            parts.append(f"Exit code {proc.returncode}")
        text = "\n".join(parts) if parts else "(no output)"
        return text, proc.returncode


def _decode(data) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def _changed_fraction(old: str, new: str) -> float:
    """Share of lines (0..1) that differ between two outputs, measured against the longer one."""
    old_lines, new_lines = old.splitlines(), new.splitlines()
    total = max(len(old_lines), len(new_lines))
    if total == 0:
        return 0.0
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    same = sum(block.size for block in matcher.get_matching_blocks())
    return 1 - same / total


def _split_cwd_marker(stdout: str) -> tuple[str, str | None]:
    idx = stdout.rfind(CWD_MARKER)
    if idx == -1:
        return stdout, None
    new_cwd = stdout[idx + len(CWD_MARKER):].strip()
    return stdout[:idx], new_cwd


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    dropped = len(text) - MAX_OUTPUT_CHARS
    return text[:half] + f"\n\n... [{dropped} characters truncated] ...\n\n" + text[-half:]


def reply(msg_id, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main() -> None:
    runner = BashRunner()
    log(f"started, cwd={runner.cwd}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            log(f"bad json: {line[:200]}")
            continue

        method = req.get("method")
        msg_id = req.get("id")
        params = req.get("params") or {}

        if msg_id is None:
            # A notification (e.g. notifications/initialized): no reply expected.
            continue

        if method == "initialize":
            reply(msg_id, {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mcp-bash", "version": "0.2"},
            })
        elif method == "tools/list":
            reply(msg_id, {"tools": [TOOL]})
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name != "bash":
                reply(msg_id, error={"code": -32602, "message": f"Unknown tool: {name}"})
                continue
            command = args.get("command")
            if not isinstance(command, str) or not command:
                reply(msg_id, {"content": [{"type": "text", "text": "Missing required `command`"}],
                               "isError": True})
                continue
            text, is_error = runner.run_cached(command, args.get("timeout"))
            reply(msg_id, {"content": [{"type": "text", "text": text}], "isError": is_error})
        elif method == "ping":
            reply(msg_id, {})
        else:
            reply(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})


if __name__ == "__main__":
    main()
