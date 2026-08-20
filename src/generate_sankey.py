#!/usr/bin/env python3
"""
Generate an interactive Sankey diagram of the supplements data pipeline.

Recomputes every stage count from the repository's current data and writes a
self-contained HTML page to docs/index.html, suitable for serving with
GitHub Pages (Settings -> Pages -> deploy from branch -> /docs).

Stages: Google search links -> downloaded & LLM-processed -> menopause screen
-> deduplication -> supplement screen -> primary supplement category.

Inputs:
  data/supplements.csv               search links with platform source
  data/supplements_search_terms.txt  search terms (count shown in notes)
  data/supplements_LLM_results.xlsx  joined LLM output
Dependencies: clean_supplements.py (category coding), analyze_data.py
(duplicate removal).
"""

from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

from analyze_data import remove_duplicates
from clean_supplements import UNMATCHED, split_supplements, status_category

# ---------------------------------------------------------------------------
# Diagram constants
# ---------------------------------------------------------------------------
DIAGRAM_HEIGHT = 630   # px used by the tallest column
NODE_WIDTH = 14
MIN_NODE_H = 4         # visibility floor for tiny nodes
COLUMN_X = [150, 340, 530, 720, 910, 1100]
VIEWBOX_W = 1395

ALLOWED_PLATFORMS = ["youtube", "tiktok", "facebook", "instagram"]
PLATFORM_CLASS = {"instagram": "ig", "tiktok": "tt", "youtube": "yt", "facebook": "fb"}
PLATFORM_LABEL = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube", "facebook": "Facebook"}

# short display names for the coding framework's long category names
CATEGORY_SHORT = {
    UNMATCHED: "Manual review queue",
    "Vitamins and minerals": "Vitamins & minerals",
    "Branded menopause or symptom-targeted formulations": "Branded menopause formulations",
    "Hormone therapies": "Hormone therapies",
    "Protein, amino acids, creatine, body-composition and sports/performance supplements":
        "Protein, amino acids & creatine",
    "Herbals, botanicals and phytoestrogenic products": "Herbals & botanicals",
    "Gut/microbiome products, including probiotics, prebiotics, postbiotics, symbiotics and fibre":
        "Gut / microbiome",
    "Other, vague, ambiguous or non-classifiable terms": "Vague or non-classifiable",
    "Fatty acids and oils": "Fatty acids & oils",
    "Prescription and over-the-counter medications": "Prescription & OTC medicines",
}


def fmt(n):
    return f"{n:,}"


def primary_category(supplements_value):
    """Most frequent status category among a post's supplement terms.

    Ties resolve away from the manual-review flag so a post with one matched
    and one unmatched term is categorised by the matched one.
    """
    terms = split_supplements(supplements_value)
    if not terms:
        return None
    cats = Counter(status_category(t) for t in terms)
    ranked = sorted(cats.items(), key=lambda kv: (-kv[1], kv[0] == UNMATCHED))
    return ranked[0][0]


def compute_counts():
    """Recompute every pipeline stage from the current data files."""
    links = pd.read_csv("data/supplements.csv")
    link_counts = links["source"].str.lower().value_counts().to_dict()

    n_terms = sum(1 for line in open("data/supplements_search_terms.txt") if line.strip())

    df = pd.read_excel("data/supplements_LLM_results.xlsx")
    df["extractor"] = df["extractor"].str.lower()
    df = df[df["extractor"].isin(ALLOWED_PLATFORMS)].copy()
    processed_counts = df["extractor"].value_counts().to_dict()

    meno = df[df["menopause"] == True].copy()
    uniq = remove_duplicates(meno)

    has_supp = uniq["supplements"].apply(lambda v: len(split_supplements(v)) > 0)
    supp_posts = uniq[has_supp]
    cat_counts = supp_posts["supplements"].apply(primary_category).value_counts().to_dict()

    # platforms ordered by link volume
    platforms = sorted(link_counts, key=link_counts.get, reverse=True)
    return dict(
        n_terms=n_terms,
        platforms=platforms,
        link_counts=link_counts,
        processed_counts={p: processed_counts.get(p, 0) for p in platforms},
        total_links=int(sum(link_counts.values())),
        total_processed=len(df),
        n_meno=len(meno), n_not_meno=len(df) - len(meno),
        n_uniq=len(uniq), n_dupes=len(meno) - len(uniq),
        n_supp=len(supp_posts), n_no_supp=len(uniq) - len(supp_posts),
        categories=sorted(cat_counts.items(), key=lambda kv: -kv[1]),
    )


