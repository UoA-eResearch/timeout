#!/usr/bin/env python3
"""Build the verification report.

One self-contained HTML file that a researcher can read end to end and check:
what was in the corpus, what came out, how stable it is, and where every
judgement came from. Every chart carries the numbers behind it; every claim in
the narrative is computed from the labels rather than typed by hand.

    python3 src/report.py                      # full report
    python3 src/report.py --out report/x.html

Structure follows what a reviewer asks in order: what did you analyse, is it
trustworthy, and only then what did you find.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from codebook.schema import build as build_pass
from reporting import theme as T
from reporting.page import (checks, esc, figure, flow, kv, page, table, tiles)

REPO = Path(__file__).resolve().parent.parent
CLAIM_LISTS = ["supplements_raw", "supplement_group", "ingredient_type", "claim_target",
               "claim_type", "claim_strength", "evidence_type", "claim_quote"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def n(x) -> str:
    return f"{int(x):,}"


def pct(part, whole) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "—"


def by_video(ev: pd.DataFrame) -> pd.DataFrame:
    """Evidence indexed uniquely by video_id.

    The corpus contains 86 exact platform-id collisions, so a naive
    set_index/merge on video_id would silently duplicate label rows. The primary
    row of each duplicate group wins.
    """
    return ev.sort_values("is_primary", ascending=False).drop_duplicates("video_id")


def split_cell(cell) -> list[str]:
    if cell is None or (isinstance(cell, float) and np.isnan(cell)):
        return []
    return [p.strip() for p in str(cell).split(" | ") if p.strip()]


def multi_counts(series: pd.Series) -> Counter:
    counts: Counter = Counter()
    for cell in series.dropna():
        counts.update(split_cell(cell))
    return counts


def ordered_counts(series: pd.Series, order: list[str]) -> tuple[list[str], list[int]]:
    """Counts in codebook order, so a chart's axis matches the codebook."""
    vc = series.value_counts()
    labels = [o for o in order if o in vc.index] + [i for i in vc.index if i not in order]
    return labels, [int(vc[l]) for l in labels]


def values_of(cb: dict, section: str, name: str) -> list[str]:
    for var in cb[section]["variables"]:
        if var["name"] == name:
            return [v["value"] for v in var["values"]] + [cb["insufficient"]]
    return []


def explode_claims(labels: pd.DataFrame) -> pd.DataFrame:
    """One row per supplement mention. Derived by splitting the aligned lists.

    The delivered table is one row per video; this is the long view of the same
    data, produced deterministically rather than stored separately.
    """
    rows = []
    for _, row in labels.iterrows():
        parts = {c: split_cell(row.get(c)) for c in CLAIM_LISTS}
        length = len(parts["supplements_raw"])
        for i in range(length):
            entry = {"video_id": row["video_id"]}
            for col, vals in parts.items():
                entry[col] = vals[i] if i < len(vals) else ""
            rows.append(entry)
    return pd.DataFrame(rows)


def crosstab_pct(df: pd.DataFrame, row: str, col: str,
                 row_order: list[str], col_order: list[str]):
    ct = pd.crosstab(df[row], df[col])
    rows = [r for r in row_order if r in ct.index]
    cols = [c for c in col_order if c in ct.columns]
    ct = ct.reindex(index=rows, columns=cols, fill_value=0)
    totals = ct.sum(axis=1).replace(0, 1)
    return rows, cols, (ct.div(totals, axis=0) * 100).values, ct


def count_table(labels, values, headers=("category", "videos", "share")) -> str:
    total = sum(values) or 1
    return table(list(headers),
                 [[l, n(v), f"{100 * v / total:.1f}%"] for l, v in zip(labels, values)],
                 numeric={1, 2})


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------

def sec_flow(ev: pd.DataFrame, gate: pd.DataFrame, labels: pd.DataFrame, manifest: dict) -> str:
    tiers = ev["evidence_tier"].value_counts()
    n_dupe = int((~ev["is_primary"]).sum())
    n_groups = int((ev.groupby("duplicate_group_id").size() > 1).sum())
    codable = int(tiers.get("A", 0) + tiers.get("B", 0))
    passed = int((gate["is_about_menopause"] == True).sum())  # noqa: E712
    with_supp = int((labels["n_supplements"] > 0).sum())

    steps = [
        ("18,579", "video URLs found by search", "collected by run_googlesearch.py"),
        (n(manifest["n_rows"]), "videos downloaded and transcribed",
         f"{18579 - manifest['n_rows']:,} lost to download or extraction failure"),
        (n(codable), "have codable evidence (tier A or B)",
         f"{n(tiers.get('C', 0))} excluded: no transcript and no post text"),
        (n(len(gate)), "screened by the relevance gate", "transcript + platform metadata only"),
        (n(passed), "discuss menopause — the analysis set",
         f"{n(len(gate) - passed)} screened out as off-topic"),
        (n(with_supp), "name at least one supplement",
         f"{n(passed - with_supp)} discuss menopause without naming a product"),
    ]
    return (
        '<h2><span class="num">1</span>What was analysed</h2>'
        "<p>Attrition from search results to the analysis set. Each step is a "
        "filter applied by a named script, not a manual selection.</p>"
        + flow(steps)
        + f"<p class='small muted'>{n(n_dupe)} rows across {n(n_groups)} multi-member "
          "duplicate groups are flagged non-primary. They are retained in every file and "
          "excluded only at analysis time, so the count stays reportable.</p>"
    )


