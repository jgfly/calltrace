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


def _rel(filename, base):
    """Relative path of ``filename`` against ``base`` (falls back to raw)."""
    if not filename or filename.startswith("<"):
        return ""
    try:
        return os.path.relpath(filename, base)
    except ValueError:
        return filename


def _loc(filename, lineno, base):
    if not filename:
        return ""
    if filename.startswith("<"):
        return filename
    return f"{_rel(filename, base)}:{lineno}"


def _data_attrs(node, base):
    """``data-file`` / ``data-line`` for the hover tooltip (non-loop nodes only)."""
    if not node.filename or node.filename.startswith("<") or not node.lineno:
        return ""
    rel = _rel(node.filename, base)
    return (
        f' data-file="{_html.escape(rel, quote=True)}"'
        f' data-line="{int(node.lineno)}"'
    )


def _render_node(node, base, depth):
    is_loop = isinstance(node, LoopNode)
    children = node.children
    has_children = len(children) > 0
    data_attrs = "" if is_loop else _data_attrs(node, base)

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
            f'<details class="node"{open_attr}{data_attrs}>'
            f'<summary>{label}<span class="chev"></span></summary>'
            f'<div class="children">{child_html}</div>'
            f'</details>'
        )
    return f'<div class="node leaf"><div class="leafrow"{data_attrs}>{label}</div></div>'


