#!/usr/bin/env python3
"""Verification suite -- the checks that make the labels reportable.

Six checks, each producing a number a reviewer can be shown:

  1. Enum conformance      -- is every value actually in the codebook?
  2. Claim-list alignment  -- do the pipe-separated lists line up per row?
  3. Evidence grounding    -- is each quoted span really in the evidence text?
  4. Test-retest stability -- same input twice, same label?
  5. Tier sensitivity      -- do results depend on the weaker-evidence rows?
  6. Legacy comparison     -- how far does the new run move from the old one?

Check 3 is the one worth understanding. Every judgement carries a verbatim quote
justifying it. If that quote cannot be found in the evidence the model was
given, the label is not grounded -- the model wrote something plausible instead
of reading. This is directly measurable, and it is how the off-topic Italian
video that acquired a "traditional chinese medicine" label was caught.
"""

from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

import provenance as prov
from annotate import Annotator, render_evidence
from codebook.schema import build as build_pass

REPO = Path(__file__).resolve().parent.parent

CLAIM_LISTS = ["supplements_raw", "supplement_group", "ingredient_type", "claim_target",
               "claim_type", "claim_strength", "evidence_type", "claim_quote"]
NO_EVIDENCE = {"no supporting evidence", "insufficient evidence", "", "none", "nan"}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text).lower()).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _norm(text).split() if len(t) > 2}


# --------------------------------------------------------------------------
# 1. enum conformance
# --------------------------------------------------------------------------