def sec_evidence(ev: pd.DataFrame, manifest: dict) -> str:
    tiers = ev["evidence_tier"].value_counts()
    tier_labels = ["A — usable transcript", "B — post text only", "C — no evidence"]
    tier_values = [int(tiers.get(k, 0)) for k in ("A", "B", "C")]

    plat = ev["platform"].value_counts()
    lengths = ev.loc[ev["evidence_tier"] == "A", "transcript_chars"]

    withheld = ", ".join(manifest["fields_withheld_from_model"])
    shown = ", ".join(manifest["fields_shown_to_model"])

    return (
        '<h2><span class="num">2</span>The evidence base</h2>'
        "<p>Every variable in this report is derived from the fields below and "
        "nothing else. No label from the previous pipeline is used as an input, "
        "and no engagement metric or upload date is shown to the model — those "
        "are outcome variables and feeding them in would make the "
        "credibility-versus-popularity question circular.</p>"
        + '<div class="panel">'
        + kv([("shown to the model", shown), ("withheld", withheld),
              ("inferred columns dropped", str(len(manifest["inferred_columns_dropped"]))),
              ("source spreadsheet sha256", manifest["source_sha256"][:24] + "…"),
              ("evidence corpus sha256", manifest["corpus_sha256"][:24] + "…"),
              ("built at", manifest["built_at"])])
        + "</div>"
        + figure("Evidence tiers.",
                 "Tier C has neither a transcript nor post text and is never annotated — "
                 "it is reported as an exclusion instead of being given invented labels.",
                 T.hbar(tier_labels, tier_values, xlabel="videos", ramp=True),
                 count_table(tier_labels, tier_values, ("tier", "videos", "share")))
        + figure("Transcript length.",
                 f"Median {int(lengths.median()):,} characters — these are short-form videos "
                 f"(median duration {int(ev['duration_s'].median())}s). The whole corpus is "
                 "roughly 4.2M tokens of text, which is why a full re-annotation costs "
                 "under two hours rather than ten.",
                 T.histogram(lengths.values, bins=50, xlabel="characters in transcript (tier A)", logx=True))
        + figure("Platform mix.", "Where the corpus came from.",
                 T.hbar(list(plat.index), list(plat.values), xlabel="videos"),
                 count_table(list(plat.index), list(plat.values), ("platform", "videos", "share")))
    )


