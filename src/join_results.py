#!/usr/bin/env python3
"""
Join LLM result JSON files with video metadata and save to Excel.

For each dataset (timeout, supplements), this script:
  1. Reads AI result JSON files from {dataset}_results/
  2. Joins them with the corresponding metadata from {dataset}_videos/*.info.json
  3. Saves the combined data to data/{dataset}_LLM_results.xlsx
"""

import argparse
import json
import os
from glob import glob

import pandas as pd
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
    videos_dir = f"{dataset}_videos"

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
            result_file.replace(f"{dataset}_results/", f"{dataset}_videos/")
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
        choices=["timeout", "supplements", "all"],
        default="all",
        help="Dataset to process (default: all)",
    )
    args = parser.parse_args()

    datasets = ["timeout", "supplements"] if args.dataset == "all" else [args.dataset]

    os.makedirs("data", exist_ok=True)

    for dataset in datasets:
        print(f"\nJoining results for dataset: {dataset}")
        df = join_dataset(dataset)
        if df.empty:
            print(f"No data to save for {dataset}")
            continue
        output_path = f"data/{dataset}_LLM_results.xlsx"
        df.to_excel(output_path, index=False)
        print(f"Saved {len(df)} rows to {output_path}")


if __name__ == "__main__":
    main()