def check_enums(labels: pd.DataFrame, cb: dict) -> pd.DataFrame:
    rows = []
    ins = cb["insufficient"]
    specs = [(v["name"], v) for v in cb["video_level"]["variables"]] + [
        ("supplements_raw" if v["name"] == "supplement_name_raw" else v["name"], v)
        for v in cb["per_supplement"]["variables"]
    ]
    for col, var in specs:
        if col not in labels.columns or var["type"] not in ("enum", "multi_enum"):
            continue
        allowed = {v["value"] for v in var["values"]} | {ins}
        observed: set[str] = set()
        for cell in labels[col].dropna():
            observed |= {p.strip() for p in str(cell).split(" | ") if p.strip()}
        rows.append({
            "variable": col,
            "allowed": len(allowed),
            "observed": len(observed),
            "out_of_vocabulary": len(observed - allowed),
            "examples": ", ".join(sorted(observed - allowed)[:3]),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 2. claim-list alignment
# --------------------------------------------------------------------------

def check_alignment(labels: pd.DataFrame) -> dict:
    present = [c for c in CLAIM_LISTS if c in labels.columns]
    bad = 0
    for _, row in labels.iterrows():
        lengths = {len([p for p in str(row[c]).split(" | ") if p.strip()]) for c in present}
        if len(lengths) > 1 or lengths.pop() != int(row["n_supplements"]):
            bad += 1
    return {"rows_checked": len(labels), "misaligned_rows": bad,
            "aligned_pct": 100 * (1 - bad / max(len(labels), 1))}


# --------------------------------------------------------------------------
# 3. evidence grounding
# --------------------------------------------------------------------------

def check_grounding(labels: pd.DataFrame, evidence: pd.DataFrame) -> pd.DataFrame:
    ev = evidence.sort_values("is_primary", ascending=False)\
        .drop_duplicates("video_id").set_index("video_id")
    quote_cols = [c for c in labels.columns if c.endswith("_evidence")] + ["claim_quote"]
    quote_cols = [c for c in quote_cols if c in labels.columns]

    rows = []
    for col in quote_cols:
        exact = fuzzy = checked = declined = 0
        for _, row in labels.iterrows():
            vid = row["video_id"]
            if vid not in ev.index:
                continue
            source = _norm(f"{ev.at[vid, 'title']} {ev.at[vid, 'post_text']} {ev.at[vid, 'transcript']}")
            source_tokens = set(source.split())
            for quote in str(row[col]).split(" | "):
                quote = quote.strip()
                if not quote or quote.lower() in NO_EVIDENCE:
                    declined += 1
                    continue
                checked += 1
                normed = _norm(quote)
                if normed and normed in source:
                    exact += 1
                    fuzzy += 1
                else:
                    qt = _tokens(quote)
                    if qt and len(qt & source_tokens) / len(qt) >= 0.8:
                        fuzzy += 1
        rows.append({
            "quote_field": col,
            "quotes_checked": checked,
            "declined_to_quote": declined,
            "verbatim_pct": round(100 * exact / max(checked, 1), 1),
            "near_verbatim_pct": round(100 * fuzzy / max(checked, 1), 1),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 4. test-retest
# --------------------------------------------------------------------------

def check_retest(evidence: pd.DataFrame, n: int, repeats: int, workers: int) -> pd.DataFrame:
    built = build_pass("codebook")
    run = prov.RunProvenance(
        pass_name="codebook", codebook_version=built["codebook_version"],
        schema_hash=built["schema_hash"], prompt_hash=built["prompt_hash"],
    )
    annotator = Annotator(built, run)
    sample = evidence.sample(n, random_state=prov.SEED)

    def once(_: int) -> pd.DataFrame:
        with ThreadPoolExecutor(workers) as pool:
            got = list(pool.map(annotator.annotate_row, (r for _, r in sample.iterrows())))
        return pd.DataFrame([g for g in got if g])

    runs = [once(i) for i in range(repeats)]
    variables = [v["name"] for v in built["codebook"]["video_level"]["variables"]]

    rows = []
    for var in variables:
        stable = total = 0
        for vid in sample["video_id"]:
            seen = []
            for frame in runs:
                hit = frame[frame["video_id"] == vid]
                if len(hit):
                    value = hit.iloc[0][var]
                    seen.append(tuple(value) if isinstance(value, list) else value)
            if len(seen) == repeats:
                total += 1
                stable += len(set(seen)) == 1
        rows.append({"variable": var, "videos": total,
                     "identical_across_runs_pct": round(100 * stable / max(total, 1), 1)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 5 & 6. tier sensitivity and legacy comparison
# --------------------------------------------------------------------------

def check_tiers(labels: pd.DataFrame, evidence: pd.DataFrame, cb: dict) -> pd.DataFrame:
    uniq = evidence.sort_values("is_primary", ascending=False).drop_duplicates("video_id")
    merged = labels.merge(uniq[["video_id", "evidence_tier"]], on="video_id", how="left")
    rows = []
    for var in [v["name"] for v in cb["video_level"]["variables"] if v["type"] == "enum"]:
        if var not in merged.columns:
            continue
        a = merged[merged.evidence_tier == "A"][var].value_counts(normalize=True)
        b = merged[merged.evidence_tier == "B"][var].value_counts(normalize=True)
        both = a.align(b, fill_value=0)
        tvd = float((both[0] - both[1]).abs().sum() / 2)
        rows.append({"variable": var, "tier_A_n": int((merged.evidence_tier == "A").sum()),
                     "tier_B_n": int((merged.evidence_tier == "B").sum()),
                     "total_variation_distance": round(tvd, 3)})
    return pd.DataFrame(rows)


def check_legacy(labels: pd.DataFrame, xlsx: Path) -> pd.DataFrame:
    """Diagnostic only -- the legacy columns are NOT used as input anywhere."""
    old = pd.read_excel(xlsx)[["id", "menopause", "content_type", "health_framework",
                               "credentials", "primary_focus"]]
    # Suffix every legacy column explicitly. Relying on merge's suffixes only
    # renames columns that collide, so a pair with differing names (speaker_role
    # vs credentials) would silently drop out of the comparison.
    old = old.rename(columns={"id": "video_id"})
    old = old.rename(columns={c: f"{c}_old" for c in old.columns if c != "video_id"})
    merged = labels.merge(old, on="video_id", suffixes=("_new", ""))
    pairs = [("content_type", "content_type"), ("health_framework", "health_framework"),
             ("primary_focus", "primary_focus"), ("speaker_role", "credentials")]
    rows = []
    for new_col, old_col in pairs:
        new = new_col
        nc = f"{new}_new" if f"{new}_new" in merged.columns else new
        oc = f"{old_col}_old"
        if nc not in merged.columns or oc not in merged.columns:
            continue
        a = merged[nc].astype(str).str.lower().str.strip()
        b = merged[oc].astype(str).str.lower().str.strip()
        rows.append({"variable": new, "n_compared": len(merged),
                     "exact_agreement_pct": round(100 * float((a == b).mean()), 1)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labels", type=Path, default=REPO / "data/labels/codebook_cb1.0.0.parquet")
    ap.add_argument("--evidence", type=Path, default=REPO / "data/evidence/v1/evidence.parquet")
    ap.add_argument("--xlsx", type=Path, default=REPO / "data/supplements_LLM_results.xlsx")
    ap.add_argument("--out", type=Path, default=REPO / "data/validation")
    ap.add_argument("--retest-n", type=int, default=60)
    ap.add_argument("--retest-repeats", type=int, default=3)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--skip-retest", action="store_true")
    args = ap.parse_args()

    labels = pd.read_parquet(args.labels)
    evidence = pd.read_parquet(args.evidence)
    cb = build_pass("codebook")["codebook"]
    args.out.mkdir(parents=True, exist_ok=True)

    results: dict[str, object] = {}

    print("1. enum conformance")
    enums = check_enums(labels, cb)
    enums.to_csv(args.out / "enum_conformance.csv", index=False)
    results["out_of_vocabulary_total"] = int(enums["out_of_vocabulary"].sum())
    print(enums.to_string(index=False))

    print("\n2. claim-list alignment")
    align = check_alignment(labels)
    results["alignment"] = align
    print(json.dumps(align, indent=2))

    print("\n3. evidence grounding")
    ground = check_grounding(labels, evidence)
    ground.to_csv(args.out / "evidence_grounding.csv", index=False)
    print(ground.to_string(index=False))

    print("\n5. tier sensitivity")
    tiers = check_tiers(labels, evidence, cb)
    tiers.to_csv(args.out / "tier_sensitivity.csv", index=False)
    print(tiers.to_string(index=False))

    print("\n6. legacy comparison (diagnostic only)")
    legacy = check_legacy(labels, args.xlsx)
    legacy.to_csv(args.out / "legacy_comparison.csv", index=False)
    print(legacy.to_string(index=False))

    if not args.skip_retest:
        print(f"\n4. test-retest ({args.retest_n} videos x {args.retest_repeats} runs)")
        subset = evidence[evidence["video_id"].isin(labels["video_id"])]
        retest = check_retest(subset, args.retest_n, args.retest_repeats, args.workers)
        retest.to_csv(args.out / "test_retest.csv", index=False)
        print(retest.to_string(index=False))
        results["retest_min_pct"] = float(retest["identical_across_runs_pct"].min())

    (args.out / "summary.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\nvalidation artifacts -> {args.out}")


if __name__ == "__main__":
    main()