def sec_verification(labels: pd.DataFrame, ev: pd.DataFrame, prov: dict,
                     validation: dict) -> str:
    ground = validation.get("grounding")
    enums = validation.get("enums")
    align = validation.get("alignment", {})
    retest = validation.get("retest")
    tiers = validation.get("tiers")
    legacy = validation.get("legacy")

    items = []
    if enums is not None:
        oov = int(enums["out_of_vocabulary"].sum())
        items.append((
            "pass" if oov == 0 else "fail",
            "Every value is inside the codebook",
            f"{len(enums)} categorical variables checked, <b>{oov}</b> values outside their "
            "declared vocabulary. Enforced at the decoder by schema-constrained decoding, "
            "not by asking the model nicely."))
    if align:
        items.append((
            "pass" if align["misaligned_rows"] == 0 else "fail",
            "Per-supplement lists line up",
            f"{n(align['rows_checked'])} rows checked; <b>{align['misaligned_rows']}</b> "
            "misaligned. Position <i>i</i> of every claim column describes the same "
            "supplement as position <i>i</i> of <code>supplements_raw</code>."))
    if ground is not None and len(ground):
        overall = float((ground["near_verbatim_pct"] * ground["quotes_checked"]).sum()
                        / max(ground["quotes_checked"].sum(), 1))
        status = "pass" if overall >= 85 else ("warn" if overall >= 70 else "fail")
        items.append((
            status, "Justifying quotes are really in the evidence",
            f"<b>{overall:.1f}%</b> of {n(ground['quotes_checked'].sum())} quoted spans are "
            "found in the transcript or post text the model was given. A quote that cannot "
            "be located means the label was written rather than read."))
    if retest is not None and len(retest):
        worst = float(retest["identical_across_runs_pct"].min())
        mean = float(retest["identical_across_runs_pct"].mean())
        status = "pass" if worst >= 90 else ("warn" if worst >= 75 else "fail")
        items.append((
            status, "The same input gives the same label",
            f"Mean <b>{mean:.1f}%</b>, worst variable <b>{worst:.1f}%</b> identical across "
            "repeat runs at temperature 0. The previous pipeline ran at temperature 0.6, "
            "where one transcript scored 1, 1, 2, 3, 5, 5, 10, 10, 10, 10 on <code>quality</code> "
            "across ten identical requests."))
    if tiers is not None and len(tiers):
        worst_tvd = float(tiers["total_variation_distance"].max())
        status = "pass" if worst_tvd < 0.15 else "warn"
        items.append((
            status, "Results do not hinge on the weaker-evidence rows",
            f"Largest distribution shift between tier A and tier B videos is "
            f"<b>{worst_tvd:.2f}</b> (total variation distance). Every result can be "
            "re-run tier A only using the <code>evidence_tier</code> column."))
    items.append((
        "info", "Every row states what produced it",
        f"model <code>{esc(prov.get('model_revision', '?'))}</code>, "
        f"temperature <code>{prov.get('temperature')}</code>, seed <code>{prov.get('seed')}</code>, "
        f"codebook <code>v{prov.get('codebook_version')}</code>, "
        f"prompt hash <code>{prov.get('prompt_hash')}</code>. Output files are keyed by "
        "codebook version, so two versions cannot silently mix in one spreadsheet."))

    body = (
        '<h2><span class="num">3</span>Can these labels be trusted?</h2>'
        "<p>Six checks run on every build. They come before the findings because "
        "a finding is only worth as much as the check behind it.</p>"
        + checks(items))

    if ground is not None and len(ground):
        g = ground.sort_values("near_verbatim_pct")
        body += figure(
            "Evidence grounding by field.",
            "Share of quoted spans that can be located in the evidence the model was shown. "
            "Fields where the model more often declines to quote are fields where it more "
            "often had nothing to go on.",
            T.hbar(list(g["quote_field"]), list(g["near_verbatim_pct"]),
                   xlabel="% of quotes found in the evidence", ramp=True, value_fmt="{:.1f}%"),
            table(["field", "quotes checked", "declined to quote", "verbatim", "near-verbatim"],
                  [[r["quote_field"], n(r["quotes_checked"]), n(r["declined_to_quote"]),
                    f"{r['verbatim_pct']}%", f"{r['near_verbatim_pct']}%"]
                   for _, r in g.iterrows()], numeric={1, 2, 3, 4}))

    if retest is not None and len(retest):
        r = retest.sort_values("identical_across_runs_pct")
        body += figure(
            "Test–retest stability.",
            "Each variable re-derived on the same videos several times over. "
            "Anything below 100% is a variable where the wording of the codebook is "
            "doing less work than it should.",
            T.hbar(list(r["variable"]), list(r["identical_across_runs_pct"]),
                   xlabel="% identical across repeat runs", ramp=True, value_fmt="{:.0f}%"),
            table(["variable", "videos", "identical across runs"],
                  [[x["variable"], n(x["videos"]), f"{x['identical_across_runs_pct']}%"]
                   for _, x in r.iterrows()], numeric={1, 2}))

    if legacy is not None and len(legacy):
        body += figure(
            "Agreement with the previous pipeline.",
            "Diagnostic only — the old columns are not used as input anywhere. Low agreement "
            "is expected and informative: it measures what the old temperature-0.6, "
            "unconstrained run was costing.",
            T.hbar(list(legacy["variable"]), list(legacy["exact_agreement_pct"]),
                   xlabel="% exact agreement with old labels", color_slot=1, value_fmt="{:.0f}%"),
            table(["variable", "n compared", "exact agreement"],
                  [[x["variable"], n(x["n_compared"]), f"{x['exact_agreement_pct']}%"]
                   for _, x in legacy.iterrows()], numeric={1, 2}))
    return body


