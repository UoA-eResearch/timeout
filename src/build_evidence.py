#!/usr/bin/env python3
"""Stage A -- build the frozen evidence corpus.

Reads data/supplements_LLM_results.xlsx and keeps ONLY the evidence: the
transcript plus genuine platform metadata that came from yt-dlp. Every
previously-inferred label is dropped, so downstream variables are re-derived
from scratch rather than inherited.

Two categories of field are deliberately withheld from the model:

  * AI_description -- model-generated visual description. It is the only visual
    signal available and dropping it costs information, but it is model output,
    not observed data; including it would bury an undocumented model pass inside
    the evidence base. Available via --include-visual so the cost is measurable.

  * view_count / like_count / comment_count / upload_date -- these are the
    study's OUTCOME variables. The old prompt interpolated engagement counts
    into the same call that judged credibility, which makes
    "engagement with misinformation vs credible content" circular. They are
    carried in the corpus for analysis but never shown to the model.

The output is versioned, hashed and manifested: it is the artifact you archive
and cite, and it is never regenerated for a prompt change.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from provenance import file_sha256, utcnow

REPO = Path(__file__).resolve().parent.parent

# Genuine platform metadata -- came from yt-dlp, not from a model.
PLATFORM_META = [
    "id", "extractor", "channel", "channel_id", "uploader", "uploader_id",
    "title", "description", "timestamp", "duration", "upload_date", "webpage_url",
]
# Outcome variables: carried for analysis, never shown to the model.
OUTCOMES = ["view_count", "like_count", "comment_count"]

# Fields shown to the model. Nothing else reaches the prompt.
EVIDENCE_FIELDS = ["title", "post_text", "channel_name", "platform", "duration_s", "transcript"]

NO_SPEECH_MARKERS = ("no spoken content", "no speech", "no audio")
MIN_CHARS = 40


def _clean(value: object) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).split())


def _usable(text: str) -> bool:
    if len(text) < MIN_CHARS:
        return False
    return not any(m in text.lower() for m in NO_SPEECH_MARKERS)


def assign_tier(transcript: str, post_text: str) -> str:
    """Evidence tier -- how much there is to code from.

    A: usable transcript.
    B: no usable transcript, but usable post text.
    C: neither. NOT annotated; reported as an exclusion. The old pipeline
       labelled these anyway, which is where fabricated labels came from.
    """
    if _usable(transcript):
        return "A"
    if _usable(post_text):
        return "B"
    return "C"


def build(xlsx: Path, out_dir: Path, version: str, include_visual: bool) -> pd.DataFrame:
    raw = pd.read_excel(xlsx)

    ev = pd.DataFrame(index=raw.index)
    ev["video_id"] = raw["id"].map(_clean)
    ev["platform"] = raw["extractor"].map(_clean)
    ev["title"] = raw["title"].map(_clean)
    ev["post_text"] = raw["description"].map(_clean)
    ev["channel_name"] = raw["channel"].fillna(raw["uploader"]).map(_clean)
    ev["uploader"] = raw["uploader"].map(_clean)
    ev["webpage_url"] = raw["webpage_url"].map(_clean)
    ev["duration_s"] = pd.to_numeric(raw["duration"], errors="coerce")
    ev["transcript"] = raw["transcript"].map(_clean)

    # Withheld from the model; kept for analysis-time joins.
    for col in OUTCOMES:
        ev[f"outcome_{col}"] = pd.to_numeric(raw[col], errors="coerce")
    ev["outcome_upload_date"] = pd.to_datetime(
        raw["upload_date"], format="%Y%m%d", errors="coerce"
    )

    if include_visual:
        ev["visual_description"] = raw["AI_description"].map(_clean)

    ev["transcript_chars"] = ev["transcript"].str.len()
    ev["post_text_chars"] = ev["post_text"].str.len()
    ev["evidence_tier"] = [
        assign_tier(t, p) for t, p in zip(ev["transcript"], ev["post_text"])
    ]

    # A stable per-row hash of exactly what the model will see. Two runs over
    # the same evidence hash are comparable; a changed hash means the input
    # moved, not the model.
    ev["evidence_sha"] = [
        __import__("hashlib").sha256(
            "\x1f".join(str(r[f]) for f in EVIDENCE_FIELDS).encode()
        ).hexdigest()[:16]
        for _, r in ev.iterrows()
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = out_dir / "evidence.parquet"
    ev.to_parquet(corpus_path, index=False)

    manifest = {
        "evidence_version": version,
        "built_at": utcnow(),
        "source_xlsx": str(xlsx.relative_to(REPO)),
        "source_sha256": file_sha256(xlsx),
        "n_rows": int(len(ev)),
        "include_visual": include_visual,
        "fields_shown_to_model": EVIDENCE_FIELDS + (["visual_description"] if include_visual else []),
        "fields_withheld_from_model": OUTCOMES + ["upload_date"] + ([] if include_visual else ["AI_description"]),
        "inferred_columns_dropped": sorted(
            set(raw.columns) - set(PLATFORM_META) - set(OUTCOMES)
        ),
        "evidence_tiers": ev["evidence_tier"].value_counts().sort_index().to_dict(),
        "corpus_sha256": file_sha256(corpus_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"evidence corpus {version}: {len(ev):,} rows -> {corpus_path}")
    for tier, n in sorted(manifest["evidence_tiers"].items()):
        print(f"  tier {tier}: {n:,} ({100 * n / len(ev):.1f}%)")
    print(f"  dropped {len(manifest['inferred_columns_dropped'])} inferred columns")
    return ev


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsx", type=Path, default=REPO / "data/supplements_LLM_results.xlsx")
    ap.add_argument("--out", type=Path, default=REPO / "data/evidence")
    ap.add_argument("--version", default="v1")
    ap.add_argument("--include-visual", action="store_true",
                    help="also expose the model-generated visual description (default off)")
    args = ap.parse_args()
    build(args.xlsx, args.out / args.version, args.version, args.include_visual)


if __name__ == "__main__":
    main()
