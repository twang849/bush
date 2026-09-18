# Terminal-Bench with Harbor: cheat sheet

Written 2026-09-14. Everything here was run on this Mac and worked unless marked otherwise.

## What this is

**Terminal-Bench** is a set of 66 coding tasks. Each task is a folder with an instruction, a Docker image, and hidden tests.
**Harbor** is the command-line program that runs the benchmark. One "run" does this for each task:

1. Downloads the task from the Harbor Hub (cached after the first time).
2. Builds and starts a Docker container for it.
3. Installs an "agent" (an AI coding tool such as Claude Code or Codex) inside the container and gives it the instruction.
4. When the agent stops, runs the task's tests inside the container.
5. Writes a score (reward 1 = pass, 0 = fail) plus the full transcript to a folder on your disk.

## Prerequisites (how to check)

```bash
docker info >/dev/null && echo "docker ok"   # Docker Desktop must be running
uv --version                                  # Python tool installer, used to install Harbor
harbor --version                              # expect 0.23.0 or newer
```

If `harbor` is not found, install it and make sure `~/.local/bin` is on your PATH:

```bash
uv tool install harbor
export PATH="$HOME/.local/bin:$PATH"
```

## The minimal run (copy-paste)

Always run from this folder so results land in `~/Projects/tb-harbor/jobs/`.

```bash
cd ~/Projects/tb-harbor

# 1. See what agents exist
harbor agent list

# 2. Dry run: checks the command is valid. Downloads nothing, runs nothing.
harbor run -d terminal-bench/terminal-bench@latest -a oracle -i '*html-js-filter' --dry-run

# 3. Pipeline check with the "oracle" agent. It applies the task's own reference
#    solution, so it needs no model and no API key. Proves Docker + download + tests work.
#    First time: several minutes (Docker image build).
harbor run -d terminal-bench/terminal-bench@latest -a oracle -i '*html-js-filter' -n 1 --job-name oracle-html-js-filter

# 4. Same task with a real agent (see "Using a subscription" below for the env vars first)
harbor run -d terminal-bench/terminal-bench@latest -a claude-code -m anthropic/claude-sonnet-5 -i '*html-js-filter' -n 1 --job-name claude-html-js-filter

# 5. Browse results in a web page (http://127.0.0.1:8080)
harbor view jobs
```

Task-name gotcha: task names carry a `terminal-bench/` prefix. Either write the full name
(`-i terminal-bench/html-js-filter`) or use a wildcard (`-i '*html-js-filter'`). Without one of
those you get "No tasks matched the filter".

## `harbor run` flags you will actually use

| Flag | Meaning |
|---|---|
| `-d terminal-bench/terminal-bench@latest` | Which dataset. `@latest` = newest published version. Pin (e.g. `@4.0.0`) for repeatable numbers. |
| `-a claude-code` | Which agent. Others: `codex`, `terminus-2`, `oracle` (reference solution), `nop` (does nothing, useful for testing the harness). |
| `-m anthropic/claude-sonnet-5` | Model, written as `provider/model-name`. |
| `-i '*pattern'` | Only run tasks whose name matches (glob). Repeatable. |
| `-x '*pattern'` | Skip tasks whose name matches. Repeatable. |
| `-l 5` | Run at most 5 tasks (after the include/exclude filters). |
| `-n 4` | How many tasks to run at the same time (default 4). Use `-n 1` on a laptop. |
| `-k 3` | Attempts per task (default 1). |
| `--job-name NAME` | Folder name under `jobs/` (default: timestamp). |
| `-o DIR` | Put results somewhere other than `./jobs`. |
| `--dry-run` | Validate only. |
| `--ak key=value` | Agent option. See `harbor agent schema claude-code` for the list (e.g. `--ak reasoning_effort=high`, `--ak max_turns=50`, `--ak version=2.1.270`). |
| `--ae KEY=VALUE` | Extra environment variable given to the agent inside the container. |
| `--timeout-multiplier 2` | Give every task twice its normal time limit. |
| `--no-delete` | Keep the container after the run so you can `docker exec` into it. |
| `-y` | Auto-answer yes to prompts. |

Full list: `harbor run --help`.

## Using a subscription instead of an API key

Harbor normally looks for `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`. Both agents also support
subscription login. Benchmark runs count against your plan's usage limits like normal usage,
so keep subscription runs small (a handful of tasks). Use an API key for a full 66-task run.

### Claude subscription (Claude Code agent)