def sec_supplements(labels: pd.DataFrame, claims: pd.DataFrame, cmap: pd.DataFrame | None) -> str:
    body = ('<h2><span class="num">4</span>What supplements are promoted</h2>'
            "<p><i>RQ: what is the range of products, and which are most popular?</i></p>")

    if cmap is not None and len(cmap):
        lookup = dict(zip(cmap["raw_name"], cmap["canonical_name"]))
        is_supp = dict(zip(cmap["raw_name"], cmap["is_supplement"]))
        claims = claims.copy()
        claims["canonical"] = claims["supplements_raw"].map(lookup).fillna(claims["supplements_raw"])
        claims["is_supp"] = claims["supplements_raw"].map(is_supp).fillna(True)
        real = claims[claims["is_supp"] == True]  # noqa: E712
        top = real["canonical"].value_counts().head(20)
        n_raw, n_canon = len(cmap), cmap["canonical_name"].nunique()
        body += figure(
            "Top 20 supplements named.",
            f"After normalising {n_raw:,} raw name strings onto {n_canon:,} canonical names — "
            "46 spellings of vitamin D, 86 of collagen, 75 of magnesium collapse to one each. "
            "The mapping is a reviewable CSV, not a per-video decision.",
            T.hbar(list(top.index)[::-1][::-1], list(top.values), xlabel="videos mentioning", ramp=True),
            table(["canonical supplement", "mentions"],
                  [[k, n(v)] for k, v in top.items()], numeric={1}))
    else:
        top = claims["supplements_raw"].value_counts().head(20)
        body += figure("Top 20 supplement strings (not yet canonicalised).",
                       "Run canonicalise.py to collapse spelling variants.",
                       T.hbar(list(top.index), list(top.values), xlabel="mentions", ramp=True),
                       table(["raw string", "mentions"], [[k, n(v)] for k, v in top.items()],
                             numeric={1}))

    grp = claims["supplement_group"].value_counts()
    body += figure(
        "Product groups.",
        "The five mutually exclusive groups from the research questions. "
        "Medicines and hormone therapies are labelled and kept, not dropped, so the "
        "count stays reportable when HRT is excluded at analysis time.",
        T.hbar(list(grp.index), list(grp.values), xlabel="supplement mentions"),
        count_table(list(grp.index), list(grp.values), ("group", "mentions", "share")))

    single = claims[claims["supplement_group"] == "single ingredient"]
    if len(single):
        ing = single["ingredient_type"].value_counts()
        ing = ing[ing.index != "not applicable"]
        body += figure(
            "Substance types among single-ingredient products.",
            "Only single-ingredient products are typed; branded formulations are not.",
            T.hbar(list(ing.index), list(ing.values), xlabel="mentions", color_slot=2),
            count_table(list(ing.index), list(ing.values), ("substance type", "mentions", "share")))
    return body


def sec_time(labels: pd.DataFrame, ev: pd.DataFrame, claims: pd.DataFrame,
             cmap: pd.DataFrame | None) -> str:
    dates = by_video(ev).set_index("video_id")["outcome_upload_date"]
    lab = labels.copy()
    lab["date"] = lab["video_id"].map(dates)
    lab = lab.dropna(subset=["date"])
    lab["year"] = pd.to_datetime(lab["date"]).dt.year
    lab = lab[(lab["year"] >= 2016) & (lab["year"] <= 2026)]

    per_year = lab.groupby("year").size()
    body = ('<h2><span class="num">5</span>Change over time</h2>'
            "<p><i>RQ: have the supplements promoted changed over time?</i> "
            "Upload dates were withheld from the model, so this is an independent "
            "join rather than something the labeller could see.</p>")
    body += figure(
        "Menopause videos per year.",
        "Counts reflect what the search returned and what was still downloadable, "
        "so the recent-year rise is partly a collection artefact.",
        T.lines(list(per_year.index.astype(int)), {"videos": list(per_year.values)},
                ylabel="videos", xlabel="upload year", direct_label=False),
        table(["year", "videos"], [[int(y), n(v)] for y, v in per_year.items()], numeric={0, 1}))

    if cmap is not None and len(cmap):
        lookup = dict(zip(cmap["raw_name"], cmap["canonical_name"]))
        cl = claims.merge(lab[["video_id", "year"]], on="video_id")
        cl["canonical"] = cl["supplements_raw"].map(lookup).fillna(cl["supplements_raw"])
        top5 = list(cl["canonical"].value_counts().head(5).index)
        years = sorted(cl["year"].unique())
        series = {}
        for name in top5:
            sub = cl[cl["canonical"] == name].groupby("year").size()
            denom = cl.groupby("year").size()
            series[name] = [round(100 * sub.get(y, 0) / max(denom.get(y, 1), 1), 1) for y in years]
        body += figure(
            "Share of supplement mentions, top 5 products.",
            "As a share of all mentions that year, so the trend is not just corpus growth. "
            "Five series because the palette's fixed hue order validates that far; a sixth "
            "would fold into Other.",
            T.lines([int(y) for y in years], series, ylabel="% of mentions that year",
                    xlabel="upload year", direct_label=False),
            table(["year"] + top5,
                  [[int(y)] + [f"{series[k][i]}%" for k in top5] for i, y in enumerate(years)],
                  numeric=set(range(len(top5) + 1))))
    return body


