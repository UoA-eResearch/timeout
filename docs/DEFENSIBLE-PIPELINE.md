# A defensible annotation pipeline for the menopause supplement corpus

**Status:** proposal, 2026-08-21. Written after the *Menopause Supplement Project*
meeting (Rebecca Slykerman, Amore Strauss, Nick Young, Nidhi Gowdra).
Nothing here is implemented yet.

**Audience:** the research team. Sections 1–3 are the argument; section 4 is the
design; section 5 is what goes in the paper's methods.

---

## 0. The problem in one paragraph

The current pipeline (`src/batch_LLM.py`) sends each video, base64-encoded, to
`nemotron_3_nano_omni` with one ~30-field prompt and stores whatever JSON comes
back. It works, and it has produced 12,213 labelled rows. But it fuses two very
different operations — *reading the video* and *judging the video* — into one
irreversible 10-hour call. That fusion is the source of every complaint raised in
the meeting: prompt changes are expensive, the ratings are unexplained, and the
whole thing is hard to describe in a methods section without a reviewer asking
"how do you know the model would say that again tomorrow?"

The fix is to split those two operations apart. Everything else follows.

---

## 1. Evidence that the current design has a reproducibility problem

These are measurements against the live endpoint and the committed spreadsheet,
not predictions.

### 1.1 The subjective 1–10 scales are not stable

`batch_LLM.py` runs at `temperature=0.6, top_p=0.95`. Sampling is on. To see what
that costs, the *same* transcript was sent 10 times with an identical prompt:

| temperature | `quality` across 10 identical runs | `menopause_framing` |
|---|---|---|
| **0.6** (current) | 10, 10, 10, 10, 5, 5, 3, 2, 1, 1 | `natural life stage` ×10 |
| **0.0** | 1 ×10 | `natural life stage` ×10 |

`usefulness` behaved the same way, spanning 1 to 10 across identical requests.

Two things follow. First, **the categorical variables are stable and the numeric
subjective scales are not** — the closed-vocabulary judgement is anchored by the
text, the 1–10 judgement is essentially resampled each time. Second, this is
fixable for free by setting `temperature=0`.

*Caveat, stated plainly:* this test used a short transcript and a three-field
prompt, not the full video call with all 30 fields. The full prompt may anchor
the model better. The test is cheap to repeat properly and **should be repeated
on the real pipeline before anything is published** — see §5.3.

### 1.2 The rating scales barely vary anyway

From the 12,213 committed rows:

| variable | mean | sd | modal value | share at mode |
|---|---|---|---|---|
| `quality` | 7.70 | 1.06 | 8 | **56%** |
| `usefulness` | 7.08 | 1.67 | 8 | **56%** |
| `misleading` | 2.46 | 1.76 | 1 | 37% (70% at 1–2) |

`quality` is very close to a constant. A variable where over half the corpus gets
the identical value, and where re-running moves individual scores by several
points, cannot carry a finding. Combined with §1.1 this is the single most
important thing to tell Rebecca: **the 1–10 scales are the weakest part of the
dataset, and they are the ones most likely to be challenged.**

The recommendation is not to delete them. It is to (a) pin temperature, (b)
replace bare 1–10 with a short ordinal scale with *defined anchors*
(e.g. 4 levels, each described in a sentence), and (c) report their
human-agreement statistic honestly alongside them.

### 1.3 Unconstrained JSON is leaking outside its own vocabulary

The prompt specifies closed lists. The output does not respect them:

| variable | categories offered | distinct values observed |
|---|---|---|
| `health_framework` | 7 | **13** (`holistic` ×404 alongside `naturopathic or holistic`) |
| `credentials` | 6 | **10** |
| `sentiment` | 3 + 1 | **7** |
| `content_type` | 3 | 4 (a casing duplicate) |
| `job` | closed list of 12 | **112** |
| `tone` | open-ended | **1,693** |
| `emotional_tone` | closed list of 14 | **521** combinations |

There is also field bleed: 4 rows have the *boolean* `menopause` column set to
`natural life stage` or `symptom burden or suffering` — values that belong to
`menopause_framing`. The model wrote into the wrong key and nothing caught it.

This is not a prompt-wording problem. It is a *decoding* problem, and it has a
mechanical fix (§4.2).

### 1.4 Most of the corpus is off-topic, and is being labelled anyway

- `menopause == False` for **7,501 of 12,213 rows (61%)**
- `supplements` is "no supplements mentioned" for **7,163 rows (59%)**
- **15.4%** of the corpus is not in English (Spanish 408, Italian 329,
  Portuguese 235, Hindi 160, …)

`src/Research_questions_report.py` already filters on `menopause == True` before
analysis, so these rows do not contaminate the published numbers — that part is
fine and should be kept.

