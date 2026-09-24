#!/usr/bin/env python3
"""Turn a Harbor job folder into a single HTML page you can read in a browser.

Usage:
    python3 render_log.py jobs/<job-name> [--fragment] [-o out.html]

It reads, from the first trial folder inside the job:
  agent/claude-code.txt   the Claude Code event stream (one JSON object per line)
  agent/trajectory.json   only used to recover the task prompt the model was given
  result.json             cost, tokens, timing, reward
  verifier/test-stdout.txt the hidden test output
and writes <job>/transcript.html (or -o path).

--fragment drops the <!doctype>/<html>/<head>/<body> wrapper (for publishing
as a Claude artifact, which adds its own wrapper).
"""
import argparse, html, json, re, sys
from pathlib import Path


def esc(s):
    return html.escape(str(s), quote=False)


def fmt_json(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False)


def inline_md(text):
    """Escape text, then turn `code` into <code>. Nothing fancier."""
    t = esc(text)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    return t


def block_md(text):
    """Very small markdown: fenced code blocks + paragraphs + inline code."""
    out, parts = [], re.split(r"```(\w*)\n(.*?)```", text, flags=re.S)
    i = 0
    while i < len(parts):
        chunk = parts[i]
        for para in re.split(r"\n\s*\n", chunk.strip()):
            if para.strip():
                out.append("<p>" + inline_md(para).replace("\n", "<br>") + "</p>")
        if i + 2 < len(parts):
            out.append("<pre><code>" + esc(parts[i + 2]) + "</code></pre>")
        i += 3
    return "\n".join(out)


