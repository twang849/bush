"""
Harbor agent = the built-in Claude Code agent + our own MCP `bash` tool.

Why a subclass: Claude Code is closed source, so we cannot edit its Bash tool.
Instead we (1) upload mcp_bash/server.py into the task container and
(2) register it as an MCP server so Claude Code sees a tool named
`mcp__mcpbash__bash`. The real Bash tool is switched off from the command line
with `--ak disallowed_tools=Bash` (see run_mcp_bash.sh).

Everything else (subscription auth, trajectories, --ak options) is inherited
from harbor.agents.installed.claude_code.ClaudeCode unchanged.
"""
from pathlib import Path

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.environments.base import BaseEnvironment
from harbor.models.task.config import MCPServerConfig

SERVER_LOCAL = Path(__file__).parent / "mcp_bash" / "server.py"
SERVER_REMOTE_DIR = "/opt/mcp_bash"
SERVER_REMOTE = f"{SERVER_REMOTE_DIR}/server.py"


class ClaudeCodeMcpBash(ClaudeCode):
    @staticmethod
    def name() -> str:
        return "claude-code-mcp-bash"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Harbor writes this list to $CLAUDE_CONFIG_DIR/.claude.json before the
        # run (ClaudeCode._build_register_mcp_servers_command), which is how
        # Claude Code learns about the server without a trust prompt.
        self.mcp_servers.append(
            MCPServerConfig(
                name="mcpbash",
                transport="stdio",
                command="python3",
                args=[SERVER_REMOTE],
            )
        )

    async def install(self, environment: BaseEnvironment) -> None:
        # Installs the claude CLI in the container exactly as the built-in agent does.
        await super().install(environment)
        # Then copy our server in so `python3 /opt/mcp_bash/server.py` works.
        await environment.exec(
            f"mkdir -p {SERVER_REMOTE_DIR} && chmod 777 {SERVER_REMOTE_DIR}"
        )
        await environment.upload_file(SERVER_LOCAL, SERVER_REMOTE)
        await environment.exec(f"chmod 755 {SERVER_REMOTE}")
        self.logger.info("Uploaded MCP bash server to %s", SERVER_REMOTE)