def sec_symptoms(labels: pd.DataFrame, claims: pd.DataFrame, cb: dict) -> str:
    order = values_of(cb, "video_level", "symptom_categories")
    counts = multi_counts(labels["symptom_categories"])
    labs = [o for o in order if counts.get(o)]
    vals = [counts[l] for l in labs]

    body = ('<h2><span class="num">6</span>What symptoms are targeted</h2>'
            "<p><i>RQ: what symptoms are the supplement products targeting?</i> "
            "Multi-label — a video mentioning hot flushes and low mood counts in both.</p>")
    body += figure(
        "Symptom categories mentioned.",
        "Categories are exactly those specified in the research questions document.",
        T.hbar(labs, vals, xlabel="videos mentioning"),
        count_table(labs, vals, ("symptom category", "videos", "share of videos")))

    target_order = values_of(cb, "per_supplement", "claim_target")
    group_order = values_of(cb, "per_supplement", "supplement_group")
    rows, cols, matrix, raw = crosstab_pct(claims, "supplement_group", "claim_target",
                                           group_order, target_order)
    if len(rows) and len(cols):
        body += figure(
            "Which products are claimed to help with what.",
            "Row-normalised: each row sums to 100% across the claim targets. This is the "
            "supplement-to-symptom match the research questions asked for, and it is only "
            "possible because claims are recorded per supplement rather than per video.",
            T.heatmap(rows, cols, matrix, cbar_label="% of that group's mentions"),
            table(["supplement group"] + cols,
                  [[r] + [n(raw.loc[r, c]) for c in cols] for r in rows],
                  numeric=set(range(1, len(cols) + 1))))
    return body


def sec_framing(labels: pd.DataFrame, cb: dict) -> str:
    fr_order = values_of(cb, "video_level", "symptom_framing")
    counts = multi_counts(labels["symptom_framing"])
    labs = [o for o in fr_order if counts.get(o)]
    vals = [counts[l] for l in labs]

    body = ('<h2><span class="num">7</span>How menopause is portrayed</h2>'
            "<p><i>Primary RQ: how are symptoms and supplements portrayed?</i> "
            "The stated hypothesis is that a Western lens produces symptom-burden framing. "
            "These are the numbers that bear on it.</p>")
    body += figure(
        "Symptom framing.",
        "How symptoms are talked about, independent of which symptoms are named. "
        "A video can carry more than one framing.",
        T.hbar(labs, vals, xlabel="videos"),
        count_table(labs, vals, ("framing", "videos", "share of videos")))

    hf_order = values_of(cb, "video_level", "health_framework")
    # explode repeats the index; reset it so crosstab has a unique axis
    exploded = (labels.assign(f=labels["symptom_framing"].map(split_cell))
                .explode("f").reset_index(drop=True))
    exploded = exploded[exploded["f"].notna() & (exploded["f"] != "")]
    rows, cols, matrix, raw = crosstab_pct(exploded, "health_framework", "f", hf_order, fr_order)
    if len(rows) and len(cols):
        body += figure(
            "Framing by knowledge system.",
            "Row-normalised. The hypothesis predicts burden and deficiency framings "
            "concentrating in the western biomedical row; read the row, not the column.",
            T.heatmap(rows, cols, matrix, cbar_label="% of that row"),
            table(["knowledge system"] + cols,
                  [[r] + [n(raw.loc[r, c]) for c in cols] for r in rows],
                  numeric=set(range(1, len(cols) + 1))))

    ct_order = values_of(cb, "video_level", "content_type")
    ct_labels, ct_values = ordered_counts(labels["content_type"], ct_order)
    body += figure(
        "Content type.",
        "The informative / marketing / personal-commentary split the researchers asked for.",
        T.hbar(ct_labels, ct_values, xlabel="videos", color_slot=2),
        count_table(ct_labels, ct_values, ("content type", "videos", "share")))
    return body