def tool_result_text(content):
    """tool_result content is either a string or a list of {type:text} blocks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    bits = []
    for b in content:
        if isinstance(b, dict):
            bits.append(b.get("text") or fmt_json(b))
        else:
            bits.append(str(b))
    return "\n".join(bits)


def summarize_input(name, inp):
    """One-line label for a tool call header."""
    if not isinstance(inp, dict):
        return esc(str(inp))[:160]
    for key in ("command", "file_path", "pattern", "path", "description", "prompt", "query"):
        if key in inp and isinstance(inp[key], str):
            v = inp[key].strip().split("\n")[0]
            return esc(v[:160] + ("…" if len(v) > 160 else ""))
    return esc(", ".join(inp.keys()))


def render_tool_input(name, inp):
    if not isinstance(inp, dict):
        return "<pre>" + esc(inp) + "</pre>"
    if name.endswith("bash") and "command" in inp:
        rest = {k: v for k, v in inp.items() if k != "command"}
        h = '<div class="lbl">command</div><pre class="sh">' + esc(inp["command"]) + "</pre>"
        if rest:
            h += '<div class="lbl">other arguments</div><pre>' + esc(fmt_json(rest)) + "</pre>"
        return h
    if name == "Edit" and "old_string" in inp:
        h = '<div class="lbl">file</div><pre>' + esc(inp.get("file_path", "")) + "</pre>"
        h += '<div class="diff"><div><div class="lbl del">old</div><pre class="del">' + esc(inp["old_string"]) + "</pre></div>"
        h += '<div><div class="lbl add">new</div><pre class="add">' + esc(inp.get("new_string", "")) + "</pre></div></div>"
        return h
    if name == "Write" and "content" in inp:
        return ('<div class="lbl">file</div><pre>' + esc(inp.get("file_path", "")) + "</pre>"
                '<div class="lbl">content</div><pre>' + esc(inp["content"]) + "</pre>")
    return "<pre>" + esc(fmt_json(inp)) + "</pre>"


def details(summary_html, body_html, open_=False, cls=""):
    return (f'<details class="{cls}"{" open" if open_ else ""}><summary>{summary_html}</summary>'
            f'<div class="body">{body_html}</div></details>')


def load(job_dir):
    job_dir = Path(job_dir)
    trials = [p for p in job_dir.iterdir() if p.is_dir() and (p / "agent").exists()]
    if not trials:
        sys.exit(f"no trial folder with an agent/ dir inside {job_dir}")
    trial = sorted(trials)[0]
    events = []
    for line in (trial / "agent" / "claude-code.txt").read_text().splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"type": "raw", "text": line})
    task_prompt = None
    tj = trial / "agent" / "trajectory.json"
    if tj.exists():
        for step in json.loads(tj.read_text()).get("steps", []):
            if step.get("source") == "user":
                task_prompt = step.get("message")
                break
    result = json.loads((trial / "result.json").read_text()) if (trial / "result.json").exists() else {}
    tests = (trial / "verifier" / "test-stdout.txt")
    tests = tests.read_text() if tests.exists() else ""
    return trial, events, task_prompt, result, tests


def render(job_dir, fragment=False):
    trial, events, task_prompt, result, tests = load(job_dir)
    job_name = Path(job_dir).name
    task = result.get("task_name", job_name)
    reward = (result.get("verifier_result") or {}).get("rewards", {}).get("reward")
    ar = result.get("agent_result") or {}
    model = (result.get("agent_info") or {}).get("model_info", {}).get("name", "")

    def dur(section):
        s = result.get(section) or {}
        try:
            from datetime import datetime
            a = datetime.fromisoformat(s["started_at"].replace("Z", "+00:00"))
            b = datetime.fromisoformat(s["finished_at"].replace("Z", "+00:00"))
            return f"{(b - a).total_seconds():.0f}s"
        except Exception:
            return "–"

    # ---- walk events, build the timeline ----
    rows = []
    tool_names = {}  # tool_use_id -> name
    n_calls = 0
    n_bash = 0
    turn = 0

    if task_prompt:
        rows.append(f'<section class="turn user"><div class="rail">task</div><div class="msg">'
                    f'<div class="who">Task prompt given to the agent</div>{block_md(task_prompt)}</div></section>')

    for ev in events:
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            tools = ev.get("tools", [])
            mcp = ", ".join(f'{m["name"]} ({m.get("status")})' for m in ev.get("mcp_servers", []))
            body = (f'<div class="kv"><b>model</b><span>{esc(ev.get("model"))}</span>'
                    f'<b>Claude Code</b><span>{esc(ev.get("claude_code_version"))}</span>'
                    f'<b>permission mode</b><span>{esc(ev.get("permissionMode"))}</span>'
                    f'<b>MCP servers</b><span>{esc(mcp) or "none"}</span>'
                    f'<b>Bash tool present?</b><span>{"yes" if "Bash" in tools else "no (disabled)"}</span></div>'
                    f'<div class="lbl">tools available</div><div class="chips">'
                    + "".join(f'<span class="chip{" hi" if x.startswith("mcp__") else ""}">{esc(x)}</span>' for x in tools)
                    + "</div>")
            rows.append('<section class="turn sys"><div class="rail">init</div><div class="msg">'
                        + details("Session start: tools and settings", body, cls="sysd") + "</div></section>")
        elif t == "assistant":
            turn += 1
            content = ev["message"].get("content", [])
            parts = []
            for c in content:
                ct = c.get("type")
                if ct == "thinking":
                    if c.get("thinking"):
                        parts.append(details("thinking", "<pre>" + esc(c["thinking"]) + "</pre>", cls="think"))
                    else:
                        parts.append('<div class="note">thinking block (empty / redacted)</div>')
                elif ct == "text":
                    parts.append('<div class="text">' + block_md(c.get("text", "")) + "</div>")
                elif ct == "tool_use":
                    n_calls += 1
                    name = c.get("name", "?")
                    tool_names[c.get("id")] = name
                    is_bash = name.endswith("bash")
                    n_bash += is_bash
                    parts.append(details(
                        f'<span class="tool{" bash" if is_bash else ""}">{esc(name)}</span>'
                        f'<span class="arg">{summarize_input(name, c.get("input"))}</span>',
                        render_tool_input(name, c.get("input")), open_=True, cls="call"))
            usage = ev["message"].get("usage") or {}
            meta = ""
            if usage:
                meta = (f'<div class="meta">out {usage.get("output_tokens", 0)} tok · '
                        f'cache read {usage.get("cache_read_input_tokens", 0)} · '
                        f'cache write {usage.get("cache_creation_input_tokens", 0)}</div>')
            rows.append(f'<section class="turn asst"><div class="rail">#{turn}<br><small>agent</small></div>'
                        f'<div class="msg">{"".join(parts)}{meta}</div></section>')
        elif t == "user":
            content = ev["message"].get("content", [])
            if isinstance(content, str):
                rows.append(f'<section class="turn user"><div class="rail">user</div><div class="msg">{block_md(content)}</div></section>')
                continue
            parts = []
            for c in content:
                if c.get("type") == "tool_result":
                    name = tool_names.get(c.get("tool_use_id"), "tool")
                    txt = tool_result_text(c.get("content"))
                    err = c.get("is_error")
                    lines = txt.count("\n") + 1
                    label = (f'<span class="tool{" bash" if name.endswith("bash") else ""}">{esc(name)}</span>'
                             f'<span class="arg">result · {lines} line{"s" if lines != 1 else ""}'
                             f'{" · <b class=err>error</b>" if err else ""}</span>')
                    parts.append(details(label, "<pre>" + esc(txt) + "</pre>", open_=lines <= 40, cls="result" + (" iserr" if err else "")))
                elif c.get("type") == "text":
                    parts.append('<div class="text">' + block_md(c.get("text", "")) + "</div>")
            rows.append(f'<section class="turn res"><div class="rail">→<br><small>result</small></div><div class="msg">{"".join(parts)}</div></section>')
        elif t == "result":
            ok = not ev.get("is_error")
            body = (f'<div class="kv"><b>status</b><span>{esc(ev.get("subtype"))}</span>'
                    f'<b>turns</b><span>{ev.get("num_turns")}</span>'
                    f'<b>wall time</b><span>{(ev.get("duration_ms") or 0)/1000:.1f}s</span>'
                    f'<b>cost</b><span>${ev.get("total_cost_usd", 0):.4f}</span></div>'
                    f'<div class="lbl">final message</div><div class="text">{block_md(ev.get("result") or "")}</div>')
            rows.append(f'<section class="turn sys"><div class="rail">end</div><div class="msg">'
                        + details(f'Agent finished ({"ok" if ok else "error"})', body, open_=True, cls="sysd") + "</div></section>")
        elif t == "rate_limit_event":
            info = ev.get("rate_limit_info") or {}
            rows.append(f'<section class="turn sys tiny"><div class="rail"></div><div class="msg note">rate-limit event: {esc(info.get("status", ""))}</div></section>')
        else:
            rows.append(f'<section class="turn sys tiny"><div class="rail"></div><div class="msg note">{esc(t)} event</div></section>')

    if tests:
        rows.append('<section class="turn sys"><div class="rail">tests</div><div class="msg">'
                    + details("Hidden test output (verifier)", "<pre>" + esc(tests) + "</pre>", cls="sysd") + "</div></section>")

    verdict = "no verdict" if reward is None else ("PASS" if reward >= 1 else f"FAIL ({reward})")
    vcls = "na" if reward is None else ("pass" if reward >= 1 else "fail")

    head = f"""<title>{esc(job_name)} transcript</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{--bg:#f4f4f1;--panel:#fff;--ink:#1c2128;--mute:#6b7280;--line:#dcdcd6;--rail:#8a8f99;
--acc:#0e7490;--acc-bg:#e6f4f7;--asst:#f9f9f7;--res:#f1f2f4;--user:#fbf7ea;--user-line:#e5d9a8;
--pass:#15803d;--pass-bg:#e4f5ea;--fail:#b91c1c;--fail-bg:#fbe7e7;--del:#fbe7e7;--add:#e4f5ea;--code:#eeeeea}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#15171b;--panel:#1d2026;--ink:#e6e7ea;--mute:#9aa0aa;--line:#2f333b;--rail:#7d838e;
--acc:#5ec5d8;--acc-bg:#12303a;--asst:#1d2026;--res:#191c21;--user:#26231a;--user-line:#4a4325;
--pass:#4ade80;--pass-bg:#15301f;--fail:#f87171;--fail-bg:#3a1a1a;--del:#3a1a1a;--add:#15301f;--code:#14161a}}}}
:root[data-theme="dark"]{{--bg:#15171b;--panel:#1d2026;--ink:#e6e7ea;--mute:#9aa0aa;--line:#2f333b;--rail:#7d838e;
--acc:#5ec5d8;--acc-bg:#12303a;--asst:#1d2026;--res:#191c21;--user:#26231a;--user-line:#4a4325;
--pass:#4ade80;--pass-bg:#15301f;--fail:#f87171;--fail-bg:#3a1a1a;--del:#3a1a1a;--add:#15301f;--code:#14161a}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "IBM Plex Sans",system-ui,sans-serif}}
.wrap{{max-width:960px;margin:0 auto;padding:0 16px 64px}}
header{{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:14px 0 10px;margin-bottom:20px}}
header h1{{font-size:18px;font-weight:600;margin:0 0 6px;text-wrap:balance}}
header h1 small{{font-weight:400;color:var(--mute)}}
.stats{{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--mute);font-variant-numeric:tabular-nums}}
.stats b{{color:var(--ink);font-weight:500}}
.verdict{{display:inline-block;padding:1px 8px;border-radius:4px;font-weight:600;font-size:12px;letter-spacing:.04em}}
.verdict.pass{{background:var(--pass-bg);color:var(--pass)}}.verdict.fail{{background:var(--fail-bg);color:var(--fail)}}.verdict.na{{background:var(--res);color:var(--mute)}}
.ctl{{margin-left:auto;display:flex;gap:6px}}
.ctl button{{font:inherit;font-size:12px;padding:2px 9px;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:4px;cursor:pointer}}
.ctl button:focus-visible{{outline:2px solid var(--acc)}}
.turn{{display:grid;grid-template-columns:52px 1fr;gap:12px;margin-bottom:12px}}
.rail{{font-family:"IBM Plex Mono",monospace;font-size:12px;color:var(--rail);text-align:right;padding-top:10px;line-height:1.2}}
.rail small{{font-size:10px;text-transform:uppercase;letter-spacing:.06em}}
.msg{{min-width:0;border:1px solid var(--line);border-radius:6px;padding:10px 14px;background:var(--panel)}}
.asst .msg{{background:var(--asst)}}
.res .msg{{background:var(--res);border-style:dashed}}
.user .msg{{background:var(--user);border-color:var(--user-line)}}
.sys .msg{{background:transparent}}
.tiny .msg{{border:0;padding:0 14px;font-size:12px}}
.who{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin-bottom:4px}}
.text p{{margin:.3em 0}}
.note{{color:var(--mute);font-size:12px;font-style:italic}}
.meta{{color:var(--mute);font-size:11px;margin-top:8px;font-variant-numeric:tabular-nums}}
details{{border-top:1px solid var(--line);margin-top:8px;padding-top:6px}}
details:first-child{{border-top:0;margin-top:0;padding-top:0}}
summary{{cursor:pointer;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;list-style:none;font-size:13px}}
summary::-webkit-details-marker{{display:none}}
summary::before{{content:"▸";color:var(--mute);font-size:11px;flex:none}}
details[open]>summary::before{{content:"▾"}}
summary:focus-visible{{outline:2px solid var(--acc);border-radius:3px}}
.tool{{font-family:"IBM Plex Mono",monospace;font-weight:500;padding:0 6px;border-radius:3px;background:var(--code);flex:none}}
.tool.bash{{background:var(--acc-bg);color:var(--acc)}}
.arg{{font-family:"IBM Plex Mono",monospace;color:var(--mute);font-size:12px;overflow-wrap:anywhere}}
.err{{color:var(--fail)}}
.iserr>summary{{color:var(--fail)}}
.body{{margin-top:6px}}
pre{{margin:4px 0;padding:8px 10px;background:var(--code);border-radius:4px;font:12.5px/1.45 "IBM Plex Mono",monospace;overflow-x:auto;white-space:pre-wrap;overflow-wrap:anywhere;max-height:520px;overflow-y:auto}}
pre.sh{{border-left:3px solid var(--acc)}}
pre.del{{background:var(--del)}}pre.add{{background:var(--add)}}
code{{font:12.5px "IBM Plex Mono",monospace;background:var(--code);padding:0 4px;border-radius:3px}}
pre code{{padding:0;background:none}}
.lbl{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin-top:8px}}
.lbl.del{{color:var(--fail)}}.lbl.add{{color:var(--pass)}}
.diff{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
@media (max-width:640px){{.diff{{grid-template-columns:1fr}}.turn{{grid-template-columns:40px 1fr;gap:8px}}}}
.kv{{display:grid;grid-template-columns:max-content 1fr;gap:3px 14px;font-size:13px}}
.kv b{{font-weight:500;color:var(--mute)}}
.chips{{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}}
.chip{{font:11px "IBM Plex Mono",monospace;padding:1px 6px;border:1px solid var(--line);border-radius:3px;color:var(--mute)}}
.chip.hi{{border-color:var(--acc);color:var(--acc)}}
.think>summary{{color:var(--mute);font-style:italic}}
</style>"""

    body = f"""<div class="wrap">
<header>
<h1>{esc(task)} <small>· {esc(job_name)}</small></h1>
<div class="stats">
<span class="verdict {vcls}">{verdict}</span>
<span>model <b>{esc(model)}</b></span>
<span>tool calls <b>{n_calls}</b> ({n_bash} via mcp bash)</span>
<span>cost <b>${ar.get("cost_usd", 0):.4f}</b></span>
<span>tokens in <b>{ar.get("n_input_tokens", 0):,}</b> · out <b>{ar.get("n_output_tokens", 0):,}</b></span>
<span>agent ran <b>{dur("agent_execution")}</b> · setup {dur("agent_setup")} · tests {dur("verifier")}</span>
<span class="ctl"><button type="button" id="exp">expand all</button><button type="button" id="col">collapse all</button></span>
</div>
</header>
{"".join(rows)}
</div>
<script>
document.getElementById('exp').onclick=()=>document.querySelectorAll('details').forEach(d=>d.open=true);
document.getElementById('col').onclick=()=>document.querySelectorAll('details').forEach(d=>d.open=false);
</script>"""

    if fragment:
        return head + "\n" + body
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">' + head + "</head><body>" + body + "</body></html>")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir")
    ap.add_argument("-o", "--out")
    ap.add_argument("--fragment", action="store_true", help="omit the html/head/body wrapper (for artifacts)")
    a = ap.parse_args()
    out = Path(a.out) if a.out else Path(a.job_dir) / "transcript.html"
    out.write_text(render(a.job_dir, a.fragment))
    print(out)
