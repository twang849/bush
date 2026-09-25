#!/usr/bin/env python3
"""
A minimal MCP (Model Context Protocol) server that offers ONE tool: `bash`.

It is a stand-in for Claude Code's built-in Bash tool so we can experiment with
how shell commands are run. Version 0.1 tries to behave exactly like the real
tool: same inputs (command, timeout in ms, description), runs the command in
bash, remembers the working directory between calls, returns stdout + stderr,
reports a non-zero exit code, and kills the command after the timeout.

Output over SAVE_THRESHOLD_CHARS is NOT sent back directly. It is saved to a
numbered file in RESULTS_DIR (0001.txt, 0002.txt, ...) and the reply is a short
note: the path, exit code and size. The model reads the file with bash (cat,
sed -n, grep, ...). Commands that mention RESULTS_DIR always get their output
sent back directly, so reading a saved file does not get saved again.

Protocol: JSON-RPC 2.0, one JSON object per line on stdin -> one per line on
stdout. Only stdlib is used so it runs inside any container that has python3.
Never print to stdout except protocol replies; use stderr for logging.
"""
import json
import os
import subprocess
import sys

DEFAULT_TIMEOUT_MS = 120_000
MAX_TIMEOUT_MS = 600_000
MAX_OUTPUT_CHARS = 30_000
CWD_MARKER = "__MCP_BASH_CWD__"
RESULTS_DIR = os.environ.get("MCP_BASH_RESULTS_DIR", "/tmp/mcp_bash_results")
SAVE_THRESHOLD_CHARS = 2_000

TOOL = {
    "name": "bash",
    "description": (
        "Executes a bash command and returns its output. Output over "
        f"{SAVE_THRESHOLD_CHARS} characters is not returned: it is saved to a file "
        f"in {RESULTS_DIR} and you get back the file path, exit code and size. "
        "Read that file with commands like `sed -n`, `head`, `tail` or `grep`; "
        f"output of commands that mention {RESULTS_DIR} is always returned. The "
        "working directory persists between calls. `timeout` is in milliseconds "
        "(default 120000, max 600000)."
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

    def run(self, command: str, timeout_ms: int | None) -> tuple[str, bool, str]:
        """Run `command` in bash. Returns (full output text, is_error, status)."""
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
            return text, True, "timed out"
        except FileNotFoundError:
            return "bash not found in this environment", True, "bash not found"

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
        return text, proc.returncode != 0, f"exit code {proc.returncode}"


def _decode(data) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


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


class ResultStore:
    """Saves long bash outputs to RESULTS_DIR/NNNN.txt."""

    def __init__(self, directory: str) -> None:
        self.dir = directory
        os.makedirs(self.dir, exist_ok=True)
        self.count = 0

    def save(self, text: str) -> str:
        self.count += 1
        path = os.path.join(self.dir, f"{self.count:04d}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path


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
    store = ResultStore(RESULTS_DIR)
    log(f"started, cwd={runner.cwd}, results={store.dir}")
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
                "serverInfo": {"name": "mcp-bash", "version": "0.1"},
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
            text, is_error, status = runner.run(command, args.get("timeout"))
            if len(text) <= SAVE_THRESHOLD_CHARS or store.dir in command:
                # Short output, or the model is reading a saved file: send it directly.
                reply(msg_id, {"content": [{"type": "text", "text": _truncate(text)}],
                               "isError": is_error})
                continue
            path = store.save(text)
            n_lines = text.count("\n") + 1
            note = (f"Output too long to show ({len(text)} chars, {n_lines} lines, "
                    f"{status}). Saved to {path}; read it with sed -n, head, tail or grep.")
            reply(msg_id, {"content": [{"type": "text", "text": note}], "isError": is_error})
        elif method == "ping":
            reply(msg_id, {})
        else:
            reply(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})


if __name__ == "__main__":
    main()