The cost is elsewhere: **61% of a 10-hour inference run is spent producing labels
that are then discarded.** Worse, the discarded labels are confidently wrong
rather than empty. In a 60-video sample drawn for this document, one Italian
video about *bus timetables to Città Alta* was assigned
`menopause_framing: natural life stage` and
`health_framework: traditional chinese medicine`. The model had no evidence for
either and no way to say so, because every field was mandatory and no enum
included an "insufficient evidence" option.

### 1.5 There is no provenance on any row

A `*.result.json` file contains the answers and nothing else — no model version,
no prompt hash, no timestamp, no sampling parameters. And `process_file()` skips
any video whose result file already exists:

```python
if os.path.isfile(output_filename):
    return
```

Today that is harmless, because the last prompt change was followed by a full
regeneration (commit `7dc0a82`). But the mechanism is a trap: the next person who
edits the prompt and re-runs without manually wiping `supplements_results/` will
silently produce a spreadsheet mixing two prompt versions, with **no way to tell
which row came from which**. For a study that intends to iterate on prompts, this
is the highest-risk latent defect in the repo.

---

## 2. Why "put every question in one giant prompt" is the wrong answer

This was the working conclusion of the meeting, and it is understandable: if a
re-run costs 10 hours, you want to ask everything at once. Nick's advice —
"better to put in everything you could possibly want" — is correct *given the
current architecture*.

But it has three costs the meeting did not price in:

1. **Rebecca is forced to finalise her research questions before she has seen the
   data.** She said so herself: *"the possibilities would become more apparent"*
   as the project developed. A design that punishes learning is the wrong design
   for a project that is explicitly still learning.
2. **Long prompts degrade.** ~30 heterogeneous fields in one call means the model
   is transcribing, describing, extracting entities, and making six subjective
   judgements simultaneously. §1.3's vocabulary leakage is the visible symptom.
3. **It does not actually solve the peeking-forward problem** Nidhi raised. Asking
   all questions at once does not make it defensible to look at the answers and
   then change the questions. It just makes it more expensive to do so.

The real fix is to make re-running cheap. Then the constraint disappears and the
methodological question can be answered on its merits.

---

## 3. The key observation: the expensive part is not the part that changes

The corpus's full extracted text — transcripts plus AI visual descriptions —
is **16.8M characters, about 4.2M tokens** for all 12,213 videos. Median
transcript is 774 characters. These are 52-second videos.

That is a very small amount of text. The 10 hours is not spent on the judgements.
It is spent shipping base64 video over HTTP and running the audio-visual encoder.

**And the video only needs to be read once.** Transcripts and visual descriptions
do not change when Rebecca decides she also wants to know about menopause framing.

### Measured: a text-only annotation pass over the real corpus

60 real videos were drawn from the committed spreadsheet and re-annotated from
their stored `transcript` + `AI_description` + post metadata, with an
8-field schema-constrained prompt, at concurrency 12:

```
59/60 parsed OK in 32.3s   (0.54 s/video wall)
708 tokens/video
=> full 12,213-video corpus: ~110 minutes at concurrency 12
```

Concurrency 12 was chosen to be polite to a shared endpoint; text-only requests
are far lighter than video ones, so higher concurrency should cut this
substantially. Even unoptimised, **a full re-annotation drops from ~10 hours to
under 2**, and if the relevance gate (§4.1) runs first, only ~4,700 videos need
the full codebook — call it **under 45 minutes**.

That changes what is possible. Prompt iteration becomes something Rebecca and
Amore can do in an afternoon, together, watching the labels change.

### The honest caveat

In that same 60-video sample, text-only `content_type` agreed with the existing
video-based label on **36 of 59 (61%)**. That gap is real and has two possible
causes — the text-only pass is missing visual signal, or the original video-based
labels are themselves unstable (§1.1 suggests they might be). **We do not
currently know which**, and the proposal below does not assume an answer. It
makes the question measurable (§4.4) instead. If visual signal turns out to
matter for a given variable, that variable stays in Stage A.

---

## 4. The proposed pipeline

Four stages. The dividing line is: **Stage A describes, Stage B judges.**

```
                                                    ┌─────────────────────┐
  videos ──► [A] EXTRACT ──► evidence records ──┬──►│ [B] ANNOTATE        │──► labels
              once, ~10h      frozen, versioned │   │ cheap, re-runnable  │    v1, v2, v3…
              never re-run    a citable artifact│   │ schema-constrained  │
                                                │   └─────────────────────┘
                                                │            ▲
                                                │            │ codebook
                                                └──►[C] HUMAN CODING ──► agreement stats
                                                       Amore's sample
```

### 4.1 Stage A — extraction (expensive, run once, frozen)

One video pass producing only *descriptive* fields — things another person could
check against the video and agree on:

- `transcript` (verbatim, plus a separate `transcript_en` translation for the 15%
  non-English, kept as a distinct field so the translation step is visible)
- `visual_description`
- `on_screen_text` — currently not captured at all; for short-form video this is
  where product names and claims often live
- `speaker_self_description` — verbatim quotes of any credential claim, rather
  than a `credentials` judgement
- platform metadata as already collected

Plus **one gate**: `is_about_menopause` (boolean) and
`mentions_supplements` (boolean). Everything downstream filters on these, so 61%
of the corpus stops consuming inference after Stage A.

The output is a **frozen, versioned evidence corpus**. It gets a version tag, a
manifest with per-record hashes, and it is the thing you archive and cite. It is
never regenerated for a prompt change.

Optional but worth costing: run transcription through a dedicated ASR model
rather than the omni model. ASR has a standard, citable evaluation (WER against a
hand-transcribed sample) which makes the transcript itself defensible rather than
a black-box byproduct. There is ASR capacity on the `/mnt` inference server.

### 4.2 Stage B — annotation (cheap, text-only, versioned, re-runnable)

Reads evidence records, writes labels. Three rules:

**(a) Schema-constrained decoding, not prompt-instructed JSON.** The endpoint is
vLLM and supports it — verified working:

```python
extra_body={"response_format": {"type": "json_schema",
            "json_schema": {"name": "codebook", "schema": SCHEMA, "strict": True}}}
```

With `strict: True`, enum values are enforced at the decoder. All of §1.3
disappears by construction: no `holistic`-vs-`naturopathic or holistic` split, no
1,693 distinct tones, no field bleed.

> ⚠️ `extra_body={"guided_json": ...}` is **silently ignored** by this endpoint —
> it returns free prose and no error. Tested and confirmed. Use `response_format`.

**(b) Every enum gets an `insufficient evidence` member, and every judgement gets
an `evidence_span`** — a verbatim quote from the transcript justifying the label.
This is the direct answer to Rebecca's explainability ask, and it is *checkable*:
if the span isn't in the transcript, the label is suspect. In the 60-video sample
this immediately exposed the Città Alta bus video, because its evidence span was
about bus timetables.

**(c) `temperature=0`, pinned seed, and full provenance on every row:** model id,
model revision, prompt file hash, schema hash, sampling parameters, timestamp,
evidence-corpus version. Written into the output record, not a README.

The prompt lives in a **version-controlled codebook file**, not in a Python
f-string. It is the same document Amore's human coders work from — see §4.3 —
and a version of it goes in the paper's supplementary material.

Result files are keyed `{video_id}__{codebook_version}.json`, which makes the
`if os.path.isfile(...): return` skip *correct* instead of dangerous: it skips
work already done at this codebook version, and re-runs everything when the
codebook changes.

### 4.3 Stage C — human coding as a first-class stage

Amore's checking is currently happening in a spreadsheet alongside the pipeline.
It should be *inside* it, because it is what makes the LLM labels defensible.

- **One codebook, two readers.** The same document defines the categories for the
  model and for the human coders. When Amore disagrees with a label, the fix is
  to sharpen the codebook definition — which improves both at once.
- **Stratified random sample**, drawn with a recorded seed, from the
  *menopause-relevant* subset. Something like 300–400 videos gets usefully tight
  confidence intervals on per-variable agreement.
- **Double-code a subset** (~100) with a second coder to establish
  *human–human* reliability first. This matters: you cannot ask whether the model
  agrees with humans until you know whether humans agree with each other.
  Report Krippendorff's α or Cohen's κ.
- **Then report model–human agreement per variable**, not as one headline number.
  Expect the picture from §1.1: high on `primary_focus` and
  `supplement_sentiment`, poor on `quality`.
- **Decide a threshold in advance** for which variables carry inferential claims
  and which are reported as descriptive only.

This also gives Rebecca the thing she said she'd find interesting in its own
right: *where and how* the model and the human diverge, as a finding.

### 4.4 Stage D — validation experiments

Three cheap runs that turn "we used an LLM" into a methods section:

1. **Test–retest.** Re-run Stage B on the human-coded sample 5 times at the
   production settings; report per-variable stability. This is §1.1 done properly.
2. **Modality ablation.** For the human-coded sample only, run the full video
   pass *and* the text-only pass; compare both against the human codes. This
   settles §3's open question — whether the 61% `content_type` gap is lost visual
   signal or baseline label noise — and tells you which variables genuinely need
   the video.
3. **Prompt-order / paraphrase sensitivity.** Re-run with the codebook fields
   reordered and the wording paraphrased. If labels move, the finding is an
   artefact of prompt wording, and you want to know that before a reviewer does.

None of these take more than an hour of compute on a few hundred videos.