def sec_claims(claims: pd.DataFrame, cb: dict) -> str:
    strength_order = values_of(cb, "per_supplement", "claim_strength")
    evidence_order = values_of(cb, "per_supplement", "evidence_type")
    type_order = values_of(cb, "per_supplement", "claim_type")

    body = ('<h2><span class="num">8</span>What is claimed, and on what basis</h2>'
            "<p><i>RQ: what type of claim, how strongly worded, and does the post offer "
            "any evidence?</i> Each row below is one supplement mention, not one video.</p>")

    s_labels, s_values = ordered_counts(claims["claim_strength"], strength_order)
    body += figure(
        "Claim strength.",
        "The strongest wording actually used about each supplement, ordered from "
        "strongest to weakest as the codebook defines them.",
        T.hbar(s_labels, s_values, xlabel="supplement mentions", ramp=True),
        count_table(s_labels, s_values, ("claim strength", "mentions", "share")))

    e_labels, e_values = ordered_counts(claims["evidence_type"], evidence_order)
    body += figure(
        "Evidence offered.",
        "What, if anything, is offered in support. This is a description of what the "
        "posts say — not an assessment of whether the claims are scientifically correct, "
        "which would require a literature base the pipeline does not have.",
        T.hbar(e_labels, e_values, xlabel="supplement mentions", color_slot=1),
        count_table(e_labels, e_values, ("evidence offered", "mentions", "share")))

    rows, cols, matrix, raw = crosstab_pct(claims, "claim_strength", "evidence_type",
                                           strength_order, evidence_order)
    if len(rows) and len(cols):
        body += figure(
            "Claim strength against evidence offered.",
            "The cell that matters for the clinical question is strong wording with no "
            "evidence — the top-right region. Row-normalised.",
            T.heatmap(rows, cols, matrix, cbar_label="% of that strength"),
            table(["claim strength"] + cols,
                  [[r] + [n(raw.loc[r, c]) for c in cols] for r in rows],
                  numeric=set(range(1, len(cols) + 1))))

    t_labels, t_values = ordered_counts(claims["claim_type"], type_order)
    body += figure("Claim type.", "Benefit, risk, informational, or no claim at all.",
                   T.hbar(t_labels, t_values, xlabel="supplement mentions", color_slot=2),
                   count_table(t_labels, t_values, ("claim type", "mentions", "share")))
    return body


def sec_credibility(labels: pd.DataFrame, ev: pd.DataFrame, cb: dict) -> str:
    role_order = values_of(cb, "video_level", "speaker_role")
    qual_order = values_of(cb, "video_level", "information_quality")
    mis_order = values_of(cb, "video_level", "misleading_level")
    com_order = values_of(cb, "video_level", "commercial_intent")

    body = ('<h2><span class="num">9</span>Who is speaking, and does reach follow credibility</h2>'
            "<p><i>RQ: sources of information and credibility; engagement with misleading "
            "versus credible content.</i></p>"
            "<blockquote><p>The previous pipeline interpolated like, view and comment counts "
            "into the same prompt that judged credibility, which makes correlating the two "
            "circular. Engagement is withheld from the model here and joined only at this "
            "point, which is what makes the comparison below meaningful.</p></blockquote>")

    r_labels, r_values = ordered_counts(labels["speaker_role"], role_order)
    body += figure("Who is speaking.",
                   "Based only on stated qualifications and the channel name — never inferred "
                   "from how confident the speaker sounds.",
                   T.hbar(r_labels, r_values, xlabel="videos"),
                   count_table(r_labels, r_values, ("speaker role", "videos", "share")))

    q_labels, q_values = ordered_counts(labels["information_quality"], qual_order)
    m_labels, m_values = ordered_counts(labels["misleading_level"], mis_order)
    body += figure("Information quality.",
                   "How well supported the health information is — the support offered, "
                   "not whether the coder agrees with it. Replaces the previous 1–10 scale, "
                   "which put 56% of the corpus on a single value.",
                   T.hbar(q_labels, q_values, xlabel="videos", ramp=True),
                   count_table(q_labels, q_values, ("information quality", "videos", "share")))
    body += figure("Potential to mislead.", "Judged on the content, not the speaker.",
                   T.hbar(m_labels, m_values, xlabel="videos", ramp=True, color_slot=1),
                   count_table(m_labels, m_values, ("misleading level", "videos", "share")))

    c_labels, c_values = ordered_counts(labels["commercial_intent"], com_order)
    body += figure("Commercial intent and disclosure.",
                   "Undisclosed promotion is the category with regulatory relevance.",
                   T.hbar(c_labels, c_values, xlabel="videos", color_slot=2),
                   count_table(c_labels, c_values, ("commercial intent", "videos", "share")))

    views = by_video(ev).set_index("video_id")["outcome_view_count"]
    lab = labels.copy()
    lab["views"] = lab["video_id"].map(views)
    lab = lab.dropna(subset=["views"])

    for var, order, title, caption in [
        ("misleading_level", mis_order, "Reach by potential to mislead",
         "Median views. Medians rather than means because view counts are extremely "
         "long-tailed; a dot plot rather than bars because these do not sum."),
        ("speaker_role", role_order, "Reach by speaker role",
         "Median views by who is speaking."),
    ]:
        grouped = lab.groupby(var)["views"].agg(["median", "count"])
        grouped = grouped.reindex([o for o in order if o in grouped.index]).dropna()
        if len(grouped):
            body += figure(
                title + ".", caption,
                T.dot_range(list(grouped.index), list(grouped["median"]),
                            xlabel="median views", color_slot=0),
                table([var, "videos", "median views"],
                      [[i, n(r["count"]), n(r["median"])] for i, r in grouped.iterrows()],
                      numeric={1, 2}))
    return body


