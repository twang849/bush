# The three shortest Terminal-Bench tasks

Written 2026-09-18. Ranked by `expert_time_estimate_hours` in each task's `task.toml`
(the author's guess of how long a human expert needs). All 66 tasks get the same 8-hour
agent time limit, so this field is the only built-in difficulty signal. Everything not
listed here is 1.5 h or more. Three tasks need a GPU (`math-eval-grader`, `jax-speedrun-gpu`,
`fp8-rmsnorm-gemm`) and cannot run on a Mac.

To rebuild the ranking: download the task folders (text only, ~30 s) and read every `task.toml`.

```bash
harbor dataset download terminal-bench/terminal-bench@latest -o /tmp/tb-tasks
grep -H expert_time_estimate_hours /tmp/tb-tasks/terminal-bench/*/task.toml | sort -t= -k2 -n
```

## 1. `html-js-filter` — 0.75 h, Security

- **Task:** write `/app/filter.py`, an HTML sanitizer that blocks XSS. Instruction is 137 words.
- **Container:** prebuilt image, plus a separate browser-based test image (headless Chromium).
  The test runner has a 30-minute limit. First download took ~12 min; both images are now cached.
- **Status:** our default task. Baseline `claude-code` and the MCP Bash agent both scored 0
  (same hidden test fails, `test_filter_blocks_xss`). Short for a human, not easy for a model.
- **Run:** `./run_mcp_bash.sh` (defaults to this task).

## 2. `photonic-waveguide-routing` — 0.75 h, Software

- **Task:** read `/app/layout_spec.json`, write `/app/routing_result_1.json` with waypoint paths
  for nine "nets" that stay on the board, avoid obstacles, keep minimum separation, and minimize
  a weighted cost. A `check_routing.py` is provided in the container for self-checking.
- **Container:** `python:3.13-slim` + numpy, scipy, shapely, rtree. Small, quick to build.
  Test runner limit is 5 minutes.
- **Why pick it:** best second task for comparing the MCP Bash swap. Pure Python, no browser,
  no prebuilt image to download.
- **Run:** `./run_mcp_bash.sh '*photonic-waveguide-routing' mcpbash-photonic`

## 3. `music-harmony` — 1.0 h, Media

- **Task:** read a melody from `/app/Harmony.pdf`, write a four-voice Bach-style harmony as
  MusicXML to `/app/harmony.mxl`, with Roman numeral labels in `<harmony>` elements.
  Instruction is 110 words.
- **Container:** `python:3.11-slim` with one PDF copied in. Smallest image of the three.
  Test runner limit is 60 seconds.
- **Why (not) pick it:** cheapest to build, but it is a music-theory task that needs PDF reading
  and MusicXML output, so it says little about a shell tool.
- **Run:** `./run_mcp_bash.sh '*music-harmony' mcpbash-music-harmony`
