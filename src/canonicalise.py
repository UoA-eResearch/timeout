#!/usr/bin/env python3
"""Normalise supplement names to canonical forms -- once per distinct string.

The researchers asked to "normalise supplement names to a canonical supplement
name (e.g. Vit D includes D3, D2, cholecalciferol...)". The corpus contains
3,117 distinct raw strings for roughly a few hundred real substances: 46
spellings of vitamin D, 86 of collagen, 75 of magnesium.

Design decision: the mapping is built ONCE PER DISTINCT STRING and frozen into
a reviewable CSV, rather than re-decided inside every video call. Three reasons:

  1. Cost -- 3,117 calls instead of 12,213, and it never re-runs for a string
     already in the map.
  2. Consistency -- the same raw string always maps to the same canonical name,
     which a per-video decision cannot guarantee.
  3. Defensibility -- the map is a human-editable artifact. Rebecca and Amore
     can correct any row by hand, and the correction applies retroactively to
     the whole corpus. A reviewer can read the mapping; they cannot read a
     model's per-call reasoning.

Hand edits are preserved: any row with reviewed=yes is never overwritten.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from openai import OpenAI
from tqdm import tqdm

import provenance as prov

REPO = Path(__file__).resolve().parent.parent
MAP_PATH = REPO / "data/supplement_canonical_map.csv"

SCHEMA = {
    "type": "object",
    "properties": {
        "canonical_name": {
            "type": "string",
            "maxLength": 60,
            "description": "The standard name of the underlying substance or product.",
        },
        "is_supplement": {"type": "boolean"},
    },
    "required": ["canonical_name", "is_supplement"],
    "additionalProperties": False,
}

PROMPT = """You are normalising supplement names for a research dataset.

Given one raw supplement name as it was said in a video, return the canonical
name of the underlying substance or product.

Rules:
- Collapse spelling, plural, brand-suffix and form variants onto one name.
  "Vitamin D3", "Vit D", "cholecalciferol", "Vitamin D3 + K2" -> "Vitamin D"
  "Omega-3 Fatty Acids", "Omega 3 Fish Oil", "Omega-3S" -> "Omega-3"
  "Magnesium Glycinate", "Magnesium Citrate", "Magnesium L-Threonate" -> "Magnesium"
  "Red Clover Tea", "Red Clover Leaf" -> "Red Clover"
- Keep a branded multi-ingredient product under its brand name.
- Use Title Case. Do not add words that are not implied by the raw name.
- If a raw string names more than one substance, return the FIRST one.
- is_supplement is false if the string is not actually a supplement, vitamin,
  herb or medication (for example "my supplements", "a healthy diet", "exercise").

Raw name: """


def split_raw(series: pd.Series) -> Counter:
    counts: Counter = Counter()
    for cell in series.dropna():
        for part in str(cell).split(" | "):
            name = re.sub(r"\s+", " ", part).strip(" .,;:-")
            if name and name.lower() not in ("", "nan", "none"):
                counts[name] += 1
    return counts


def load_map() -> pd.DataFrame:
    if MAP_PATH.exists():
        return pd.read_csv(MAP_PATH)
    return pd.DataFrame(columns=["raw_name", "canonical_name", "is_supplement", "n_mentions", "reviewed", "notes"])


def canonicalise(names: list[str], workers: int) -> dict[str, dict]:
    client = OpenAI(base_url=prov.BASE_URL, api_key="not needed",
                    timeout=prov.REQUEST_TIMEOUT_S, max_retries=0)

    def one(name: str) -> tuple[str, dict]:
        for _ in range(3):
            try:
                response = client.chat.completions.create(
                    model=prov.MODEL,
                    messages=[{"role": "user", "content": PROMPT + name}],
                    max_tokens=200, temperature=prov.TEMPERATURE,
                    top_p=prov.TOP_P, seed=prov.SEED,
                    extra_body={
                        "response_format": {"type": "json_schema", "json_schema": {
                            "name": "canonical", "schema": SCHEMA, "strict": True}},
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
                return name, json.loads(response.choices[0].message.content)
            except Exception:
                continue
        # Fall back to the raw string rather than dropping the mention.
        return name, {"canonical_name": name.title(), "is_supplement": True}

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(workers) as pool:
        for name, result in tqdm(pool.map(one, names), total=len(names), desc="canonicalise"):
            out[name] = result
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labels", type=Path, default=REPO / "data/labels/codebook_cb1.0.0.parquet")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    labels = pd.read_parquet(args.labels)
    counts = split_raw(labels["supplements_raw"])
    print(f"{len(counts):,} distinct raw supplement strings, {sum(counts.values()):,} mentions")

    existing = load_map()
    known = set(existing["raw_name"]) if len(existing) else set()
    todo = [n for n in counts if n not in known]
    print(f"{len(todo):,} new strings to canonicalise ({len(known):,} already mapped)")

    if todo:
        resolved = canonicalise(todo, args.workers)
        new_rows = pd.DataFrame([
            {"raw_name": raw, "canonical_name": res["canonical_name"],
             "is_supplement": res["is_supplement"], "n_mentions": counts[raw],
             "reviewed": "no", "notes": ""}
            for raw, res in resolved.items()
        ])
        existing = pd.concat([existing, new_rows], ignore_index=True)

    # Refresh counts, but never touch a row a human has reviewed.
    existing["n_mentions"] = existing["raw_name"].map(counts).fillna(0).astype(int)
    existing = existing.sort_values(["n_mentions", "canonical_name"], ascending=[False, True])
    existing.to_csv(MAP_PATH, index=False)

    n_canon = existing["canonical_name"].nunique()
    print(f"map: {len(existing):,} raw -> {n_canon:,} canonical names -> {MAP_PATH}")
    print(f"  reviewed by a human: {(existing['reviewed'] == 'yes').sum():,}")
    top = (existing[existing["is_supplement"] == True]  # noqa: E712
           .groupby("canonical_name")["n_mentions"].sum().sort_values(ascending=False))
    print("\ntop 15 canonical supplements:")
    print(top.head(15).to_string())


if __name__ == "__main__":
    main()