def build_layout(c):
    """Node positions and flow ribbons, proportional to post counts."""
    k = DIAGRAM_HEIGHT / c["total_links"]

    def h(v):
        return max(v * k, MIN_NODE_H)

    nodes, flows = {}, []

    def add(nid, col, y, val, cls, label):
        nodes[nid] = dict(col=col, x=COLUMN_X[col], y=y, val=val, h=h(val), cls=cls, label=label)

    y = 70
    for p in c["platforms"]:
        val = c["link_counts"][p]
        add(p, 0, y, val, PLATFORM_CLASS.get(p, "kept"), PLATFORM_LABEL.get(p, p.title()))
        y += h(val) + 10

    add("proc", 1, 70, c["total_processed"], "kept", "Downloaded & LLM-processed")
    add("fail", 1, 70 + c["total_processed"] * k + 40,
        c["total_links"] - c["total_processed"], "sink", "Not retrievable / not processed")
    add("meno", 2, 70, c["n_meno"], "kept", "Menopause-targeted")
    add("notmeno", 2, 70 + c["n_meno"] * k + 40, c["n_not_meno"], "sink", "Not menopause-targeted")
    add("uniq", 3, 70, c["n_uniq"], "kept", "Unique posts")
    add("dupe", 3, 70 + c["n_uniq"] * k + 40, c["n_dupes"], "sink", "Cross-platform duplicates")
    add("supp", 4, 70, c["n_supp"], "kept", "Mentions supplements")
    add("nosupp", 4, 70 + c["n_supp"] * k + 40, c["n_no_supp"], "sink2", "No supplements mentioned")

    y = 70
    for i, (name, val) in enumerate(c["categories"]):
        add(f"cat{i}", 5, y, val, "kept", CATEGORY_SHORT.get(name, name))
        y += h(val) + 9

    for p in c["platforms"]:
        done = c["processed_counts"][p]
        flows.append((p, "proc", done, PLATFORM_CLASS.get(p, "kept")))
        flows.append((p, "fail", c["link_counts"][p] - done, "sink"))
    flows += [("proc", "meno", c["n_meno"], "kept"), ("proc", "notmeno", c["n_not_meno"], "sink"),
              ("meno", "uniq", c["n_uniq"], "kept"), ("meno", "dupe", c["n_dupes"], "sink"),
              ("uniq", "supp", c["n_supp"], "kept"), ("uniq", "nosupp", c["n_no_supp"], "sink2")]
    for i, (_, val) in enumerate(c["categories"]):
        flows.append(("supp", f"cat{i}", val, "kept"))

    # ribbon geometry: outgoing/incoming flows stack top-down at each node
    out_off = {nid: 0.0 for nid in nodes}
    in_off = {nid: 0.0 for nid in nodes}
    paths = []
    for src in nodes:
        for s, d, v, cls in sorted((f for f in flows if f[0] == src),
                                   key=lambda f: nodes[f[1]]["y"]):
            sn, dn = nodes[s], nodes[d]
            sw = v * k * (sn["h"] / (sn["val"] * k))   # rescale into clamped nodes
            dw = v * k * (dn["h"] / (dn["val"] * k))
            sy, ty = sn["y"] + out_off[s], dn["y"] + in_off[d]
            out_off[s] += sw
            in_off[d] += dw
            x0, x1 = sn["x"] + NODE_WIDTH, dn["x"]
            mx = (x0 + x1) / 2
            d_attr = (f"M{x0:.1f},{sy:.1f} C{mx:.1f},{sy:.1f} {mx:.1f},{ty:.1f} {x1:.1f},{ty:.1f} "
                      f"L{x1:.1f},{ty + dw:.1f} C{mx:.1f},{ty + dw:.1f} {mx:.1f},{sy + sw:.1f} "
                      f"{x0:.1f},{sy + sw:.1f} Z")
            paths.append(dict(d=d_attr, cls=cls, src=s, dst=d, val=v))
    return nodes, paths


