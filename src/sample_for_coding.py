#!/usr/bin/env python3
"""Draw the human-coding sample and render it as a workbook.

Amore's coding is what makes the LLM labels defensible, so it belongs inside
the pipeline rather than beside it. This produces a stratified random sample
with a recorded seed, laid out as an Excel workbook with:

  Sheet "coding"    -- one row per video, the evidence the model saw, and EMPTY
                       columns for the human coder. The model's labels are NOT
                       shown: a coder who can see them is anchored by them, and
                       the agreement statistic becomes meaningless.
  Sheet "codebook"  -- the category definitions, verbatim from codebook_v1.yaml,
                       so the coder and the model work from the same document.
  Sheet "sample"    -- how the sample was drawn: seed, strata, counts.

A second coder should independently code the double-coded subset (flagged in the
workbook) so human-human reliability can be established BEFORE asking whether
the model agrees with humans.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import provenance as prov
from codebook.schema import build as build_pass

REPO = Path(__file__).resolve().parent.parent

# Strata: sample proportionally within platform x evidence tier, so the sample
# is not dominated by whichever platform happens to be largest.
STRATA = ["platform", "evidence_tier"]


def draw(evidence: pd.DataFrame, labels: pd.DataFrame, n: int, double_n: int) -> pd.DataFrame:
    pool = evidence[evidence["video_id"].isin(labels["video_id"]) & evidence["is_primary"]]
    frac = n / len(pool)

    # Collect indices per stratum rather than groupby().apply(): apply consumes
    # the grouping columns, which silently drops platform and evidence_tier from
    # the very sample they were used to stratify.
    picked = []
    for _, group in pool.groupby(STRATA, sort=True):
        take = min(len(group), max(1, round(len(group) * frac)))
        picked.extend(group.sample(take, random_state=prov.SEED).index)

    sample = pool.loc[picked].sample(frac=1, random_state=prov.SEED).head(n).copy()
    sample["double_coded"] = False
    sample.iloc[:double_n, sample.columns.get_loc("double_coded")] = True
    return sample


def codebook_sheet(cb: dict) -> pd.DataFrame:
    rows = []
    for section, key in (("video level", "video_level"), ("per supplement", "per_supplement")):
        for var in cb[key]["variables"]:
            if var["type"] in ("enum", "multi_enum"):
                for value in var["values"]:
                    rows.append({"section": section, "variable": var["name"],
                                 "question": " ".join(var["question"].split()),
                                 "category": value["value"], "definition": value["definition"]})
                rows.append({"section": section, "variable": var["name"], "question": "",
                             "category": cb["insufficient"],
                             "definition": "The evidence does not let you decide."})
            else:
                rows.append({"section": section, "variable": var["name"],
                             "question": " ".join(var["question"].split()),
                             "category": f"(free text: {var['type']})", "definition": ""})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence", type=Path, default=REPO / "data/evidence/v1/evidence.parquet")
    ap.add_argument("--labels", type=Path, default=REPO / "data/labels/codebook_cb1.0.0.parquet")
    ap.add_argument("--out", type=Path, default=REPO / "data/human_coding/coding_sample_v1.xlsx")
    ap.add_argument("-n", type=int, default=350, help="sample size")
    ap.add_argument("--double", type=int, default=100, help="subset coded by two people")
    args = ap.parse_args()

    evidence = pd.read_parquet(args.evidence)
    labels = pd.read_parquet(args.labels)
    cb = build_pass("codebook")["codebook"]

    sample = draw(evidence, labels, args.n, args.double)

    coding = sample[["video_id", "platform", "channel_name", "evidence_tier", "double_coded",
                     "webpage_url", "title", "post_text", "transcript"]].copy()
    # Empty columns for the coder. Deliberately no model labels -- see docstring.
    for var in cb["video_level"]["variables"]:
        coding[f"HUMAN_{var['name']}"] = ""
    coding["HUMAN_supplements_listed"] = ""
    coding["HUMAN_notes"] = ""

    meta = pd.DataFrame([
        {"field": "seed", "value": prov.SEED},
        {"field": "sample_size", "value": len(coding)},
        {"field": "double_coded_subset", "value": int(sample["double_coded"].sum())},
        {"field": "strata", "value": " x ".join(STRATA)},
        {"field": "population", "value": "gate-passed, is_primary videos"},
        {"field": "population_size", "value": int(labels["video_id"].nunique())},
        {"field": "codebook_version", "value": cb["version"]},
        {"field": "drawn_at", "value": prov.utcnow()},
    ])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(args.out, engine="openpyxl") as writer:
        coding.to_excel(writer, sheet_name="coding", index=False)
        codebook_sheet(cb).to_excel(writer, sheet_name="codebook", index=False)
        meta.to_excel(writer, sheet_name="sample", index=False)
        for sheet, widths in (("coding", {"G": 50, "H": 60, "I": 90}), ("codebook", {"C": 60, "E": 70})):
            ws = writer.sheets[sheet]
            for col, width in widths.items():
                ws.column_dimensions[col].width = width

    print(f"coding workbook: {len(coding):,} videos "
          f"({int(sample['double_coded'].sum())} double-coded) -> {args.out}")
    print(sample.groupby(STRATA).size().to_string())


if __name__ == "__main__":
    main()