# Tooltip JS, kept as a *raw* string so backslashes (`\\`, `\n`) and braces are
# literal JS -- they would be mangled if this lived inside the .format()'d
# _HTML_TEMPLATE (Python triple-quoted strings eat `\n`; .format eats `{}`).
# It is injected via the {tooltip_js} field, whose value .format() inserts as
# opaque text (no re-parsing of braces/escapes).
_TOOLTIP_JS = r'''// ---- hover source tooltip -------------------------------------------------
const tip = document.getElementById('ct-tip');
let hideTimer = null;
let showTimer = null;
let lastReq = 0;

function esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
// ---- lightweight Python tokenizer for tooltip coloring --------------------
const PY_KW = new Set((`False None True and as assert async await break class continue def del elif ` +
  `else except finally for from global if import in is lambda nonlocal not or pass raise return try ` +
  `while with yield match case`).split(' '));
const PY_BI = new Set((`self cls int str bytes float bool list dict set tuple frozenset range len print ` +
  `open type super object isinstance hasattr getattr setattr enumerate zip map filter sorted sum min max ` +
  `abs round any all Exception ValueError TypeError KeyError IndexError RuntimeError AttributeError`).split(' '));

// Tokenize one source line into token objects {t, v}. Handles triple-quoted
// strings spanning lines via a carried string-state object {ch, triple}.
// Returns {tokens, state}.
function tokenizePyLine(line, state) {
  let out = [];
  let i = 0, n = line.length;
  const push = (t, v) => out.push({t, v});
  // Continue an unterminated string from a previous line?
  if (state && state.ch) {
    const ch = state.ch, triple = state.triple;
    let buf = '';
    while (i < n) {
      if (triple && line[i] === ch && line.substr(i, 3) === ch + ch + ch) {
        buf += ch + ch + ch; i += 3; state = null; break;
      } else if (!triple && line[i] === ch) {
        state = null; i++; break;
      } else if (line[i] === '\\' && i + 1 < n) {
        buf += line[i] + line[i+1]; i += 2;
      } else {
        buf += line[i]; i++;
      }
    }
    if (state) { /* still inside a (triple-quoted) string */ buf += '\n'; }
    push('str', buf);
    if (i >= n) return {tokens: out, state};
  }
  state = null;
  while (i < n) {
    const c = line[i];
    if (c === '#') { push('cmt', line.slice(i)); break; }
    // strings (incl. triple-quoted, f/r/b prefixes). Quote char + triple-ness
    // are detected by hand (no literal triple-quotes in any regex).
    const prefMatch = line.slice(i).match(/^[rbfRBFuU]{0,2}/);
    let pi = i + (prefMatch ? prefMatch[0].length : 0);
    let q = '', triple = false;
    if (pi + 2 < n && ((line[pi] === '"' && line[pi+1] === '"' && line[pi+2] === '"') ||
                       (line[pi] === "'" && line[pi+1] === "'" && line[pi+2] === "'"))) {
      q = line[pi] + line[pi] + line[pi]; triple = true;
    } else if (pi < n && (line[pi] === '"' || line[pi] === "'")) {
      q = line[pi]; triple = false;
    }
    if (q) {
      const qc = q[0];
      let j = pi + q.length;
      let buf = line.slice(i, j);
      let closed = false;
      while (j < n) {
        if (triple && line.substr(j, 3) === q) { buf += q; j += 3; closed = true; break; }
        if (!triple && line[j] === qc) { buf += qc; j++; closed = true; break; }
        if (line[j] === '\\' && j + 1 < n) { buf += line[j] + line[j+1]; j += 2; continue; }
        buf += line[j]; j++;
      }
      if (!closed) { state = {ch: qc, triple}; buf += '\n'; }
      push('str', buf); i = j; continue;
    }
    if (/[0-9]/.test(c) || (c === '.' && i+1 < n && /[0-9]/.test(line[i+1]))) {
      const m = line.slice(i).match(/^[0-9_]*\.?[0-9_]+([eE][+-]?[0-9]+)?[jJ]?/);
      push('num', m[0]); i += m[0].length; continue;
    }
    if (/[A-Za-z_]/.test(c)) {
      const m = line.slice(i).match(/^[A-Za-z_][A-Za-z0-9_]*/);
      const word = m[0];
      const after = line.slice(i + word.length);
      if (/^\s*\(/.test(after) && !PY_KW.has(word)) {
        push('fn', word);
      } else if (PY_KW.has(word)) {
        push('kw', word);
      } else if (PY_BI.has(word)) {
        push('bi', word);
      } else {
        push('txt', word);
      }
      i += word.length; continue;
    }
    // decorator
    if (c === '@' && (i === 0 || /\s/.test(line[i-1]))) {
      const m = line.slice(i).match(/^@[\w.]+/);
      if (m) { push('dfn', m[0]); i += m[0].length; continue; }
    }
    push('txt', c); i++;
  }
  return {tokens: out, state};
}

function renderLineHTML(tokens) {
  // Mark the identifier right after 'def '/'class ' as a definition name.
  for (let k = 0; k < tokens.length; k++) {
    if (tokens[k].t === 'kw' && (tokens[k].v === 'def' || tokens[k].v === 'class')) {
      let m = k + 1;
      while (m < tokens.length && tokens[m].t === 'txt' && /^\s*$/.test(tokens[m].v)) m++;
      if (m < tokens.length) tokens[m].t = 'dfn';
      break;
    }
  }
  return tokens.map(tok => {
    if (tok.t === 'txt') return esc(tok.v);
    return `<span class="tok-${tok.t}">${esc(tok.v)}</span>`;
  }).join('');
}

function renderLines(start, lines, hl) {
  // A table: gutter column (line numbers) + code column. Code keeps real
  // indentation because the cell uses white-space: pre and we never touch
  // leading spaces. Triple-quoted-string state is carried across lines.
  let rows = '';
  let state = null;
  for (let i = 0; i < lines.length; i++) {
    const n = start + i;
    const raw = lines[i] || '';
    const r = tokenizePyLine(raw, state);
    state = r.state;
    const codeHTML = renderLineHTML(r.tokens);
    const cls = n === hl ? ' ct-hl-row' : '';
    rows += `<tr class="ct-row${cls}"><td class="ct-ln">${n}</td><td class="ct-code">${codeHTML || '&#8203;'}</td></tr>`;
  }
  return `<table>${rows}</table>`;
}
function showTip(html, x, y) {
  tip.innerHTML = html;
  tip.style.display = 'block';
  let left = x + 16, top = y + 16;
  const r = tip.getBoundingClientRect();
  if (left + r.width > window.innerWidth - 8) left = Math.max(8, window.innerWidth - r.width - 8);
  if (top + r.height > window.innerHeight - 8) top = Math.max(8, y - r.height - 12);
  tip.style.left = left + 'px';
  tip.style.top = top + 'px';
}
function positionTip(x, y) {
  tip.style.left = (x + 16) + 'px';
  tip.style.top = (y + 16) + 'px';
}

async function resolveCode(file, line) {
  if (CT_SRC_URL) {
    const r = await fetch(`${CT_SRC_URL}/src?file=${encodeURIComponent(file)}&line=${line}&context=14`);
    if (!r.ok) return null;
    const j = await r.json();
    if (j.error) return null;
    return { start: j.start, lines: j.lines, hl: line };
  }
  if (CT_SNIPPETS) {
    const snip = CT_SNIPPETS[file] && CT_SNIPPETS[file][line];
    if (!snip) return null;
    const lines = snip.split('\n');
    return { start: line, lines: lines, hl: line };
  }
  return null;
}

function attachHover(el) {
  el.addEventListener('mouseenter', (e) => {
    const file = el.getAttribute('data-file');
    const line = parseInt(el.getAttribute('data-line'), 10);
    if (!file || !line) return;
    clearTimeout(hideTimer); clearTimeout(showTimer);
    showTip(`<div class="ct-msg">loading…</div>`, e.clientX, e.clientY);
    const req = ++lastReq;
    showTimer = setTimeout(async () => {
      try {
        const code = await resolveCode(file, line);
        if (req !== lastReq) return;
        if (!code) {
          showTip(`<div class="ct-head">${esc(file)}:${line}</div><div class="ct-msg">source unavailable</div>`, e.clientX, e.clientY);
          return;
        }
        const body = renderLines(code.start, code.lines, code.hl);
        showTip(`<div class="ct-head">${esc(file)}:${line}</div>${body}`, e.clientX, e.clientY);
      } catch (err) {
        if (req === lastReq) showTip(`<div class="ct-msg">failed to load source</div>`, e.clientX, e.clientY);
      }
    }, 120);
  });
  el.addEventListener('mousemove', (e) => {
    if (tip.style.display === 'block' && tip.innerHTML.includes('loading')) positionTip(e.clientX, e.clientY);
  });
  el.addEventListener('mouseleave', () => {
    clearTimeout(showTimer);
    hideTimer = setTimeout(() => { tip.style.display = 'none'; }, 200);
  });
}
tip.addEventListener('mouseenter', () => clearTimeout(hideTimer));
tip.addEventListener('mouseleave', () => {
  hideTimer = setTimeout(() => { tip.style.display = 'none'; }, 120);
});

document.querySelectorAll('[data-file][data-line]').forEach(attachHover);
'''


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