def build_svg(c, nodes, paths):
    height = max(n["y"] + n["h"] for n in nodes.values()) + 40
    stage_headers = [
        ("Google search", f"{fmt(c['total_links'])} links", 0),
        ("Download + LLM", f"{fmt(c['total_processed'])} kept", 1),
        ("Menopause screen", f"{fmt(c['n_meno'])} kept", 2),
        ("Deduplication", f"{fmt(c['n_uniq'])} kept", 3),
        ("Supplement screen", f"{fmt(c['n_supp'])} kept", 4),
        ("Primary category", f"{len(c['categories'])} groups", 5),
    ]
    s = [f'<svg viewBox="0 0 {VIEWBOX_W} {height:.0f}" role="img" aria-labelledby="sankey-title" '
         f'font-family="\'IBM Plex Sans\', system-ui, sans-serif">',
         f'<title id="sankey-title">Sankey diagram: {fmt(c["total_links"])} Google search links '
         f'filtered to {fmt(c["n_supp"])} menopause posts mentioning supplements, divided into '
         f'{len(c["categories"])} supplement categories</title>']

    for name, sub, col in stage_headers:
        tx = COLUMN_X[col] if col in (0, 5) else COLUMN_X[col] + NODE_WIDTH / 2
        anchor = "start" if col in (0, 5) else "middle"
        s.append(f'<text x="{tx}" y="28" text-anchor="{anchor}" class="stage">{name.upper()}</text>')
        s.append(f'<text x="{tx}" y="46" text-anchor="{anchor}" class="stagecount">{sub}</text>')

    for p in paths:
        sv, dv = nodes[p["src"]], nodes[p["dst"]]
        pct = p["val"] / sv["val"] * 100
        tip = f'{sv["label"]} → {dv["label"]}: {fmt(p["val"])} posts ({pct:.1f}%)'
        s.append(f'<path d="{p["d"]}" class="flow f-{p["cls"]}" data-tip="{tip}"/>')

    for n in nodes.values():
        tip = f'{n["label"]}: {fmt(n["val"])} ({n["val"] / c["total_links"] * 100:.1f}% of search links)'
        s.append(f'<rect x="{n["x"]}" y="{n["y"]:.1f}" width="{NODE_WIDTH}" height="{n["h"]:.1f}" '
                 f'rx="2" class="node n-{n["cls"]}" data-tip="{tip}"/>')

    for p in c["platforms"]:
        n = nodes[p]
        cy = n["y"] + n["h"] / 2
        s.append(f'<text x="{n["x"] - 10}" y="{cy - 3:.1f}" text-anchor="end" class="nlabel">{n["label"]}</text>')
        s.append(f'<text x="{n["x"] - 10}" y="{cy + 14:.1f}" text-anchor="end" class="ncount">{fmt(n["val"])}</text>')

    side_sinks = {"fail": ["not retrievable or", "not processed"],
                  "notmeno": ["not menopause-", "targeted"],
                  "dupe": ["cross-platform", "duplicates"]}
    for nid, lines in side_sinks.items():
        n = nodes[nid]
        x = n["x"] + NODE_WIDTH + 8
        cy = n["y"] + min(n["h"] / 2, 30)
        s.append(f'<text x="{x}" y="{cy - 2:.1f}" class="ncount">{fmt(n["val"])}</text>')
        for i, line in enumerate(lines):
            s.append(f'<text x="{x}" y="{cy + 13 + i * 13:.1f}" class="nlabel-sm">{line}</text>')

    n = nodes["nosupp"]   # labelled below the node, clear of the category fan
    cx = n["x"] + NODE_WIDTH / 2
    yb = n["y"] + n["h"] + 18
    s.append(f'<text x="{cx}" y="{yb:.1f}" text-anchor="middle" class="ncount">{fmt(n["val"])}</text>')
    s.append(f'<text x="{cx}" y="{yb + 14:.1f}" text-anchor="middle" class="nlabel-sm">no supplements mentioned</text>')
    s.append(f'<text x="{cx}" y="{yb + 27:.1f}" text-anchor="middle" class="nlabel-sm">(symptom &amp; experience posts)</text>')

    for i in range(len(c["categories"])):
        n = nodes[f"cat{i}"]
        cy = n["y"] + n["h"] / 2 + 4
        s.append(f'<text x="{n["x"] + NODE_WIDTH + 8}" y="{cy:.1f}" class="nlabel">'
                 f'<tspan class="ncount-inline">{fmt(n["val"])}</tspan>  {n["label"]}</text>')
    s.append("</svg>")
    return "\n".join(s)


