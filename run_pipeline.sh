#!/usr/bin/env bash
# run_pipeline.sh — Run the full data collection and analysis pipeline.
#
# Steps:
#   1. Download videos with yt-dlp
#   2. Run batch LLM analysis (batch_LLM.py)
#   3. Join results into Excel files (join_results.py)
#   4. Commit and push changes back to the repository
#
# Usage:
#   ./run_pipeline.sh [timeout|supplements|all]
#
# The optional argument selects which dataset to process (default: all).
#
# Environment variables:
#   GIT_USER_NAME   — Name to use for the git commit (default: "pipeline-bot")
#   GIT_USER_EMAIL  — Email to use for the git commit (default: "pipeline-bot@users.noreply.github.com")

set -euo pipefail

DATASET="${1:-all}"

if [[ "$DATASET" != "timeout" && "$DATASET" != "supplements" && "$DATASET" != "all" ]]; then
    echo "Usage: $0 [timeout|supplements|all]"
    exit 1
fi

if [[ "$DATASET" == "all" ]]; then
    DATASETS=("timeout" "supplements")
else
    DATASETS=("$DATASET")
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Step 1: Download videos with yt-dlp
# ---------------------------------------------------------------------------
echo "=== Step 1: Downloading videos with yt-dlp ==="
for ds in "${DATASETS[@]}"; do
    links_file="$SCRIPT_DIR/data/${ds}_links.txt"
    videos_dir="$SCRIPT_DIR/${ds}_videos"

    if [[ ! -f "$links_file" ]]; then
        echo "Links file not found: $links_file — skipping yt-dlp for $ds"
        continue
    fi

    echo "Downloading $ds videos to $videos_dir ..."
    mkdir -p "$videos_dir"
    yt-dlp \
        --write-info-json \
        --batch-file "$links_file" \
        --paths "$videos_dir" \
        --no-abort-on-error
done

# ---------------------------------------------------------------------------
# Step 2: Run batch LLM analysis
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 2: Running batch LLM analysis ==="
for ds in "${DATASETS[@]}"; do
    echo "Processing $ds dataset with batch_LLM.py ..."
    python3 "$SCRIPT_DIR/src/batch_LLM.py" --dataset "$ds"
done

# ---------------------------------------------------------------------------
# Step 3: Join results into Excel files
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 3: Joining results into Excel files ==="
python3 "$SCRIPT_DIR/src/join_results.py" --dataset "$DATASET"

# ---------------------------------------------------------------------------
# Step 4: Commit and push
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 4: Committing and pushing results ==="

cd "$SCRIPT_DIR"

git config user.name  "${GIT_USER_NAME:-pipeline-bot}"
git config user.email "${GIT_USER_EMAIL:-pipeline-bot@users.noreply.github.com}"

# Pull latest changes before committing to avoid conflicts
git pull --rebase

git add data/*.xlsx data/*.csv data/*.txt 2>/dev/null || true

if git diff --cached --quiet; then
    echo "Nothing to commit — all results are already up to date."
else
    TIMESTAMP="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    git commit -m "chore: update LLM results [$TIMESTAMP]"
    git push
    echo "Changes committed and pushed."
fi

echo ""
echo "Pipeline complete."