```bash
claude setup-token          # opens a browser, prints a long-lived token starting with sk-ant-oat
export CLAUDE_CODE_OAUTH_TOKEN='<paste the token>'
export CLAUDE_FORCE_OAUTH=1  # tells Harbor to ignore any API key and use the token
harbor run -d terminal-bench/terminal-bench@latest -a claude-code -m anthropic/claude-sonnet-5 -i '*html-js-filter' -n 1
```

Why the second variable: Harbor's Claude Code agent prefers an API key when both are present.
`CLAUDE_FORCE_OAUTH=1` drops the key so the container uses the subscription token.
(Source: `harbor/agents/installed/claude_code.py`, function `_resolve_auth_env`.)

### ChatGPT / Codex subscription (Codex agent)

You are already logged in on this Mac (`~/.codex/auth.json` exists, auth mode is ChatGPT tokens).

```bash
export CODEX_FORCE_AUTH_JSON=1   # Harbor copies ~/.codex/auth.json into the container
harbor run -d terminal-bench/terminal-bench@latest -a codex -m openai/gpt-5.6-sol -i '*html-js-filter' -n 1
```

`gpt-5.6-sol` is the default model in `~/.codex/config.toml`. If you are not logged in, run
`codex login` first. (Source: `harbor/agents/installed/codex.py`, function `_resolve_auth_json_path`.)

**Stale login gotcha (hit on 2026-09-14):** the run ended with `AgentAuthenticationError` and the
Codex log said "Your access token could not be refreshed. Please log out and sign in again."
The login file was six weeks old. Fix: run `codex login` on the Mac, then re-run. Check the
file's age first with:

```bash
python3 -c "import json;print(json.load(open('$HOME/.codex/auth.json'))['last_refresh'])"
```

### Switching back to an API key

```bash
unset CLAUDE_FORCE_OAUTH CODEX_FORCE_AUTH_JSON
export ANTHROPIC_API_KEY='sk-ant-...'     # or OPENAI_API_KEY for codex
```

## Reading results

- Every run makes `jobs/<job-name>/`. Inside: `result.json` (summary), `config.json` (the exact
  settings used), `job.log`, and one folder per trial named `<task>__<id>/`.
- Inside a trial folder (from the real oracle run):
  - `agent/` - the agent's transcript. For Claude Code and Codex this holds the full session log.
  - `verifier/test-stdout.txt` - what the tests printed. `verifier/reward.txt` - the score.
    `verifier/ctrf.json` - per-test pass/fail in a standard format.
  - `artifacts/` - files Harbor copied out of the container after the run (e.g. the solution file).
  - `result.json` - reward, token counts, timings, and `exception_info` if something crashed.
  - `trial.log` - step-by-step log of that one trial.
- `harbor view jobs` starts a local web page that shows the same thing with a nicer layout.
- Reward `1.0` = all tests passed. `0.0` = failed. If the summary table shows an
  **Exceptions** count, the agent crashed before finishing. Read `exception_info` in the trial's
  `result.json`, and the agent's own log in `agent/` (e.g. `agent/codex.txt`).

Quick way to print the reward and any exception for every trial in a job:

```bash
python3 -c "
import json,glob,sys
for f in sorted(glob.glob('jobs/'+sys.argv[1]+'/*/result.json')):
    d=json.load(open(f)); e=d.get('exception_info') or {}
    print(f.split('/')[2], 'reward=', (d.get('verifier_result') or {}).get('rewards'), 'exception=', e.get('exception_type'))
" oracle-html-js-filter
```

## Gotchas

- **First run of a task is slow.** The oracle run of `html-js-filter` took 12m 44s on this Mac,
  almost all of it downloading two prebuilt Docker images (the task environment and the test
  runner). Later runs of the same task reuse them and are much faster.
- **Harmless warnings you will see:** "Skipping image OS validation ... docker inspect returned 1",
  "compose cp failed; retrying download with engine cp", and a LiteLLM "Failed to fetch remote
  model cost map" line. All three appeared on a run that scored 1.0. Ignore them.
- **Some tasks need a GPU or several containers.** Those fail on a Mac. Pick tasks by name with
  `-i` rather than running everything. Task names with `gpu` in them are the obvious ones to skip.
- **`@latest` moves.** For numbers you want to compare across weeks, pin the version.
- **Your local Claude settings do not leak in.** Harbor gives Claude Code its own config folder
  inside the container, so your `~/.claude` memory, CLAUDE.md, and plugins are not used.
  The agent runs with `permission_mode=bypassPermissions` by default (it never asks for approval).