def build_html(c, svg_str, paths, nodes):
    today = datetime.now().strftime("%-d %B %Y")
    min_visible = int(MIN_NODE_H / (DIAGRAM_HEIGHT / c["total_links"]))

    flow_rows = "\n".join(
        f'<tr><td>{nodes[p["src"]]["label"]}</td><td>{nodes[p["dst"]]["label"]}</td>'
        f'<td class="num">{fmt(p["val"])}</td>'
        f'<td class="num">{p["val"] / nodes[p["src"]]["val"] * 100:.1f}%</td></tr>'
        for p in paths)

    stage_rows = f"""
<tr><td>Google search</td><td>Daily scrape across {c['n_terms']} search terms; links from YouTube, TikTok, Facebook, Instagram</td><td class="num">—</td><td class="num">{fmt(c['total_links'])}</td><td class="num">—</td></tr>
<tr><td>Download + LLM</td><td>Video retrieved by yt-dlp and processed by Nemotron&nbsp;3 Nano Omni; drops unretrievable links (most Instagram), audio-only files and processing failures</td><td class="num">{fmt(c['total_links'])}</td><td class="num">{fmt(c['total_processed'])}</td><td class="num">{fmt(c['total_links'] - c['total_processed'])}</td></tr>
<tr><td>Menopause screen</td><td>LLM field <em>menopause</em> = True (post targets the supplement toward menopause-related symptoms)</td><td class="num">{fmt(c['total_processed'])}</td><td class="num">{fmt(c['n_meno'])}</td><td class="num">{fmt(c['n_not_meno'])}</td></tr>
<tr><td>Deduplication</td><td>Same normalised title (≥ 15 chars) and duration across platforms; copy with most views kept</td><td class="num">{fmt(c['n_meno'])}</td><td class="num">{fmt(c['n_uniq'])}</td><td class="num">{fmt(c['n_dupes'])}</td></tr>
<tr><td>Supplement screen</td><td>Post names at least one supplement; the {fmt(c['n_no_supp'])} without are retained separately as symptom-and-experience posts</td><td class="num">{fmt(c['n_uniq'])}</td><td class="num">{fmt(c['n_supp'])}</td><td class="num">{fmt(c['n_no_supp'])}</td></tr>
<tr><td>Primary category</td><td>Modal status category of the post's supplement terms, per the team's nine-category coding framework; unmatched terms go to the manual review queue</td><td class="num">{fmt(c['n_supp'])}</td><td class="num">{fmt(c['n_supp'])}</td><td class="num">—</td></tr>
"""

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Menopause Supplement Pipeline</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Serif:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root {{
  --bg: #FAF9F7; --surface: #FFFFFF; --ink: #26241F; --ink-2: #5C574D; --ink-3: #8A8478;
  --line: #E6E2DA; --accent: #C8892F;
  --c-ig: #B04FC8; --c-tt: #1E9E9E; --c-yt: #CC4B43; --c-fb: #4472CA;
  --c-kept: #C8892F; --c-sink: #A6ADB5; --c-sink2: #7A8794;
  --flow-op: 0.45; --flow-op-hover: 0.72;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #161A20; --surface: #1D222A; --ink: #E8E6E1; --ink-2: #A9A498; --ink-3: #7B766B;
    --line: #2C323C; --accent: #BC842E;
    --c-ig: #B85BD0; --c-tt: #21A8A8; --c-yt: #D5564C; --c-fb: #5581DB;
    --c-kept: #BC842E; --c-sink: #59616C; --c-sink2: #76828F;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  background: var(--bg); color: var(--ink); margin: 0;
  font-family: 'IBM Plex Sans', system-ui, sans-serif; line-height: 1.55;
}}
.wrap {{ max-width: 1180px; margin: 0 auto; padding: 40px 28px 64px; }}
header {{ margin-bottom: 8px; }}
h1 {{
  font-family: 'IBM Plex Serif', Georgia, serif; font-weight: 600;
  font-size: 1.9rem; margin: 0 0 6px; text-wrap: balance;
}}
.meta {{ color: var(--ink-2); font-size: 0.95rem; margin: 0 0 4px; max-width: 68ch; }}
.meta strong {{ color: var(--ink); font-weight: 600; }}
.figure {{ overflow-x: auto; margin: 20px 0 8px; }}
.figure svg {{ min-width: 980px; width: 100%; height: auto; display: block; }}
.stage {{ font-size: 13px; font-weight: 600; letter-spacing: 0.06em; fill: var(--ink); }}
.stagecount {{ font-size: 12.5px; font-family: 'IBM Plex Mono', monospace; fill: var(--ink-2); }}
.nlabel {{ font-size: 13px; fill: var(--ink); }}
.nlabel-sm {{ font-size: 12px; fill: var(--ink-2); }}
.ncount {{ font-size: 13px; font-weight: 500; font-family: 'IBM Plex Mono', monospace; fill: var(--ink); }}
.ncount-inline {{ font-family: 'IBM Plex Mono', monospace; font-weight: 500; }}
.flow {{ fill-opacity: var(--flow-op); transition: fill-opacity 120ms; }}
@media (prefers-reduced-motion: reduce) {{ .flow {{ transition: none; }} }}
.flow:hover {{ fill-opacity: var(--flow-op-hover); }}
.f-ig {{ fill: var(--c-ig); }} .f-tt {{ fill: var(--c-tt); }}
.f-yt {{ fill: var(--c-yt); }} .f-fb {{ fill: var(--c-fb); }}
.f-kept {{ fill: var(--c-kept); }} .f-sink {{ fill: var(--c-sink); }} .f-sink2 {{ fill: var(--c-sink2); }}
.node {{ stroke: var(--bg); stroke-width: 1; }}
.n-ig {{ fill: var(--c-ig); }} .n-tt {{ fill: var(--c-tt); }}
.n-yt {{ fill: var(--c-yt); }} .n-fb {{ fill: var(--c-fb); }}
.n-kept {{ fill: var(--c-kept); }} .n-sink {{ fill: var(--c-sink); }} .n-sink2 {{ fill: var(--c-sink2); }}
#tooltip {{
  position: fixed; pointer-events: none; display: none; z-index: 10;
  background: var(--surface); color: var(--ink); border: 1px solid var(--line);
  border-radius: 6px; padding: 7px 11px; font-size: 0.85rem;
  box-shadow: 0 4px 14px rgba(0,0,0,0.14); max-width: 320px;
}}
.notes {{ margin-top: 28px; }}
h2 {{
  font-family: 'IBM Plex Serif', Georgia, serif; font-weight: 600;
  font-size: 1.15rem; margin: 32px 0 10px;
}}
table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
th, td {{ text-align: left; padding: 7px 14px 7px 0; border-bottom: 1px solid var(--line); vertical-align: top; }}
th {{ font-size: 0.78rem; letter-spacing: 0.05em; text-transform: uppercase; color: var(--ink-2); font-weight: 600; }}
td.num, th.num {{ text-align: right; font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; white-space: nowrap; }}
.tablewrap {{ overflow-x: auto; }}
details {{ margin-top: 18px; }}
summary {{ cursor: pointer; color: var(--ink-2); font-size: 0.92rem; }}
summary:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
.fineprint {{ color: var(--ink-3); font-size: 0.82rem; margin-top: 26px; max-width: 78ch; }}
.fineprint code {{ font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; }}
</style>
</head>
<body>
<div class="wrap">
<header>
<h1>Menopause Supplement Pipeline</h1>
<p class="meta">How <strong>{fmt(c["total_links"])}</strong> Google search results become <strong>{fmt(c["n_supp"])}</strong> unique menopause-targeted posts that mention supplements, divided into {len(c["categories"])} product categories. Counts as of {today}.</p>
</header>

