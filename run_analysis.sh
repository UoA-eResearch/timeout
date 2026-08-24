#!/usr/bin/env bash
# run_analysis.sh -- rebuild the menopause supplement analysis end to end.
#
# Every stage is resumable and idempotent. Re-running after an interruption
# picks up where it stopped; re-running after a codebook change re-annotates,
# because output files are keyed by codebook version.
#
#   ./run_analysis.sh            full corpus
#   ./run_analysis.sh --dev      20% development split only (fast iteration)
#   ./run_analysis.sh --report   regenerate the report from existing labels
#
# Stages:
#   1  build_evidence.py     transcripts + platform metadata -> frozen corpus
#   2  dedupe.py             duplicate grouping (never deletes a row)
#   3  annotate.py --gate    relevance screen over the whole corpus
#   4  annotate.py --codebook full codebook on the videos that passed
#   5  canonicalise.py       supplement names -> reviewable canonical map
#   6  validate.py           the six verification checks
#   7  sample_for_coding.py  human coding workbook
#   8  report.py             the report

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PY="${PY:-/mnt/.venv/bin/python}"
WORKERS="${WORKERS:-24}"
DEV_FLAG=""
REPORT_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --dev)    DEV_FLAG="--dev-only" ;;
    --report) REPORT_ONLY=1 ;;
    *) echo "unknown option: $arg"; exit 1 ;;
  esac
done

step() { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }

if [[ "$REPORT_ONLY" -eq 0 ]]; then
  step "1/8  evidence corpus"
  $PY src/build_evidence.py

  step "2/8  duplicate grouping"
  $PY src/dedupe.py

  step "3/8  relevance gate"
  $PY src/annotate.py --pass gate --workers "$WORKERS"

  step "4/8  full codebook"
  $PY src/annotate.py --pass codebook --workers "$WORKERS" $DEV_FLAG

  step "5/8  supplement canonicalisation"
  $PY src/canonicalise.py --workers "$WORKERS"

  step "6/8  verification checks"
  $PY src/validate.py --workers "$WORKERS"

  step "7/8  human coding workbook"
  $PY src/sample_for_coding.py
fi

step "8/8  report"
$PY src/report.py

echo
echo "report:    report/menopause_supplement_report.html"
echo "labels:    data/labels/codebook_cb1.0.0.parquet   (one row per video)"
echo "coding:    data/human_coding/coding_sample_v1.xlsx"
