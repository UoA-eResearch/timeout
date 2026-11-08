#!/usr/bin/env python3
"""
Join LLM result JSON files with video metadata and save to Excel.

For each dataset (timeout, supplements, distress), this script:
  1. Reads AI result JSON files from {dataset}_results/
  2. Joins them with the corresponding metadata from {dataset}_videos/*.info.json
  3. Saves the combined data to data/{dataset}_LLM_results.xlsx
  (answers in data/{dataset}_validated_screen.csv, if present, replace the LLM's)
"""

import argparse
import json
import os
from glob import glob

import pandas as pd
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from tqdm import tqdm

METADATA_KEYS = [
    "id",
    "extractor",
    "channel",
    "channel_id",
    "uploader",
    "uploader_id",
    "title",
    "description",
    "timestamp",
    "view_count",
    "like_count",
    "comment_count",
    "duration",
    "upload_date",
    "webpage_url",
]


def join_dataset(dataset: str) -> pd.DataFrame:
    results_dir = f"{dataset}_results"
    if os.path.isdir(results_dir + "_think"):
        results_dir = results_dir + "_think"
        print(f"Using thinking results from {results_dir}")

    result_files = glob(f"{results_dir}/*.json")
    if not result_files:
        print(f"No result files found in {results_dir}/")
        return pd.DataFrame()

    rows = []
    for result_file in tqdm(result_files, desc=f"Processing {dataset}"):
        with open(result_file) as f:
            try:
                ai_data = json.load(f)
            except json.JSONDecodeError:
                print(f"Could not parse JSON: {result_file}")
                continue

        # Rename 'description' from AI output to avoid clash with video metadata
        if "description" in ai_data:
            ai_data["AI_description"] = ai_data.pop("description")

        metadata_file = (
            result_file.replace(results_dir, f"{dataset}_videos/")
            .replace(".result.json", ".info.json")
        )
        if not os.path.isfile(metadata_file):
            print(f"Missing metadata file: {metadata_file}")
            meta = {}
        else:
            with open(metadata_file) as f:
                meta = json.load(f)

        row = {key: meta.get(key) for key in METADATA_KEYS}
        row.update(ai_data)
        rows.append(row)

    df = pd.DataFrame(rows)
    # The LLM answers true/false questions with JSON booleans or with the strings "True"/"False"; make them all booleans
    for col in df.columns:
        values = df[col].dropna()
        if len(values) and values.map(lambda v: str(v).strip().lower() in ("true", "false")).all():
            df[col] = df[col].map(lambda v: str(v).strip().lower() == "true" if pd.notna(v) else v)
    # Screening answers the research team validated (data/{dataset}_validated_screen.csv: id plus answer columns)
    # take precedence over a later run's, which are kept as <column>_llm
    screen_path = f"data/{dataset}_validated_screen.csv"
    if os.path.isfile(screen_path):
        screen = pd.read_csv(screen_path, dtype={"id": str}).set_index("id")
        ids = df["id"].astype(str)
        for col in screen.columns:
            df[f"{col}_llm"] = df[col]
            validated = ids.map(screen[col])
            df[col] = validated.where(validated.notna(), df[col])
            print(f"{col}: validated answers used for {int(validated.notna().sum())} of {len(df)} posts")
    if "upload_date" in df.columns:
        df = df.sort_values("upload_date")
    if "sentiment" in df.columns:
        df["sentiment"] = df["sentiment"].str.lower()
    return df


def main():
    parser = argparse.ArgumentParser(
        description="Join LLM result JSONs with video metadata and save to Excel"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        choices=["timeout", "supplements", "distress", "all"],
        default="all",
        help="Dataset to process (default: all)",
    )
    args = parser.parse_args()

    datasets = ["timeout", "supplements", "distress"] if args.dataset == "all" else [args.dataset]

    os.makedirs("data", exist_ok=True)

    for dataset in datasets:
        print(f"\nJoining results for dataset: {dataset}")
        df = join_dataset(dataset)
        if df.empty:
            print(f"No data to save for {dataset}")
            continue
        output_path = f"data/{dataset}_LLM_results.xlsx"
        # Excel can't store some control characters that turn up in video descriptions
        df = df.apply(lambda col: col.map(lambda v: ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v))
        df.to_excel(output_path, index=False)
        print(f"Saved {len(df)} rows to {output_path}")


if __name__ == "__main__":
    main()
