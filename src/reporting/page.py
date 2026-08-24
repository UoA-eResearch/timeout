#!/usr/bin/env python3
"""HTML scaffolding for the verification report.

Self-contained by design: no external stylesheets, scripts, fonts or images, so
the report opens from a file share, survives being emailed, and prints without
a network. Theme-aware in all three states -- explicit light, explicit dark, and
the OS default -- because a report that is unreadable in dark mode is a report
half the team will not read.
"""

from __future__ import annotations

import html

CSS = """
:root{
  --surface:#fcfcfb; --panel:#ffffff; --ink:#0b0b0b; --ink-soft:#52514e;
  --ink-faint:#78776f; --rule:#e4e3df; --accent:#2a78d6; --accent-soft:#eaf2fd;
  --good:#1a7f4f; --warn:#a9741a; --bad:#c0392f;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:"Public Sans",ui-sans-serif,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
  --serif:"Newsreader",Georgia,"Times New Roman",serif;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --surface:#1a1a19; --panel:#232322; --ink:#ffffff; --ink-soft:#c3c2b7;
    --ink-faint:#94938a; --rule:#3a3a37; --accent:#3987e5; --accent-soft:#16273c;
    --good:#4bbd84; --warn:#d8a33c; --bad:#e66767;
  }
}
:root[data-theme="dark"]{
  --surface:#1a1a19; --panel:#232322; --ink:#ffffff; --ink-soft:#c3c2b7;
  --ink-faint:#94938a; --rule:#3a3a37; --accent:#3987e5; --accent-soft:#16273c;
  --good:#4bbd84; --warn:#d8a33c; --bad:#e66767;
}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.62;-webkit-font-smoothing:antialiased}
.wrap{max-width:980px;margin:0 auto;padding:0 24px 96px}
h1{font-family:var(--serif);font-size:2.45rem;font-weight:600;line-height:1.12;
  margin:0 0 10px;letter-spacing:-.015em;text-wrap:balance}
h2{font-family:var(--serif);font-size:1.6rem;font-weight:600;margin:56px 0 4px;
  padding-top:18px;border-top:1px solid var(--rule);text-wrap:balance;letter-spacing:-.01em}
h3{font-family:var(--serif);font-size:1.14rem;font-weight:600;margin:32px 0 6px;color:var(--ink)}
h2 .num{color:var(--ink-faint);font-weight:400;margin-right:10px}
p{margin:10px 0}
.lede{color:var(--ink-soft);font-size:1.08rem;margin-bottom:4px;max-width:62ch;
  text-wrap:pretty}
.muted{color:var(--ink-soft)}
.small{font-size:.87rem}
code,kbd{font-family:var(--mono);font-size:.87em;background:var(--accent-soft);
  padding:1px 5px;border-radius:4px}
a{color:var(--accent)}
:is(a,summary,details):focus-visible{outline:2px solid var(--accent);
  outline-offset:2px;border-radius:3px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
header.masthead{padding:56px 0 26px}
.eyebrow{font-family:var(--mono);font-size:.76rem;letter-spacing:.14em;
  text-transform:uppercase;color:var(--ink-faint);margin-bottom:14px}

.panel{background:var(--panel);border:1px solid var(--rule);border-radius:10px;
  padding:18px 20px;margin:18px 0}
.panel h3{margin-top:0}

.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:2px 22px;
  font-size:.86rem}
.kv div{padding:7px 0;border-bottom:1px solid var(--rule);display:flex;
  flex-direction:column;gap:2px;min-width:0}
.kv span:first-child{color:var(--ink-faint);font-size:.76rem;text-transform:uppercase;
  letter-spacing:.05em}
.kv span:last-child{font-family:var(--mono);font-size:.81rem;overflow-wrap:anywhere;
  line-height:1.45}

.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:20px 0}
.tile{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:14px 16px}
.tile .n{font-family:var(--serif);font-size:1.86rem;font-weight:600;
  letter-spacing:-.02em;line-height:1.12;font-variant-numeric:tabular-nums}
.tile .l{font-size:.8rem;color:var(--ink-soft);margin-top:3px}
.tile .s{font-size:.76rem;color:var(--ink-faint);margin-top:5px}

figure{margin:22px 0 10px}
figcaption{font-size:.86rem;color:var(--ink-soft);margin:0 0 10px}
figcaption b{color:var(--ink);font-weight:620}
.figbox{background:var(--panel);border:1px solid var(--rule);border-radius:10px;
  padding:14px 8px 8px;overflow-x:auto}
.fig svg{width:100%;height:auto;display:block}
.fig-dark{display:none}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]) .fig-light{display:none}
  :root:not([data-theme="light"]) .fig-dark{display:block}
}
:root[data-theme="dark"] .fig-light{display:none}
:root[data-theme="dark"] .fig-dark{display:block}

details{margin:8px 0 0;border-top:1px solid var(--rule);padding-top:8px}
summary{cursor:pointer;font-size:.83rem;color:var(--ink-soft);
  font-family:var(--mono);letter-spacing:.02em}
summary:hover{color:var(--accent)}
.tablewrap{overflow-x:auto;margin-top:10px}
table{border-collapse:collapse;width:100%;font-size:.84rem}
th,td{text-align:left;padding:6px 12px 6px 0;border-bottom:1px solid var(--rule);
  vertical-align:top}
th{color:var(--ink-soft);font-weight:600;font-size:.78rem;text-transform:uppercase;
  letter-spacing:.05em;white-space:nowrap}
td.num,th.num{text-align:right;font-family:var(--mono);font-size:.82rem;
  font-variant-numeric:tabular-nums}
tbody tr:hover{background:var(--accent-soft)}

.check{display:flex;gap:12px;align-items:flex-start;padding:11px 0;
  border-bottom:1px solid var(--rule)}
.check:last-child{border-bottom:0}
.badge{font-family:var(--mono);font-size:.7rem;font-weight:700;letter-spacing:.06em;
  padding:3px 8px;border-radius:5px;white-space:nowrap;margin-top:2px}
.badge.pass{background:var(--good);color:#fff}
.badge.warn{background:var(--warn);color:#fff}
.badge.fail{background:var(--bad);color:#fff}
.badge.info{background:var(--rule);color:var(--ink-soft)}
.check .body{min-width:0}
.check .t{font-weight:600;font-size:.93rem}
.check .d{font-size:.86rem;color:var(--ink-soft)}

.flow{display:flex;flex-direction:column;gap:0;margin:20px 0}
.flow .step{display:flex;align-items:stretch;gap:0}
.flow .box{background:var(--panel);border:1px solid var(--rule);border-radius:9px;
  padding:11px 16px;flex:1;min-width:0}
.flow .box .n{font-family:var(--mono);font-size:1.05rem;font-weight:600;
  font-variant-numeric:tabular-nums}
.flow .box .l{font-size:.83rem;color:var(--ink-soft)}
.flow .out{width:250px;margin-left:22px;padding:11px 14px;border-left:2px solid var(--rule);
  font-size:.8rem;color:var(--ink-faint);align-self:center}
.flow .arrow{height:16px;margin-left:26px;border-left:2px solid var(--rule)}
@media(max-width:700px){.flow .out{display:none}}

blockquote{margin:14px 0;padding:10px 16px;border-left:3px solid var(--accent);
  background:var(--panel);border-radius:0 8px 8px 0;font-size:.92rem;color:var(--ink-soft)}
blockquote p{margin:4px 0}
.quote{font-family:var(--mono);font-size:.79rem;color:var(--ink-soft);
  display:block;margin-top:3px;padding-left:9px;border-left:2px solid var(--rule)}
.toc{columns:2;column-gap:34px;font-size:.9rem;margin:6px 0 0;padding:0;list-style:none}
.toc li{padding:3px 0;break-inside:avoid}
.toc a{text-decoration:none;color:var(--ink-soft)}
.toc a:hover{color:var(--accent)}
.toc .n{font-family:var(--mono);color:var(--ink-faint);margin-right:8px;font-size:.82rem}
footer{margin-top:64px;padding-top:20px;border-top:1px solid var(--rule);
  font-size:.83rem;color:var(--ink-faint)}
@media print{
  .fig-dark{display:none!important}.fig-light{display:block!important}
  body{background:#fff;color:#000}details{display:block}details[open] summary{display:none}
  h2{break-before:auto;break-after:avoid}figure{break-inside:avoid}
}
"""


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def page(title: str, body: str, subtitle: str = "") -> str:
    return (
        f"<title>{esc(title)}</title>\n"
        f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500;6..72,600&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">\n'
        f"<style>{CSS}</style>\n"
        f'<div class="wrap">{body}</div>'
    )


