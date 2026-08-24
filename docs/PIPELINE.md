# Running the transcript-derived pipeline

Operator guide for the code in `src/`. The reasoning behind the design is in
`DEFENSIBLE-PIPELINE.md`; the mapping from the researchers' questions to
variables is in `BUILD-PLAN.md`. This file is how to run it.

```bash
./run_analysis.sh            # full corpus, all eight stages
./run_analysis.sh --dev      # 20% development split, for iterating on the codebook
./run_analysis.sh --report   # regenerate the report from existing labels
```

Everything is resumable. Interrupt any stage and re-run: completed rows are
skipped, and output files are keyed by codebook version so two versions cannot
silently mix in one spreadsheet.

---

## The one-paragraph version

Video transcripts and genuine platform metadata go in. A relevance gate throws
out the 60% of the corpus that is not about menopause. The survivors are coded
against a versioned codebook using schema-constrained decoding at temperature 0,
with a verbatim quote attached to every judgement. Six checks run over the
result, a human-coding workbook is drawn, and a self-contained HTML report is
built in which no number was typed by hand.

---

## Stages

| # | script | what it does | rough cost |
|---|---|---|---|
| 1 | `build_evidence.py` | xlsx → frozen, hashed evidence corpus + tiers | seconds |
| 2 | `dedupe.py` | duplicate grouping (never deletes a row) | seconds |
| 3 | `annotate.py --pass gate` | relevance screen over the whole corpus | ~45 min |
| 4 | `annotate.py --pass codebook` | full codebook on gate survivors | ~1–2 h |
| 5 | `canonicalise.py` | supplement names → reviewable canonical map | ~2 min |
| 6 | `validate.py` | the six verification checks | ~20 min |
| 7 | `sample_for_coding.py` | human coding workbook | seconds |
| 8 | `report.py` | the HTML report | ~1 min |

Timings are for the shared CER sandbox endpoint and vary a lot with who else is
using it.

---

## The three files that matter

**`src/codebook/codebook_v1.yaml`** — the single source of truth. Variables,
categories, and the definition of each category. `schema.py` compiles it into a
JSON Schema for the decoder; `sample_for_coding.py` renders it into the workbook
the human coders read. Model and coders therefore work from the same document.
When a coder disagrees with a label, sharpen the definition here and both improve.

**Bump `version:` on any change.** Output files are named after it.

**`data/supplement_canonical_map.csv`** — raw supplement string → canonical name.
Built once per distinct string, then hand-editable. Set `reviewed` to `yes` on a
row and the pipeline will never overwrite it. Corrections apply retroactively to
the whole corpus.

**`data/menopause_labels_v1.xlsx`** (from `export_tables.py`) — the delivered
spreadsheet. One row per video. Per-supplement fields are pipe-separated lists
aligned in the same order as `supplements_raw`; a `claims_long` sheet has the
same data exploded to one row per mention.

---

## Things that will bite you

**`guided_json` is silently ignored by this endpoint.** Passing
`extra_body={"guided_json": schema}` returns free prose with no error and no
warning, so a pipeline relying on it degrades invisibly. Use
`response_format` with `json_schema` and `strict: True`, as `annotate.py` does.

**Requests need an explicit timeout.** Without one, a hung connection parks a
worker forever and the thread pool stalls the entire run while looking healthy —
the progress bar simply stops advancing. `provenance.REQUEST_TIMEOUT_S` is set
to 90 s and the client does no retries of its own, because `annotate.py` does
them and quarantines what still fails.

**`video_id` is not unique.** The corpus has 86 exact platform-id collisions, so
a naive `merge` or `set_index` on it silently duplicates rows. Use
`report.by_video()`, which keeps the primary row of each duplicate group.

**Concurrency above ~16 is not obviously faster.** The endpoint is shared. If
throughput collapses, lower `WORKERS` rather than raising it.

---

## Changing the codebook

1. Edit `codebook_v1.yaml`, bump `version`.
2. `./run_analysis.sh --dev` — re-annotate the 20% development split only.
3. Read the report, compare against the human-coded sample, iterate.
4. When the codebook settles: pre-register the analysis plan, then run the full
   corpus once.

The development/confirmatory split exists so that step 3 is a documented
development phase rather than the thing a reviewer calls peeking. Iterating on
the dev split is fine; iterating on the confirmatory set is not.

---

## What the report will not do

It will not tell you whether a health claim is scientifically correct. The
pipeline records what evidence a post *offers* — a study, a guideline, a
mechanism, a testimonial, traditional use, or nothing. Comparing those claims
against the clinical literature needs an evidence base the pipeline does not
have, and asking a language model to do it would reintroduce exactly the
unverifiable judgement the rest of this design removes.

It will also not license inferential claims until the human coding is done. Until
`sample_for_coding.py`'s workbook comes back completed and `validate.py` can
report model–human agreement per variable, every number in the report is
descriptive.