- **Harbor and the `harbor` command live in `~/.local/bin`.** If a new shell can't find it, add
  that folder to PATH.
- **Old docs mention Terminal-Bench 2.0 and the `tb` command.** Those are outdated. Everything is
  Harbor now, and the dataset is at version 4.x.

## Discovery commands

```bash
harbor agent list                    # all built-in agents
harbor agent schema claude-code      # every --ak option the Claude Code agent accepts
harbor agent schema codex
harbor run --help                    # every flag
harbor run -d terminal-bench/terminal-bench@latest -a oracle -i 'zzz' --dry-run   # errors out but prints example task names
```

## Next step: benchmarking a modified tool (not done yet)

- **If the change is inside Claude Code:** the agent installs Claude Code fresh in the container.
  `--ak version=X` picks a published version. For an unpublished local build you would need to
  either publish it or write a small custom agent. Start from `harbor agent schema claude-code`
  and the file `harbor/agents/installed/claude_code.py` in the Harbor install.
- **If the change is to Harbor or one of its agents:** clone Harbor, edit, and run it from the
  checkout with `uv run harbor ...` so your edited code is used.
- Find the installed Harbor source with:
  `ls ~/.local/share/uv/tools/harbor/lib/python*/site-packages/harbor/agents/installed/`

## Custom agent: `mini_agent.py` (added 2026-09-17)
A ~120-line agent written from scratch so you can see exactly what Harbor asks an agent to do.
Read the file top to bottom; the comments explain each part.

| File | What it is |
|---|---|
| `mini_agent.py` | The agent. Asks the model for ONE shell command, runs it in the container, shows the model the output, repeats until the model says `DONE` (max 30 steps). |
| `mock_agent.py` | Test-only copy with a scripted fake model that replays the known solution. Proves the pipeline works with no API key. |
| `jobs/mock-test/` | The passing test run (reward 1.0, 3m 50s). Read `*/agent/transcript.md` to see the loop in action. |

### What Harbor calls on an agent
An agent is a Python class (subclass of `harbor.agents.base.BaseAgent`) with two methods:
1. `setup(environment)` - install tools in the container. `mini_agent` needs nothing, so it does nothing.
2. `run(instruction, environment, context)` - the work. `instruction` is the task text.
   `environment.exec("some command")` runs it in the container and returns `.stdout`, `.stderr`, `.return_code`.
   Fill `context.n_input_tokens` / `n_output_tokens` / `cost_usd`; Harbor writes them to `result.json` under `agent_result`.
After `run()` returns, Harbor runs the task's tests and scores the container.

The agent runs on the Mac (in Harbor's own Python) and only sends commands into the container.
It calls the model through Harbor's built-in `LiteLLM` wrapper, so `-m provider/model` and
the usual `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` variables work.

### Run it
```bash
export ANTHROPIC_API_KEY='sk-ant-...'
cd ~/Projects/tb-harbor
PYTHONPATH=. harbor run -d terminal-bench/terminal-bench@latest -i '*html-js-filter' \
  -a mini_agent:MiniAgent -m anthropic/claude-sonnet-5 -n 1 --job-name mini-first-try
```
- `-a module:Class` loads a custom agent. `PYTHONPATH` must include the folder holding the module,
  which is why the command sets `PYTHONPATH=.` and runs from this folder.
- `-t terminal-bench/html-js-filter` (instead of `-d ... -i ...`) runs that one hub task directly.
  That is the form the mock test used.
- No-key pipeline check (what was run on 2026-09-17):
  `PYTHONPATH=. harbor run -t terminal-bench/html-js-filter -a mock_agent:MockAgent -m fake/scripted -n 1 --job-name mock-test`

### Gotchas
- The Claude subscription token (`CLAUDE_CODE_OAUTH_TOKEN`) does NOT work for this agent. It only
  works for the built-in `claude-code` agent. `mini_agent` needs a real API key.
- Harbor runs in its own Python (`~/.local/share/uv/tools/harbor/bin/python`). If the agent ever
  needs an extra package: `uv tool install harbor --with <pkg>`. `litellm` is already there.
- Commands the model sends run non-interactively. Editors or anything waiting on input hang
  until the 180 s per-command timeout.

### Ideas for the next step
- Edit `SYSTEM_PROMPT` in `mini_agent.py`, re-run the same task, compare transcripts.
- Raise `MAX_STEPS` for harder tasks.
- Add a "think first" line before each command and see whether the score changes.
