#!/usr/bin/env python3
"""Provenance stamping.

Every annotated row carries enough information to answer "what produced this
value?" without consulting anyone's memory: which model build, which codebook
version, which prompt text, which sampling settings, when.

The previous pipeline stored none of this, and skipped any video whose result
file already existed -- so editing the prompt and re-running would silently
produce a spreadsheet mixing two prompt versions with no way to tell rows apart.
Output files here are keyed by codebook version, which makes that skip correct
instead of dangerous.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import platform
import socket
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://ai.cer-sandbox.cloud.edu.au/v1"
MODEL = "nemotron_3_nano_omni"

# Deterministic decoding. The previous pipeline ran at temperature=0.6, where
# the same transcript scored 1,1,2,3,5,5,10,10,10,10 on `quality` across ten
# identical requests. See docs/DEFENSIBLE-PIPELINE.md section 1.1.
TEMPERATURE = 0.0
TOP_P = 1.0
SEED = 20260821

# Per-request ceiling. Without one, a hung connection parks a worker indefinitely
# and a thread pool silently stalls mid-run.
#
# Set generously on purpose. The endpoint is shared, and when another tenant
# saturates it a single 8-token request has been observed taking 108s. A tight
# timeout in that state makes things strictly worse: every request is abandoned
# just before it would have returned, and the retries add load without ever
# completing. Better to queue than to churn.
REQUEST_TIMEOUT_S = 300.0


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git_commit(repo: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def model_revision(base_url: str = BASE_URL) -> str:
    """The served model's build stamp, so a silent server-side swap is visible."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{base_url}/models", timeout=15) as fh:
            data = json.load(fh)
        entry = data["data"][0]
        return f"{entry['id']}@created={entry.get('created', 'unknown')}"
    except Exception as exc:  # pragma: no cover - network dependent
        return f"unavailable ({type(exc).__name__})"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class RunProvenance:
    """Stamped once per run; the per-row fields are a subset of this."""

    pass_name: str
    codebook_version: str
    schema_hash: str
    prompt_hash: str
    model: str = MODEL
    model_revision: str = ""
    base_url: str = BASE_URL
    temperature: float = TEMPERATURE
    top_p: float = TOP_P
    seed: int = SEED
    evidence_version: str = ""
    evidence_manifest_sha: str = ""
    started_at: str = field(default_factory=utcnow)
    git_commit: str = ""
    host: str = field(default_factory=socket.gethostname)
    user: str = field(default_factory=lambda: _safe_user())
    python: str = field(default_factory=platform.python_version)

    def __post_init__(self) -> None:
        if not self.model_revision:
            self.model_revision = model_revision(self.base_url)

    def row_fields(self) -> dict:
        """The subset stamped onto every output row."""
        return {
            "prov_model": self.model,
            "prov_model_revision": self.model_revision,
            "prov_temperature": self.temperature,
            "prov_seed": self.seed,
            "prov_codebook_version": self.codebook_version,
            "prov_schema_hash": self.schema_hash,
            "prov_prompt_hash": self.prompt_hash,
            "prov_evidence_version": self.evidence_version,
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["finished_at"] = utcnow()
        path.write_text(json.dumps(payload, indent=2))


def _safe_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"