#ct-tip {{
  position: fixed; z-index: 50; display: none;
  max-width: min(86vw, 860px); max-height: 60vh; overflow: auto;
  background: var(--panel2); border: 1px solid var(--line);
  border-radius: 8px; box-shadow: 0 8px 28px rgba(0,0,0,.5);
  font-size: 12.5px; line-height: 1.6;
}}
#ct-tip .ct-head {{
  color: var(--muted); font-size: 11px; padding: 8px 12px 6px;
  border-bottom: 1px solid var(--line); word-break: break-all;
  position: sticky; top: 0; background: var(--panel2);
}}
/* A <table> keeps line numbers and code in their own columns, so leading
   whitespace in the code is preserved exactly (no inline-block width math
   that eats indentation) and code wraps without sliding under the gutter. */
#ct-tip table {{ border-collapse: collapse; width: 100%; }}
#ct-tip td {{ vertical-align: top; padding: 0; }}
#ct-tip .ct-ln {{
  color: var(--muted); text-align: right; white-space: pre;
  padding: 0 10px 0 12px; user-select: none; opacity: .7;
  border-right: 1px solid var(--line);
}}
#ct-tip .ct-code {{ white-space: pre-wrap; word-break: break-word;
  padding: 0 12px; font-family: inherit; tab-size: 4; }}
#ct-tip .ct-hl-row .ct-ln {{ color: var(--accent); opacity: 1; }}
#ct-tip .ct-hl-row .ct-code {{ background: rgba(122,162,247,.14);
  box-shadow: inset 3px 0 0 var(--accent); }}
#ct-tip .ct-msg {{ color: var(--muted); padding: 10px 12px; font-style: italic; }}

/* Lightweight Python syntax highlighting (token spans emitted by hlPy). */
#ct-tip .tok-kw  {{ color: #bb9af7; }}
#ct-tip .tok-bi  {{ color: #7dcfff; }}
#ct-tip .tok-str {{ color: #9ece6a; }}
#ct-tip .tok-num {{ color: #ff9e64; }}
#ct-tip .tok-cmt {{ color: #5c6370; font-style: italic; }}
#ct-tip .tok-fn  {{ color: #7aa2f7; }}
#ct-tip .tok-dfn {{ color: #7aa2f7; font-weight: 600; }}
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
<div id="ct-tip" role="tooltip"></div>
<script id="ct-data" type="application/json">{ct_data}</script>
<script>
const CT_DATA = (() => {{
  try {{ return JSON.parse(document.getElementById('ct-data').textContent); }}
  catch (e) {{ return {{}}; }}
}})();
const CT_SNIPPETS = CT_DATA.snippets || null;   // embedded mode: file -> line -> src
const CT_SRC_URL  = CT_DATA.src_url  || null;   // serve mode: base URL to fetch /src from

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

// ---- hover source tooltip (injected as raw text, not via .format) ---------
{tooltip_js}
</script>
</body>
</html>
"""


def render_html(root, script, base, raw_calls, collapsed_nodes, max_depth,
                elapsed, collapsed, step_in_dirs, step_all_imports,
                snippets=None, src_url=None):
    title = os.path.basename(script)
    subtitle = (
        f"script: {script}  ·  step-into: {', '.join(step_in_dirs) or '(none)'}"
        f"  ·  step-all-imports: {step_all_imports}"
    )
    if not root.children:
        tree = '<div class="empty">No project calls were captured. Check that --project points at the package you want to trace.</div>'
    else:
        tree = "\n".join(_render_node(c, base, 1) for c in root.children)

    # Source-on-hover payload. Embedded mode ships the snippet map inline (so the
    # report works from file://); serve mode ships only the server base URL and
    # fetches on demand (no code in the HTML). Escape '<' so a snippet containing
    # '</script>' can't break out of the <script type="application/json"> block.
    import json
    payload = {}
    if src_url:
        payload["src_url"] = src_url
    elif snippets:
        payload["snippets"] = snippets
    ct_data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")

    return _HTML_TEMPLATE.format(
        title=_html.escape(title),
        subtitle=_html.escape(subtitle),
        raw_calls=f"{raw_calls:,}",
        collapsed_nodes=f"{collapsed_nodes:,}",
        max_depth=max_depth,
        wall=_fmt_dur(elapsed),
        collapsed="yes" if collapsed else "no",
        tree=tree,
        ct_data=ct_data,
        tooltip_js=_TOOLTIP_JS,
    )