---

## 5. What this gives the paper

### 5.1 On peeking forward

Nidhi's concern was correct, and cheap re-runs make it *solvable* rather than
just cheaper to ignore. Split the relevant corpus:

- a **development set** (~20%) where Rebecca and Amore iterate freely — refine
  the codebook, compare against human coding, change their minds as often as they
  like; and
- a **held-out confirmatory set** (~80%) which is annotated **once**, with the
  frozen codebook, after the analysis plan is registered.

Pre-register the analysis plan (OSF) before the confirmatory run. Then the
iteration Rebecca wants is not a problem to be hidden — it is a documented
development phase, which is exactly how content-analysis codebooks have always
been built.

### 5.2 On the "tree" structure

Rebecca asked for hierarchical categorisation: split into informative /
marketing / commentary, then measure tone within each branch.

**Do not implement this as a multi-pass LLM tree.** Extract flat, well-defined
variables in one Stage B pass, then do the tree deterministically in pandas at
analysis time. `content_type` and `primary_focus` already exist for exactly this.

Reasons: the subsetting becomes reproducible and reversible; a branching error at
the top does not propagate; and any grouping can be revisited without touching
the model. Only the *labelling* is model-dependent, and only that needs
validating. This is a simpler and stronger design than what was discussed in the
meeting.

### 5.3 The methods paragraph, in outline

Everything below is a direct consequence of the design above:

- corpus construction, search terms, and a **PRISMA-style flow diagram**
  (18,579 URLs found → 12,213 successfully downloaded and processed → 4,708
  menopause-relevant — the attrition is currently undocumented and a reviewer
  will ask)
- evidence extraction: model, version, settings, ASR validation (WER on a
  hand-checked sample)
- the codebook, as supplementary material, with version history
- annotation: model id and revision, `temperature=0`, seed, schema-constrained
  decoding, provenance per row
- reliability: human–human α, model–human α per variable, test–retest stability
- pre-registration link and the development/confirmatory split
- an explicit statement of which variables met threshold and which are reported
  descriptively only

### 5.4 What to say to Rebecca and Amore

The questions document they are assembling is still worth writing — but the
framing changes. It is no longer a one-shot list that must be complete before a
10-hour run. It is **the first draft of a codebook**, and the pipeline is built
to expect several drafts.

The one thing genuinely worth deciding early is which questions are *confirmatory*
(pre-registered, tested on held-out data) versus *exploratory* (reported as such).
That distinction has to be made before looking at the answers. Everything else can
be iterated.

---

## 6. Suggested order of work

1. `temperature=0` + provenance fields + `{video_id}__{codebook_version}` result
   keys. Small change to `batch_LLM.py`, removes the §1.5 trap immediately.
2. Split `batch_LLM.py` into `extract.py` (Stage A) and `annotate.py` (Stage B);
   back-fill an evidence corpus from the existing `*_results/` JSON so Stage B
   can be exercised today without re-downloading anything.
3. Schema-constrained decoding with `response_format`, plus `evidence_span` and
   `insufficient evidence` enum members.
4. Draw and freeze Amore's stratified sample; turn the questions document into
   codebook v0.1.
5. Run the three validation experiments in §4.4.
6. Pre-register; then the confirmatory run.

Steps 1–3 are a day or two of work and are worth doing regardless of what the
researchers decide about the rest.

---

## Appendix: things considered and rejected

- **Lexicon / dictionary methods** (raised in the meeting). Fully deterministic
  and trivially defensible, but for framing, tone and credentials the categories
  are not lexically marked — "natural life stage" framing has no keyword
  signature. Reasonable as a *supplementary* deterministic check on the
  supplement-mention variables, where the vocabulary really is closed.
- **Fine-tuning BERT on Amore's codes** (raised in the meeting). A ~350-video
  training set is too small for the number of variables, and it converts a
  transparent, promptable system into an opaque one — the opposite of what
  Rebecca asked for. Revisit only if a variable proves both important and
  unreliable under the LLM.
- **RLHF on the LLM** (raised in the meeting, and the option Rebecca liked most).
  What Rebecca actually described — "here are these posts and how they were
  rated, now apply that to the rest" — is **few-shot prompting with human-coded
  exemplars**, not RLHF. That is cheap, transparent, and fits Stage B directly:
  put 5–10 of Amore's coded examples in the codebook prompt. It should be tried,
  and it is not the same thing as tuning model weights. True RLHF is not
  warranted here.
- **Keeping the monolithic prompt and just adding fields.** The meeting's
  conclusion; rejected for the reasons in §2.
- **Discarding the 1–10 scales entirely.** Tempting given §1.2, but they may
  become usable with defined anchors and `temperature=0`. Measure first (§4.4),
  then decide.
