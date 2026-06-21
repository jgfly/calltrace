"""Render the (collapsed) call tree to a self-contained, readable HTML file."""

import os
import html as _html

from .tree import CallNode, LoopNode


def _fmt_dur(s):
    if s is None or s <= 0:
        return ""
    if s < 1e-3:
        return f"{s * 1e6:.0f}µs"
    if s < 1:
        return f"{s * 1e3:.1f}ms"
    return f"{s:.2f}s"


def _color_for(name):
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    hue = h % 360
    return f"hsl({hue},62%,52%)"


def _loc(filename, lineno, base):
    if not filename:
        return ""
    if filename.startswith("<"):
        return filename
    try:
        rel = os.path.relpath(filename, base)
    except ValueError:
        rel = filename
    return f"{rel}:{lineno}"


def _render_node(node, base, depth):
    is_loop = isinstance(node, LoopNode)
    children = node.children
    has_children = len(children) > 0

    if is_loop:
        body_names = ", ".join(
            _html.escape(c.name) for c in children[:3]
        )
        if len(children) > 3:
            body_names += ", …"
        label = (
            f'<span class="loop-ico">↻</span>'
            f'<span class="loop-lbl">loop</span>'
            f'<span class="count" title="iterations">×{node.count}</span>'
            f'<span class="fn loop-body">body: {body_names}</span>'
        )
    else:
        name_esc = _html.escape(node.name)
        label = f'<span class="fn" style="color:{_color_for(node.name)}">{name_esc}</span>'
        if node.count > 1:
            label += f'<span class="count" title="repeat count">×{node.count}</span>'
        if node.external:
            label += '<span class="ext" title="external package (not stepped into)">ext</span>'
        loc = _loc(node.filename, node.lineno, base)
        if loc:
            label += f'<span class="loc">{_html.escape(loc)}</span>'

    dur = _fmt_dur(node.duration)
    if dur:
        label += f'<span class="dur">{dur}</span>'

    if has_children:
        open_attr = " open" if depth <= 1 else ""
        child_html = "".join(
            _render_node(c, base, depth + 1) for c in children
        )
        return (
            f'<details class="node"{open_attr}>'
            f'<summary>{label}<span class="chev"></span></summary>'
            f'<div class="children">{child_html}</div>'
            f'</details>'
        )
    return f'<div class="node leaf"><div class="leafrow">{label}</div></div>'


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>calltrace — {title}</title>
<style>
:root {{
  --bg: #0f1115;
  --panel: #161a21;
  --panel2: #1c2129;
  --line: #2a313c;
  --txt: #e6e9ef;
  --muted: #8b94a3;
  --accent: #7aa2f7;
  --loop: #bb9af7;
  --ext: #e5c890;
  --count: #73daca;
  --dur: #9aa5ce;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--txt);
  font-family: "SF Mono", "JetBrains Mono", "Fira Code", Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 1.5;
}}
header {{
  position: sticky; top: 0; z-index: 10;
  background: linear-gradient(180deg, var(--panel) 0%, rgba(22,26,33,.96) 100%);
  border-bottom: 1px solid var(--line);
  padding: 14px 20px;
}}
h1 {{ margin: 0 0 4px; font-size: 16px; font-weight: 600; }}
h1 .tag {{ color: var(--accent); }}
.subtitle {{ color: var(--muted); font-size: 12px; word-break: break-all; }}
.stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }}
.stat {{
  background: var(--panel2); border: 1px solid var(--line);
  border-radius: 6px; padding: 6px 10px; min-width: 84px;
}}
.stat .k {{ color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: .06em; }}
.stat .v {{ color: var(--txt); font-size: 14px; font-weight: 600; }}
.controls {{ margin-top: 12px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
.controls button {{
  background: var(--panel2); color: var(--txt); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 10px; cursor: pointer; font: inherit; font-size: 12px;
}}
.controls button:hover {{ border-color: var(--accent); color: var(--accent); }}
.controls input {{
  background: var(--panel2); color: var(--txt); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 10px; font: inherit; font-size: 12px; width: 240px;
}}
.controls input::placeholder {{ color: var(--muted); }}
main {{ padding: 14px 20px 60px; }}
.legend {{ color: var(--muted); font-size: 11px; margin-top: 8px; }}
.legend span {{ margin-right: 12px; }}
.legend .b {{ display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }}

.node {{ padding-left: 0; }}
.node > summary {{
  list-style: none; cursor: pointer; padding: 2px 4px; border-radius: 4px;
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  position: relative;
}}
.node > summary::-webkit-details-marker {{ display: none; }}
.node > summary:hover {{ background: var(--panel2); }}
.chev {{
  display: inline-block; width: 10px; color: var(--muted);
  font-size: 10px; margin-left: auto;
}}
details.node > summary .chev::before {{ content: "▸"; }}
details.node[open] > summary .chev::before {{ content: "▾"; }}
.leaf .leafrow {{ padding: 2px 4px 2px 18px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: var(--muted); }}
.leaf .leafrow .fn {{ color: var(--muted); }}
.children {{
  margin-left: 10px; padding-left: 10px;
  border-left: 1px solid var(--line);
}}
.fn {{ font-weight: 600; }}
.leafrow .fn {{ font-weight: 400; }}
.count {{
  background: rgba(115,218,202,.12); color: var(--count);
  border: 1px solid rgba(115,218,202,.25);
  border-radius: 10px; padding: 0 7px; font-size: 11px; font-weight: 600;
}}
.ext {{
  background: rgba(229,200,144,.12); color: var(--ext);
  border: 1px solid rgba(229,200,144,.25);
  border-radius: 4px; padding: 0 5px; font-size: 10px;
}}
.loc {{ color: var(--muted); font-size: 11px; }}
.dur {{ color: var(--dur); font-size: 11px; margin-left: auto; }}
.loop-ico {{ color: var(--loop); font-weight: 700; }}
.loop-lbl {{ color: var(--loop); font-weight: 600; }}
.loop-body {{ color: var(--muted); font-weight: 400; font-size: 12px; }}
.node.hidden {{ display: none; }}
.empty {{ color: var(--muted); padding: 20px 0; }}
</style>
</head>
<body>
<header>
  <h1><span class="tag">calltrace</span> — {title}</h1>
  <div class="subtitle">{subtitle}</div>
  <div class="stats">
    <div class="stat"><div class="k">raw calls</div><div class="v">{raw_calls}</div></div>
    <div class="stat"><div class="k">nodes</div><div class="v">{collapsed_nodes}</div></div>
    <div class="stat"><div class="k">max depth</div><div class="v">{max_depth}</div></div>
    <div class="stat"><div class="k">wall time</div><div class="v">{wall}</div></div>
    <div class="stat"><div class="k">loops collapsed</div><div class="v">{collapsed}</div></div>
  </div>
  <div class="controls">
    <button onclick="expandAll()">expand all</button>
    <button onclick="collapseAll()">collapse all</button>
    <input id="filter" placeholder="filter by function name…" oninput="doFilter()">
  </div>
  <div class="legend">
    <span><span class="b" style="background:var(--loop)"></span>loop block</span>
    <span><span class="b" style="background:var(--count)"></span>× repeat count</span>
    <span><span class="b" style="background:var(--ext)"></span>ext = external (not stepped into)</span>
  </div>
</header>
<main>
{tree}
</main>
<script>
function expandAll() {{ document.querySelectorAll('details.node').forEach(d => d.open = true); }}
function collapseAll() {{ document.querySelectorAll('details.node').forEach((d,i) => d.open = false); }}
function doFilter() {{
  const q = document.getElementById('filter').value.trim().toLowerCase();
  const all = document.querySelectorAll('.node');
  if (!q) {{ all.forEach(n => n.classList.remove('hidden')); return; }}
  all.forEach(n => {{
    const sum = n.querySelector('summary, .leafrow');
    const text = sum ? sum.textContent.toLowerCase() : '';
    // show if this node or any descendant matches
    const descMatch = n.querySelectorAll('.fn, .loc').length &&
      Array.from(n.querySelectorAll('*')).some(e => e.textContent.toLowerCase().includes(q));
    if (text.includes(q) || descMatch) {{
      n.classList.remove('hidden');
      let p = n.parentElement;
      while (p && p.tagName === 'DETAILS') {{ p.classList.remove('hidden'); p.open = true; p = p.parentElement.parentElement; }}
    }} else {{ n.classList.add('hidden'); }}
  }});
}}
</script>
</body>
</html>
"""


def render_html(root, script, base, raw_calls, collapsed_nodes, max_depth,
                elapsed, collapsed, step_in_dirs, step_all_imports):
    title = os.path.basename(script)
    subtitle = (
        f"script: {script}  ·  step-into: {', '.join(step_in_dirs) or '(none)'}"
        f"  ·  step-all-imports: {step_all_imports}"
    )
    if not root.children:
        tree = '<div class="empty">No project calls were captured. Check that --project points at the package you want to trace.</div>'
    else:
        tree = "\n".join(_render_node(c, base, 1) for c in root.children)

    return _HTML_TEMPLATE.format(
        title=_html.escape(title),
        subtitle=_html.escape(subtitle),
        raw_calls=f"{raw_calls:,}",
        collapsed_nodes=f"{collapsed_nodes:,}",
        max_depth=max_depth,
        wall=_fmt_dur(elapsed),
        collapsed="yes" if collapsed else "no",
        tree=tree,
    )