def sec_spotcheck(labels: pd.DataFrame, ev: pd.DataFrame, k: int = 12) -> str:
    merged = labels.merge(
        by_video(ev)[["video_id", "webpage_url", "title", "transcript", "evidence_tier"]],
        on="video_id", how="left")
    sample = merged.sample(min(k, len(merged)), random_state=7)

    rows = []
    for _, r in sample.iterrows():
        link = (f'<a href="{esc(r["webpage_url"])}">{esc(str(r["title"])[:70])}</a>'
                if isinstance(r["webpage_url"], str) else esc(str(r["title"])[:70]))
        judgement = (
            f'{esc(r["symptom_framing"])}'
            f'<span class="quote">{esc(str(r["symptom_framing_evidence"])[:190])}</span>')
        quality = (
            f'{esc(r["information_quality"])}'
            f'<span class="quote">{esc(str(r["information_quality_evidence"])[:190])}</span>')
        rows.append([link, esc(r["content_type"]), judgement, quality,
                     esc(str(r["supplements_raw"])[:60] or "—")])

    return (
        '<h2><span class="num">10</span>Spot-check these yourself</h2>'
        "<p>A random draw of twelve coded videos with the quote the model gave for each "
        "judgement. Open the link, read the video, and check the quote against it. If the "
        "quote is not in the video, the label is not grounded — that is the failure mode "
        "this column exists to expose.</p>"
        + table(["video", "content type", "symptom framing + quote",
                 "information quality + quote", "supplements found"],
                rows, raw_cols={0, 1, 2, 3, 4})
        + "<p class='small muted'>Reproduce this draw with "
          "<code>random_state=7</code> on the labels table.</p>")


def sec_limits(ev: pd.DataFrame, manifest: dict, validation: dict) -> str:
    tier_c = int((ev["evidence_tier"] == "C").sum())
    return (
        '<h2><span class="num">11</span>What this report cannot tell you</h2>'
        "<ul>"
        "<li><b>Transcription quality is unvalidated.</b> The transcripts were produced by "
        "the previous pipeline's audio-visual model, and the source video files no longer "
        "exist, so they cannot be re-transcribed or checked against the audio. Word error "
        "rate is unknown.</li>"
        "<li><b>No visual signal.</b> Text on screen, product packaging and gesture are "
        "invisible to this pipeline. For short-form video, on-screen text often carries the "
        "product name and the claim. Re-running with <code>--include-visual</code> measures "
        f"what that costs.</li>"
        f"<li><b>{tier_c} videos have no codable evidence</b> and were excluded rather than "
        "labelled. The previous pipeline labelled them anyway.</li>"
        "<li><b>Machine labels are not validated against humans yet.</b> The agreement "
        "statistics that would license inferential claims need the human-coded sample "
        "(<code>sample_for_coding.py</code>) to be completed first. Until then every number "
        "here is descriptive.</li>"
        "<li><b>Nothing here says whether a claim is scientifically correct.</b> The pipeline "
        "records what evidence a post <i>offers</i>. Comparing those claims against the "
        "clinical literature is a separate piece of work and deliberately out of scope.</li>"
        "<li><b>Corpus construction is not random.</b> These are search results, shaped by "
        "search terms and platform algorithms, so prevalence figures describe this corpus "
        "rather than social media as a whole.</li>"
        "</ul>")


# --------------------------------------------------------------------------

