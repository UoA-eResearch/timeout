#!/usr/bin/env python3
"""Duplicate detection -- group, never delete.

The researchers asked for "one record per post (e.g. post that appear across
multiple platforms)". This assigns every video a ``duplicate_group_id`` and
marks exactly one row per group ``is_primary``. Analysis filters on is_primary;
the non-primary rows stay in the file and stay auditable. The row count is
therefore unchanged: one row per video, always.

Three rules, applied in order and each recorded, so any grouping can be
explained to a reviewer rather than attributed to a similarity score:

  1. same platform video id
  2. same normalised title + same duration
  3. same uploader + near-identical transcript opening

Rule 3 is deliberately conservative -- a normalised 120-character prefix rather
than a fuzzy similarity threshold. A duplicate you can explain in one sentence
is worth more here than a few extra catches you cannot.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    text = _PUNCT.sub(" ", str(text).lower())
    return _SPACE.sub(" ", text).strip()


class Union:
    """Plain union-find; keeps grouping transitive and order-independent."""

    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, a):
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def join(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def dedupe(ev: pd.DataFrame) -> pd.DataFrame:
    df = ev.copy().reset_index(drop=True)
    uf = Union(df.index.tolist())
    links: list[tuple[int, int, str]] = []

    def link(keys: pd.Series, reason: str) -> None:
        valid = keys[keys.astype(bool) & keys.notna()]
        for _, idx in valid.groupby(valid).groups.items():
            idx = list(idx)
            if len(idx) < 2:
                continue
            for other in idx[1:]:
                uf.join(idx[0], other)
                links.append((idx[0], other, reason))

    link(df["video_id"].astype(str), "same platform video id")

    title_key = df["title"].map(normalise) + "||" + df["duration_s"].fillna(-1).astype(int).astype(str)
    link(title_key.where(df["title"].str.len() > 0, ""), "same title and duration")

    opening = df["transcript"].map(normalise).str[:120]
    uploader_key = df["uploader"].map(normalise) + "||" + opening
    link(uploader_key.where(opening.str.len() >= 60, ""), "same uploader and transcript opening")

    df["duplicate_group_id"] = [uf.find(i) for i in df.index]

    # Reasons attach to the GROUP, not to whichever row happened to be second in
    # a pairwise link -- groups can form transitively across all three rules, and
    # every member of a group deserves the same explanation.
    group_reasons: dict[int, set[str]] = {}
    for a, b, reason in links:
        group_reasons.setdefault(uf.find(a), set()).add(reason)
    df["duplicate_reason"] = [
        "; ".join(sorted(group_reasons.get(g, ()))) for g in df["duplicate_group_id"]
    ]

    # Primary = most-viewed of the group (falls back to longest transcript, then
    # first row). Chosen because the most-viewed copy is the one whose reach the
    # engagement analyses are about.
    order = df.sort_values(
        ["duplicate_group_id", "outcome_view_count", "transcript_chars"],
        ascending=[True, False, False],
        na_position="last",
    )
    primary_idx = set(order.groupby("duplicate_group_id").head(1).index)
    df["is_primary"] = df.index.isin(primary_idx)

    sizes = df.groupby("duplicate_group_id").size()
    n_groups = int((sizes > 1).sum())
    n_dupes = int(len(df) - df["is_primary"].sum())
    print(f"duplicate groups: {n_groups:,}  non-primary rows: {n_dupes:,} "
          f"({100 * n_dupes / len(df):.1f}% of corpus)")
    if n_dupes:
        print(df.loc[~df["is_primary"], "duplicate_reason"].value_counts().to_string())
    cross = (
        df[df.duplicated("duplicate_group_id", keep=False)]
        .groupby("duplicate_group_id")["platform"].nunique()
    )
    print(f"groups spanning >1 platform: {int((cross > 1).sum()):,}")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence", type=Path, default=REPO / "data/evidence/v1/evidence.parquet")
    args = ap.parse_args()
    ev = pd.read_parquet(args.evidence)
    out = dedupe(ev)
    out.to_parquet(args.evidence, index=False)
    print(f"wrote duplicate_group_id / is_primary back to {args.evidence}")


if __name__ == "__main__":
    main()
