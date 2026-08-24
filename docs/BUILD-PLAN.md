# Build plan — re-derive all variables from transcripts

**Status:** proposal for agreement, 2026-08-21 (rev 2). Nothing coded yet.
**Inputs:** `docs/DEFENSIBLE-PIPELINE.md` (the why),
`26-08-10 Thoughts and questions to refine LLM prompts.docx` (the what),
`data/supplements_LLM_results.xlsx` (source of transcripts + platform metadata).

**Rev 2 changes:** no previously-inferred label is reused as input or carried
forward — every variable is re-derived. Output is exactly one row per video.

---

## 1. What counts as evidence

The only inputs to annotation are the transcript and **genuine platform
metadata** — fields that came from yt-dlp, not from a model:

| given to the model | withheld, and why |
|---|---|
| `transcript` | every previously-inferred label — `menopause`, `supplements`, `symptoms`, `tone`, `sentiment`, `content_type`, `credentials`, `quality`, … all re-derived from scratch |
| `title` | `AI_description` — model-generated visual description, not observed data |
| `description` (post text) | `view_count`, `like_count`, `comment_count` — **see §1.1** |
| `channel`, `uploader` | `timestamp`, `upload_date` — **see §1.1** |
| `extractor` (platform), `duration` | |

The video files no longer exist anywhere on `/mnt`, so re-transcribing with a
dedicated ASR model — the Stage A ideal in `DEFENSIBLE-PIPELINE.md` §4.1 — is not
available. The stored transcripts are the evidence floor. This should be stated
as a limitation in the paper: transcription quality is unvalidated, because the
audio it came from is gone.

### 1.1 Withholding the outcome variables — a correctness fix

The current prompt (`batch_LLM.py:55`) interpolates engagement into the same call
that produces `quality`, `usefulness` and `misleading`:

```python
It has {like_count} likes, {view_count} views, and {comment_count} comments.
```

One of the docx's research questions is:

> *"Engagement with misinformation vs credible content (could use view counts to
> answer this)"*

If popularity is fed to the model that judges credibility, then correlating
credibility against popularity is circular — the pipeline would be measuring its
own input. **The current `misleading` and `quality` columns cannot be used for
that RQ at all.** Withholding engagement is not fastidiousness; it is what makes
the question answerable.

The same applies to dates and the "changed over time" RQ. Content in, outcomes
out; the join happens at analysis time.

### 1.2 Evidence tiers — and 204 videos that cannot be coded

| tier | definition | n | share |
|---|---|---|---|
| **A** | usable transcript (has speech, ≥40 chars) | 10,522 | 86.2% |
| **B** | no usable transcript, but post text ≥40 chars | 1,487 | 12.2% |
| **C** | neither — no transcript and no post text | **204** | 1.7% |

Tier C is **not annotated**. Every variable is set to `insufficient evidence` and
the rows are reported as an exclusion in the flow diagram. The current pipeline
labels them anyway, which is where fabricated labels come from.

`evidence_tier` ships as a column, so any result can be re-run tier A only to
check whether it depends on the weaker-evidence rows.

---

## 2. Output shape: one row per video

The docx's second-pass questions are all *per supplement* — claim type, claim
strength, evidence type, and which symptom the supplement is matched to. A video
pushing magnesium *and* black cohosh can make a strong cure claim about one and
mention the other in passing.