def tiles(items: list[tuple[str, str, str]]) -> str:
    cells = "".join(
        f'<div class="tile"><div class="n">{esc(n)}</div>'
        f'<div class="l">{esc(l)}</div>'
        + (f'<div class="s">{esc(s)}</div>' if s else "")
        + "</div>"
        for n, l, s in items
    )
    return f'<div class="tiles">{cells}</div>'


def table(headers: list[str], rows: list[list], numeric: set[int] | None = None,
          raw_cols: set[int] | None = None) -> str:
    numeric = numeric or set()
    raw_cols = raw_cols or set()
    head = "".join(
        f'<th class="num">{esc(h)}</th>' if i in numeric else f"<th>{esc(h)}</th>"
        for i, h in enumerate(headers)
    )
    body = ""
    for row in rows:
        cells = ""
        for i, cell in enumerate(row):
            text = cell if i in raw_cols else esc(cell)
            cells += f'<td class="num">{text}</td>' if i in numeric else f"<td>{text}</td>"
        body += f"<tr>{cells}</tr>"
    return f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def figure(caption_bold: str, caption: str, svg: str, data_table: str = "",
           note: str = "") -> str:
    """A chart, its reading, and the numbers behind it.

    The data table is always available: identity is never carried by colour
    alone, and a researcher checking a bar needs the figure it stands for.
    """
    details = (f"<details><summary>show the numbers behind this chart</summary>"
               f"{data_table}</details>") if data_table else ""
    note_html = f'<p class="small muted">{note}</p>' if note else ""
    return (
        f"<figure><figcaption><b>{esc(caption_bold)}</b> {esc(caption)}</figcaption>"
        f'<div class="figbox">{svg}</div>{note_html}{details}</figure>'
    )


def checks(items: list[tuple[str, str, str]]) -> str:
    """(status, title, detail) where status is pass|warn|fail|info."""
    rows = "".join(
        f'<div class="check"><span class="badge {s}">{s.upper()}</span>'
        f'<div class="body"><div class="t">{esc(t)}</div>'
        f'<div class="d">{d}</div></div></div>'
        for s, t, d in items
    )
    return f'<div class="panel">{rows}</div>'


def flow(steps: list[tuple[str, str, str]]) -> str:
    """(count, label, note) rendered as a PRISMA-style attrition diagram."""
    out = '<div class="flow">'
    for i, (count, label, note) in enumerate(steps):
        if i:
            out += '<div class="arrow"></div>'
        out += ('<div class="step"><div class="box">'
                f'<div class="n">{esc(count)}</div><div class="l">{esc(label)}</div></div>'
                + (f'<div class="out">{esc(note)}</div>' if note else "")
                + "</div>")
    return out + "</div>"


def kv(pairs: list[tuple[str, str]]) -> str:
    body = "".join(f"<div><span>{esc(k)}</span><span>{esc(v)}</span></div>" for k, v in pairs)
    return f'<div class="kv">{body}</div>'
