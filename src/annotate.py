#!/usr/bin/env python3
"""Stage B -- annotate the evidence corpus against the codebook.

Two passes:

  --pass gate       cheap two-field relevance screen over the whole corpus
  --pass codebook   full codebook, only on videos the gate passed

Both use schema-constrained decoding (``response_format`` with a JSON Schema and
``strict: True``), which enforces enum membership at the decoder. This is what
stops the vocabulary leakage the previous pipeline suffered: 13 values for a
7-category variable, 112 for a closed 12-item list, framing text landing in a
boolean field.

NOTE: ``extra_body={"guided_json": ...}`` is SILENTLY IGNORED by this endpoint --
it returns free prose and no error. Use response_format, as below.

Results are written as JSONL keyed by codebook version, so runs at different
codebook versions cannot mix, and an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from openai import OpenAI
from tqdm import tqdm

import provenance as prov
from codebook.schema import build as build_pass

REPO = Path(__file__).resolve().parent.parent

# Truncation limits. Chosen from the corpus distribution -- p95 transcript is
# 2,191 characters, so 6,000 truncates almost nothing while bounding the tail.
LIMITS = {"title": 300, "post_text": 2000, "transcript": 6000, "visual_description": 2000}


def render_evidence(row: pd.Series, include_visual: bool) -> str:
    """The exact text shown to the model. Nothing else reaches the prompt.

    Engagement counts and upload dates are absent by construction -- they are
    the study's outcome variables and feeding them in would make the
    "engagement vs credibility" question circular.
    """
    parts = [
        "=== EVIDENCE ===",
        f"PLATFORM: {row['platform']}",
        f"CHANNEL NAME: {row['channel_name'] or '(unknown)'}",
        f"DURATION: {int(row['duration_s']) if pd.notna(row['duration_s']) else 'unknown'} seconds",
        f"TITLE: {str(row['title'])[:LIMITS['title']]}",
        f"POST TEXT: {str(row['post_text'])[:LIMITS['post_text']] or '(none)'}",
    ]
    if include_visual and "visual_description" in row:
        parts.append(f"VISUAL DESCRIPTION: {str(row['visual_description'])[:LIMITS['visual_description']]}")
    transcript = str(row["transcript"])[:LIMITS["transcript"]]
    parts.append(f"TRANSCRIPT: {transcript or '(no spoken content)'}")
    return "\n".join(parts)


class Annotator:
    def __init__(self, built: dict, run: prov.RunProvenance, include_visual: bool = False):
        self.built = built
        self.run = run
        self.include_visual = include_visual
        # An explicit per-request timeout matters more than it looks: without one a
        # hung connection parks a worker forever, and with a thread pool that quietly
        # stalls the whole run. Retries are ours, so the client does none.
        self.client = OpenAI(base_url=prov.BASE_URL, api_key="not needed",
                             timeout=prov.REQUEST_TIMEOUT_S, max_retries=0)
        self.lock = threading.Lock()
        self.failures: list[dict] = []

    def _request(self, evidence_text: str) -> dict:
        response = self.client.chat.completions.create(
            model=self.run.model,
            messages=[{"role": "user", "content": f"{self.built['prompt']}\n\n{evidence_text}"}],
            max_tokens=4096,
            temperature=self.run.temperature,
            top_p=self.run.top_p,
            seed=self.run.seed,
            extra_body={
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": self.built["pass"],
                        "schema": self.built["schema"],
                        "strict": True,
                    },
                },
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        return json.loads(response.choices[0].message.content)

    def annotate_row(self, row: pd.Series) -> dict | None:
        evidence_text = render_evidence(row, self.include_visual)
        last_error = "unknown"
        for _ in range(3):
            try:
                result = self._request(evidence_text)
                if self.built["pass"] == "codebook":
                    check = validate_claims(result)
                    if check:
                        last_error = check
                        continue
                return {
                    "video_id": row["video_id"],
                    "evidence_sha": row["evidence_sha"],
                    **result,
                    **self.run.row_fields(),
                }
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
        # Quarantined rather than silently written with partial values.
        with self.lock:
            self.failures.append({"video_id": row["video_id"], "error": last_error})
        return None


def validate_claims(result: dict) -> str:
    """Reject a nested result whose claims array is internally inconsistent.

    Schema-constrained decoding guarantees enum membership; it does not
    guarantee the model filled a claim entry meaningfully. A row failing this is
    retried and then quarantined -- never written half-formed.
    """
    claims = result.get("claims", [])
    if not isinstance(claims, list):
        return "claims is not a list"
    for i, claim in enumerate(claims):
        name = str(claim.get("supplement_name_raw", "")).strip()
        if not name:
            return f"claim {i} has an empty supplement_name_raw"
    return ""


def flatten(record: dict, per_supplement_fields: list[str]) -> dict:
    """Nested claims -> pipe-separated aligned lists, one row per video.

    The lists are index-aligned: position i of every claim_* column describes
    the same supplement as position i of supplements_raw. This matches the
    convention the researchers already read in the existing spreadsheet.
    """
    row = {k: v for k, v in record.items() if k != "claims"}
    claims = record.get("claims", []) or []
    for field in per_supplement_fields:
        key = "supplements_raw" if field == "supplement_name_raw" else field
        row[key] = " | ".join(str(c.get(field, "")).replace("|", "/") for c in claims)
    row["n_supplements"] = len(claims)
    for key, value in list(row.items()):
        if isinstance(value, list):
            row[key] = " | ".join(str(v) for v in value)
    return row


def run_pass(
    pass_name: str, evidence: pd.DataFrame, out_dir: Path,
    workers: int, limit: int | None, include_visual: bool,
    rebuild_only: bool = False,
) -> pd.DataFrame:
    built = build_pass(pass_name)
    manifest = json.loads((REPO / "data/evidence/v1/manifest.json").read_text())
    run = prov.RunProvenance(
        pass_name=pass_name,
        codebook_version=built["codebook_version"],
        schema_hash=built["schema_hash"],
        prompt_hash=built["prompt_hash"],
        evidence_version=manifest["evidence_version"],
        evidence_manifest_sha=manifest["corpus_sha256"][:16],
        git_commit=prov.git_commit(REPO),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{pass_name}_cb{built['codebook_version']}"
    jsonl_path = out_dir / f"{tag}.jsonl"

    done: set[str] = set()
    if jsonl_path.exists():
        with open(jsonl_path) as fh:
            for line in fh:
                try:
                    done.add(json.loads(line)["video_id"])
                except Exception:
                    continue
        print(f"resuming: {len(done):,} rows already annotated at codebook {built['codebook_version']}")

    todo = evidence[~evidence["video_id"].isin(done)]
    if limit:
        todo = todo.head(limit)
    if rebuild_only:
        # Re-derive the table from rows already on disk, without calling the API.
        # Useful to inspect an interrupted run, or to recover the parquet after a
        # crash, since the JSONL is the durable record and the parquet is derived.
        todo = todo.head(0)
        print("rebuild-only: deriving the table from existing JSONL, no requests")
    print(f"{pass_name}: {len(todo):,} to annotate "
          f"(model={run.model_revision}, temp={run.temperature}, seed={run.seed})")

    annotator = Annotator(built, run, include_visual)
    if len(todo):
        with open(jsonl_path, "a") as sink:
            with ThreadPoolExecutor(workers) as pool:
                iterator = pool.map(annotator.annotate_row, (r for _, r in todo.iterrows()))
                for result in tqdm(iterator, total=len(todo), desc=pass_name):
                    if result is None:
                        continue
                    with annotator.lock:
                        sink.write(json.dumps(result) + "\n")
                        sink.flush()

    records = [json.loads(l) for l in open(jsonl_path)] if jsonl_path.exists() else []
    if pass_name == "codebook":
        cb = built["codebook"]
        fields = [v["name"] for v in cb["per_supplement"]["variables"]]
        records = [flatten(r, fields) for r in records]
    else:
        records = [flatten(r, []) for r in records]

    frame = pd.DataFrame(records).drop_duplicates("video_id", keep="last")
    frame.to_parquet(out_dir / f"{tag}.parquet", index=False)
    run.write(out_dir / f"{tag}.provenance.json")

    if annotator.failures:
        pd.DataFrame(annotator.failures).to_csv(out_dir / f"{tag}.quarantine.csv", index=False)
        print(f"QUARANTINED {len(annotator.failures)} rows -> {tag}.quarantine.csv")
    print(f"{pass_name}: {len(frame):,} rows -> {out_dir / (tag + '.parquet')}")
    return frame


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pass", dest="pass_name", choices=["gate", "codebook"], required=True)
    ap.add_argument("--evidence", type=Path, default=REPO / "data/evidence/v1/evidence.parquet")
    ap.add_argument("--out", type=Path, default=REPO / "data/labels")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--include-visual", action="store_true")
    ap.add_argument("--dev-only", action="store_true", help="restrict to the 20%% development split")
    ap.add_argument("--rebuild-only", action="store_true",
                    help="rebuild the parquet from existing JSONL without calling the API")
    args = ap.parse_args()

    ev = pd.read_parquet(args.evidence)

    # Tier C has neither a transcript nor post text. It is never annotated;
    # it is reported as an exclusion instead.
    ev = ev[ev["evidence_tier"].isin(["A", "B"])]

    if args.pass_name == "codebook":
        gate_path = args.out / "gate_cb1.0.0.parquet"
        if not gate_path.exists():
            raise SystemExit("run --pass gate first")
        gate = pd.read_parquet(gate_path)
        keep = set(gate.loc[gate["is_about_menopause"] == True, "video_id"])  # noqa: E712
        ev = ev[ev["video_id"].isin(keep)]
        print(f"gate passed {len(keep):,} videos; {len(ev):,} present in evidence")

    if args.dev_only:
        ev = ev.sample(frac=0.2, random_state=prov.SEED)
        print(f"development split only: {len(ev):,} videos")

    run_pass(args.pass_name, ev, args.out, args.workers, args.limit, args.include_visual,
             args.rebuild_only)


if __name__ == "__main__":
    main()