The model therefore returns a nested `claims[]` array, and the delivered table
**flattens it onto one row per video** using pipe-separated aligned lists — the
same convention the existing prompt already uses ("*in the same order as the
supplements field*"), so it reads the way Rebecca and Amore already expect:

```
supplements_raw        Magnesium Glycinate | Black Cohosh | Vitamin D3
supplements_canonical  Magnesium           | Black Cohosh | Vitamin D
supplement_group       Single ingredient   | Single ingr. | Single ingredient
claim_target           physical            | vasomotor    | none
claim_strength         reduces             | may help     | no claim
evidence_type          testimonial         | traditional  | none
```

`annotate.py` asserts every aligned list on a row has identical length and that
it equals `n_supplements`; a row failing that is retried, then quarantined rather
than silently written. Sizing: 3,212 videos mention ≥1 supplement, mean 1.83,
max 19 → ~8,600 claim entries across ~3,200 rows.

A long-format claims table is derivable deterministically by splitting on `|`;
a helper is provided, but the shipped artifact is the one-row-per-video sheet.

Duplicates are grouped, never deleted (`duplicate_group_id`, `is_primary`), which
keeps the row count stable at one per video.

---

## 3. Architecture

```
data/supplements_LLM_results.xlsx
        │   (transcript + genuine platform metadata ONLY — §1)
        ▼
 [1] build_evidence.py ──► data/evidence/v1/  frozen, hashed, manifested
        │                  + evidence_tier
        ▼
 [2] dedupe.py ──────────► duplicate_group_id, is_primary
        │
        ▼
 [3] annotate.py --pass gate      11,969 tier A+B × 2 fields    ~25 min
        │                          is_about_menopause · mentions_supplements
        ▼  (~4,700 expected to survive)
 [4] annotate.py --pass codebook   full nested schema           ~40 min
        │
        ├──► [5] canonicalise.py ──► data/supplement_canonical_map.csv
        ├──► [6] sample_for_coding.py ──► Amore's coding workbook
        └──► [7] validate.py ──► agreement · test-retest · alignment checks
```

Both passes: `temperature=0`, pinned seed, `response_format` json_schema with
`strict:True`, provenance on every row, resumable, keyed by codebook version.

`batch_LLM.py` is untouched and keeps working. The existing spreadsheet is read
for its transcripts and metadata only, and its label columns are **not carried
into the output** — the new sheet stands alone. Where an old column has a new
counterpart, `validate.py` reports old-vs-new agreement as a diagnostic, which is
how we find out what the temperature-0.6 unconstrained run was costing.

---

## 4. Variable map — every ask in the docx

All of these are re-derived; none are inherited.

| docx ask | variable | 
|---|---|
| Remove/merge duplicate posts | `duplicate_group_id`, `is_primary` |
| Symptom categories (vasomotor / physical / psychological / health & metabolic / none / prevention) | `symptom_categories` — multi-label, docx wording |
| Symptom framing (burden‑suffering / loss‑decline / deficiency‑imbalance / general ageing / normalised) | `symptom_framing` — multi-label |
| Canonical supplement names | `supplements_canonical` via frozen reviewable CSV |
| 5 mutually exclusive supplement groups | `supplement_group` |
| Single ingredients by substance type | `ingredient_type` |
| Match supplement → symptom | `claim_target` |
| Claim type (benefit / risk / informational) | `claim_type` |
| Claim strength (cures / eliminates / reduces / supports / may help / no claim) | `claim_strength` |
| Evidence type (study / guideline / mechanism / testimonial / traditional use / none) | `evidence_type` |
| "quote phrases to justify categorisation" | `claim_quote` + `*_evidence_span` on every video-level judgement |
| Eliminate HRT | `supplement_group == medicines and hormone therapies`, filtered at analysis |
| Source credibility ("could use job") | `credentials`, `credentials_evidence`, `speaker_role` |
| Engagement with misinformation ("could use view counts") | analysis-time join — §1.1 |
| Western lens / symptom-burden hypothesis | `health_framework`, `menopause_framing`, `symptom_framing` |
| Top 10 supplements vs *scientific* claims | **out of scope** — §7 |

Every enum carries an `insufficient evidence` member. Every judgement carries a
verbatim `evidence_span` checkable against the transcript.

---

## 5. Files to be written

```
src/codebook/codebook_v1.yaml   single source of truth: variables, enums, definitions,
                                coder instructions. Model and human coders read the
                                SAME document. Goes in supplementary material.
src/codebook/schema.py          builds JSON Schema from the yaml
src/build_evidence.py           xlsx → frozen evidence corpus, tiers, manifest
src/dedupe.py                   duplicate grouping
src/annotate.py                 runner (--pass gate | codebook), alignment validation
src/canonicalise.py             supplement string → canonical map
src/sample_for_coding.py        stratified sample → coding workbook for Amore
src/validate.py                 agreement, test-retest, old-vs-new diagnostics
src/provenance.py               model id/revision, hashes, seeds, timestamps
```

---

## 6. Judgement calls (object if wrong)

1. **Nothing inferred is inherited** — including the `menopause` gate and the
   supplements list, both re-derived. Costs ~25 min of compute; buys a dataset
   with a single, documented provenance.
2. **`AI_description` is excluded.** It is the only visual signal available, and
   dropping it costs information — text-only agreed with the old video-based
   `content_type` on 36/59 in testing. But it is model output, not observed data,
   and mixing it in would put an undocumented model pass inside the evidence
   base. `--include-visual` will exist as a flag, default off, so the cost can be
   measured in `validate.py` rather than argued about.
3. **Engagement metrics and dates withheld from the model** — §1.1.
4. **1–10 scales replaced by 4-level anchored ordinals** (`info_quality`,
   `misleading_level`), each level defined in a sentence.
5. **Canonical names = frozen human-editable CSV**, built once per *distinct
   string* (3,117, ~2 min), not per video. Rebecca and Amore can correct it by
   hand and corrections apply retroactively. The variant problem is real: 46
   Vitamin D spellings, 86 collagen, 75 magnesium.
6. **Duplicates grouped, never deleted.** Actual scale: 86 exact id collisions,
   418 exact title collisions, but only **17 titles on more than one platform** —
   cross-platform duplication is far smaller than the docx assumes; within-
   platform reposting is the real issue.
7. **HRT labelled and kept**, filtered at analysis. Excluding at annotation makes
   the count unreportable and a reviewer will ask for it.
8. **20/80 dev/confirmatory split**, recorded seed, on the menopause-relevant set.

---

## 7. Order of work

| # | step | output | compute |
|---|---|---|---|
| 1 | `provenance.py`, `build_evidence.py` | evidence corpus v1 + tiers | — |
| 2 | `dedupe.py` | duplicate groups | — |
| 3 | `codebook_v1.yaml` + `schema.py` | the codebook | — |
| 4 | `annotate.py` + gate pass | relevant subset | ~25 min |
| 5 | `canonicalise.py` | map CSV for review | ~2 min |
| 6 | codebook pass, **dev set only** (~940) | labels v1 for review | ~10 min |
| 7 | `sample_for_coding.py` | Amore's workbook | — |
| 8 | `validate.py` | agreement + stability | ~1 h |
| 9 | *(after review + pre-registration)* confirmatory run | labels final | ~40 min |

Steps 1–7 are the coding work. 8–9 need Amore's coded sample first.

---

## 8. Out of scope

- **"Top 10 supplements and their claims vs scientific claims."** Needs a
  structured evidence base (Cochrane, NAMS/IMS). Asking an LLM whether a health
  claim is scientifically supported is exactly the unverifiable judgement this
  redesign exists to remove. Separate literature workstream.
- Re-transcription. The source video files are gone from `/mnt`.
- Comments. Only counts were ever collected.
