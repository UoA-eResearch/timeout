#!/usr/bin/env python3
"""Export the delivered spreadsheet: one row per video, aligned claim lists.

Sheets:
  labels        one row per video -- evidence metadata, every coded variable,
                pipe-separated per-supplement lists, and provenance columns
  claims_long   the same claims exploded to one row per supplement mention,
                derived deterministically by splitting on " | "
  codebook      category definitions, so the sheet is self-describing
  provenance    model, settings and hashes for the run that produced it
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from codebook.schema import build as build_pass
from report import by_video, explode_claims

REPO = Path(__file__).resolve().parent.parent

EVIDENCE_COLS = ["video_id", "platform", "channel_name", "webpage_url", "title",
                 "duration_s", "evidence_tier", "transcript_chars",
                 "duplicate_group_id", "is_primary", "duplicate_reason",
                 "outcome_view_count", "outcome_like_count", "outcome_comment_count",
                 "outcome_upload_date"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labels", type=Path, default=REPO / "data/labels/codebook_cb1.0.0.parquet")
    ap.add_argument("--evidence", type=Path, default=REPO / "data/evidence/v1/evidence.parquet")
    ap.add_argument("--canonical", type=Path, default=REPO / "data/supplement_canonical_map.csv")
    ap.add_argument("--provenance", type=Path,
                    default=REPO / "data/labels/codebook_cb1.0.0.provenance.json")
    ap.add_argument("--out", type=Path, default=REPO / "data/menopause_labels_v1.xlsx")
    args = ap.parse_args()

    labels = pd.read_parquet(args.labels)
    ev = by_video(pd.read_parquet(args.evidence))
    cb = build_pass("codebook")["codebook"]

    merged = ev[EVIDENCE_COLS].merge(labels, on="video_id", how="right")
    claims = explode_claims(labels)

    if args.canonical.exists():
        cmap = pd.read_csv(args.canonical)
        claims = claims.merge(
            cmap[["raw_name", "canonical_name", "is_supplement"]],
            left_on="supplements_raw", right_on="raw_name", how="left").drop(columns=["raw_name"])

    from sample_for_coding import codebook_sheet
    prov = json.loads(args.provenance.read_text()) if args.provenance.exists() else {}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(args.out, engine="openpyxl") as writer:
        merged.to_excel(writer, sheet_name="labels", index=False)
        claims.to_excel(writer, sheet_name="claims_long", index=False)
        codebook_sheet(cb).to_excel(writer, sheet_name="codebook", index=False)
        pd.DataFrame(list(prov.items()), columns=["field", "value"]).to_excel(
            writer, sheet_name="provenance", index=False)

    print(f"labels sheet: {len(merged):,} rows (one per video), {len(merged.columns)} columns")
    print(f"claims_long:  {len(claims):,} supplement mentions")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
