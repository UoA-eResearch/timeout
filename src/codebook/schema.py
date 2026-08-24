#!/usr/bin/env python3
"""Compile codebook_v1.yaml into JSON Schemas and prompts.

The codebook YAML is the single source of truth. This module turns it into:

  * a JSON Schema per pass, handed to vLLM as ``response_format`` with
    ``strict: True`` so enum values are enforced *at the decoder*. The model
    physically cannot emit a category that is not in the codebook.
  * the prompt text, generated from the same definitions the human coders read.

Why constrained decoding rather than asking nicely in the prompt: the previous
pipeline asked nicely and got 13 values for a 7-category variable, 112 values
for a closed 12-item list, and framing text written into a boolean field.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

CODEBOOK_PATH = Path(__file__).with_name("codebook_v1.yaml")


def load(path: Path | str = CODEBOOK_PATH) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


# --------------------------------------------------------------------------
# JSON Schema construction
# --------------------------------------------------------------------------

def _values(var: dict, insufficient: str) -> list[str]:
    """Enum members for a variable, always including the escape hatch.

    Every categorical variable can answer "insufficient evidence". Without it a
    mandatory field forces the model to invent a category for content that does
    not support one -- which is exactly how an Italian video about bus
    timetables acquired a traditional-chinese-medicine label.
    """
    vals = [v["value"] for v in var["values"]]
    if insufficient not in vals:
        vals.append(insufficient)
    return vals


def _field(var: dict, insufficient: str) -> dict[str, Any]:
    kind = var["type"]
    if kind == "boolean":
        return {"type": "boolean"}
    if kind in ("quote", "verbatim"):
        return {"type": "string", "maxLength": 400}
    if kind == "enum":
        return {"type": "string", "enum": _values(var, insufficient)}
    if kind == "multi_enum":
        return {
            "type": "array",
            "items": {"type": "string", "enum": _values(var, insufficient)},
            "minItems": 1,
            "maxItems": var.get("max_items", 5),
        }
    raise ValueError(f"unknown variable type {kind!r} for {var['name']}")


def _obj(props: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


def gate_schema(cb: dict) -> dict:
    ins = cb["insufficient"]
    props = {v["name"]: _field(v, ins) for v in cb["gate"]["variables"]}
    return _obj(props, list(props))


def codebook_schema(cb: dict) -> dict:
    """Video-level fields plus a nested per-supplement ``claims`` array.

    The nesting is required by the research questions: claim type, strength and
    evidence are asked *per supplement*, and a video can make a strong cure
    claim about one product while mentioning another in passing. The array is
    flattened to pipe-separated aligned columns on delivery (one row per video).
    """
    ins = cb["insufficient"]
    props: dict[str, Any] = {}
    for var in cb["video_level"]["variables"]:
        props[var["name"]] = _field(var, ins)
        if var.get("evidence"):
            props[f"{var['name']}_evidence"] = {"type": "string", "maxLength": 400}

    claim_props = {v["name"]: _field(v, ins) for v in cb["per_supplement"]["variables"]}
    props["claims"] = {
        "type": "array",
        "items": _obj(claim_props, list(claim_props)),
        "maxItems": cb["per_supplement"].get("max_items", 12),
    }
    return _obj(props, list(props))


# --------------------------------------------------------------------------
# Prompt construction -- generated from the same definitions coders read
# --------------------------------------------------------------------------

def _render_var(var: dict, insufficient: str) -> str:
    head = f"{var['name']}: {var['question'].strip()}"
    if var["type"] in ("enum", "multi_enum"):
        lines = [f"  - {v['value']}: {v['definition']}" for v in var["values"]]
        lines.append(f"  - {insufficient}: the evidence does not let you decide.")
        head += "\n" + "\n".join(lines)
    if var.get("evidence"):
        head += f"\n{var['name']}_evidence: quote the exact words justifying your choice."
    return head


def gate_prompt(cb: dict) -> str:
    ins = cb["insufficient"]
    body = "\n\n".join(_render_var(v, ins) for v in cb["gate"]["variables"])
    return f"{cb['gate']['instructions'].strip()}\n\n{body}"


def codebook_prompt(cb: dict) -> str:
    ins = cb["insufficient"]
    vid = "\n\n".join(_render_var(v, ins) for v in cb["video_level"]["variables"])
    sup = "\n\n".join(_render_var(v, ins) for v in cb["per_supplement"]["variables"])
    return (
        f"{cb['video_level']['instructions'].strip()}\n\n"
        f"=== VIDEO-LEVEL FIELDS ===\n\n{vid}\n\n"
        f"=== PER-SUPPLEMENT FIELDS (the `claims` array) ===\n\n"
        f"{cb['per_supplement']['instructions'].strip()}\n\n{sup}"
    )


# --------------------------------------------------------------------------
# Hashing -- what makes a row's provenance checkable
# --------------------------------------------------------------------------

def sha(obj: Any) -> str:
    text = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def build(pass_name: str, path: Path | str = CODEBOOK_PATH) -> dict:
    """Return everything annotate.py needs for one pass, with hashes."""
    cb = load(path)
    if pass_name == "gate":
        schema, prompt = gate_schema(cb), gate_prompt(cb)
    elif pass_name == "codebook":
        schema, prompt = codebook_schema(cb), codebook_prompt(cb)
    else:
        raise ValueError(f"unknown pass {pass_name!r}")
    return {
        "pass": pass_name,
        "codebook_version": cb["version"],
        "schema": schema,
        "prompt": prompt,
        "schema_hash": sha(schema),
        "prompt_hash": sha(prompt),
        "codebook": cb,
    }


if __name__ == "__main__":
    import sys

    which = sys.argv[1] if len(sys.argv) > 1 else "codebook"
    built = build(which)
    print(f"# pass={built['pass']} codebook={built['codebook_version']}")
    print(f"# schema_hash={built['schema_hash']} prompt_hash={built['prompt_hash']}")
    print(built["prompt"])