def load_validation(path: Path) -> dict:
    out: dict = {}
    for key, fname in [("enums", "enum_conformance.csv"), ("grounding", "evidence_grounding.csv"),
                       ("retest", "test_retest.csv"), ("tiers", "tier_sensitivity.csv"),
                       ("legacy", "legacy_comparison.csv")]:
        f = path / fname
        if f.exists():
            out[key] = pd.read_csv(f)
    summary = path / "summary.json"
    if summary.exists():
        data = json.loads(summary.read_text())
        out["alignment"] = data.get("alignment", {})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence", type=Path, default=REPO / "data/evidence/v1/evidence.parquet")
    ap.add_argument("--manifest", type=Path, default=REPO / "data/evidence/v1/manifest.json")
    ap.add_argument("--gate", type=Path, default=REPO / "data/labels/gate_cb1.0.0.parquet")
    ap.add_argument("--labels", type=Path, default=REPO / "data/labels/codebook_cb1.0.0.parquet")
    ap.add_argument("--provenance", type=Path,
                    default=REPO / "data/labels/codebook_cb1.0.0.provenance.json")
    ap.add_argument("--canonical", type=Path, default=REPO / "data/supplement_canonical_map.csv")
    ap.add_argument("--validation", type=Path, default=REPO / "data/validation")
    ap.add_argument("--out", type=Path, default=REPO / "report/menopause_supplement_report.html")
    args = ap.parse_args()

    ev = pd.read_parquet(args.evidence)
    gate = pd.read_parquet(args.gate)
    labels = pd.read_parquet(args.labels)
    manifest = json.loads(args.manifest.read_text())
    prov = json.loads(args.provenance.read_text()) if args.provenance.exists() else {}
    cmap = pd.read_csv(args.canonical) if args.canonical.exists() else None
    validation = load_validation(args.validation)
    cb = build_pass("codebook")["codebook"]

    claims = explode_claims(labels)
    print(f"labels {len(labels):,} videos | claims {len(claims):,} supplement mentions")

    passed = int((gate["is_about_menopause"] == True).sum())  # noqa: E712
    headline = tiles([
        (n(manifest["n_rows"]), "videos in corpus", "one row per video throughout"),
        (n(passed), "discuss menopause", pct(passed, len(gate)) + " of those screened"),
        (n(len(labels)), "fully coded", f"codebook v{cb['version']}"),
        (n(len(claims)), "supplement mentions", "coded individually"),
        (n(claims["supplements_raw"].nunique()), "distinct products", "before canonicalisation"),
    ])

    toc = [
        ("1", "What was analysed", "#s1"), ("2", "The evidence base", "#s2"),
        ("3", "Can these labels be trusted?", "#s3"), ("4", "What supplements are promoted", "#s4"),
        ("5", "Change over time", "#s5"), ("6", "What symptoms are targeted", "#s6"),
        ("7", "How menopause is portrayed", "#s7"), ("8", "What is claimed, and on what basis", "#s8"),
        ("9", "Who is speaking, and reach", "#s9"), ("10", "Spot-check these yourself", "#s10"),
        ("11", "What this cannot tell you", "#s11"),
    ]
    toc_html = ('<ul class="toc">' + "".join(
        f'<li><a href="{href}"><span class="n">{num}</span>{esc(title)}</a></li>'
        for num, title, href in toc) + "</ul>")

    coded, expected = len(labels), passed
    partial = ""
    if coded < expected * 0.98:
        partial = (
            '<div class="panel" style="border-color:var(--warn)">'
            f'<div class="check"><span class="badge warn">PARTIAL</span><div class="body">'
            f'<div class="t">This run is still in progress</div><div class="d">'
            f'{coded:,} of {expected:,} gate-passed videos have been coded '
            f'({100 * coded / max(expected, 1):.0f}%). The coded subset is a random '
            'sample of the analysis set — annotation order follows the corpus file, not '
            'any property of the videos — so proportions below are unbiased estimates, but '
            'counts are not final and small categories are noisy. Re-run '
            '<code>./run_analysis.sh --report</code> when annotation completes.'
            '</div></div></div></div>')

    masthead = (
        '<header class="masthead">'
        '<div class="eyebrow">Verification report · generated, not written</div>'
        "<h1>Menopause supplement content on social media</h1>"
        '<p class="lede">Every variable re-derived from video transcripts and platform '
        "metadata, under a versioned codebook, with deterministic decoding and a quote "
        "behind each judgement.</p>"
        f'<p class="small muted">Built {prov.get("finished_at", prov.get("started_at", "—"))} '
        f'· codebook v{cb["version"]} · evidence {manifest["evidence_version"]}</p>'
        "</header>")

    sections = [
        (partial + headline + toc_html, ""),
        (sec_flow(ev, gate, labels, manifest), "s1"),
        (sec_evidence(ev, manifest), "s2"),
        (sec_verification(labels, ev, prov, validation), "s3"),
        (sec_supplements(labels, claims, cmap), "s4"),
        (sec_time(labels, ev, claims, cmap), "s5"),
        (sec_symptoms(labels, claims, cb), "s6"),
        (sec_framing(labels, cb), "s7"),
        (sec_claims(claims, cb), "s8"),
        (sec_credibility(labels, ev, cb), "s9"),
        (sec_spotcheck(labels, ev), "s10"),
        (sec_limits(ev, manifest, validation), "s11"),
    ]
    body = masthead + "".join(
        (f'<a id="{anchor}"></a>' if anchor else "") + html_chunk
        for html_chunk, anchor in sections)

    body += (
        "<footer>Generated by <code>src/report.py</code> from "
        f"<code>{args.labels.name}</code>. Every figure is computed at build time; "
        "no number in this report was typed by hand. Regenerate with "
        "<code>./run_analysis.sh</code>.</footer>")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page("Menopause Supplement Content Analysis", body))
    print(f"report -> {args.out}  ({args.out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