<div class="figure">
{svg_str}
</div>
<div id="tooltip" role="status"></div>

<div class="notes">
<h2>Stage rules</h2>
<div class="tablewrap">
<table>
<thead><tr><th>Stage</th><th>Rule</th><th class="num">In</th><th class="num">Kept</th><th class="num">Removed</th></tr></thead>
<tbody>
{stage_rows}
</tbody>
</table>
</div>

<details>
<summary>All flows as a table</summary>
<div class="tablewrap">
<table>
<thead><tr><th>From</th><th>To</th><th class="num">Posts</th><th class="num">% of source</th></tr></thead>
<tbody>
{flow_rows}
</tbody>
</table>
</div>
</details>

<p class="fineprint">Bands are proportional to post counts; nodes smaller than {min_visible} posts are drawn at a {MIN_NODE_H}px minimum so they stay visible. Category assignment gives each post the most frequent status category among its supplement terms (ties resolved away from the manual-review flag). Generated by <code>src/generate_sankey.py</code> from <code>data/supplements.csv</code> (search links), <code>data/supplements_LLM_results.xlsx</code> (LLM output), <code>src/clean_supplements.py</code> (category coding) and <code>src/analyze_data.py</code> (platform filter and deduplication).</p>
</div>

<script>
(function () {{
  var tip = document.getElementById('tooltip');
  document.querySelectorAll('[data-tip]').forEach(function (el) {{
    el.addEventListener('mousemove', function (e) {{
      tip.textContent = el.getAttribute('data-tip');
      tip.style.display = 'block';
      var x = e.clientX + 14, y = e.clientY + 12;
      if (x + 330 > window.innerWidth) x = e.clientX - 330;
      tip.style.left = x + 'px'; tip.style.top = y + 'px';
    }});
    el.addEventListener('mouseleave', function () {{ tip.style.display = 'none'; }});
  }});
}})();
</script>
</body>
</html>
'''


def main():
    counts = compute_counts()
    nodes, paths = build_layout(counts)
    svg_str = build_svg(counts, nodes, paths)
    html = build_html(counts, svg_str, paths, nodes)
    out = Path("docs/index.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)
    print(f"Saved {out} ({counts['total_links']:,} links -> {counts['n_supp']:,} supplement posts)")


if __name__ == "__main__":
    main()
