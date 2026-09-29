"""The reasoning half of the detection arm.

Some faults have a dedicated detector and some do not, and the split is the
point (`docs/evaluation-plan.md` §3.4). A mesh with severe non-orthogonality
trips `assess_mesh_quality`; a mesh that clears checkMesh while sitting
above the limit snappyHexMesh accepts trips nothing at all. Catching the
second is judgement, and judgement is what changes when the model changes —
so recall on these probes is the model-attributable share, while recall on
the tool probes is the engineering-attributable share.

The probe is deliberately narrow. The model sees the case's artefacts and
one question, with no case history, no scenario, and no hint that a fault
might be present — the clean controls are indistinguishable in framing from the
faulty ones, which is the only way a false-alarm rate means anything. It
answers in a fixed JSON shape so scoring never depends on parsing prose.

Any OpenAI-compatible endpoint serves it, so the same probes run against a
local vLLM server and a hosted API and stay comparable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

QUESTION = """\
You are reviewing an OpenFOAM case before it is handed to a researcher.

Below are the artefacts from that case. Decide whether anything in them
should stop the run or be raised with the researcher before proceeding.

Judge only what the artefacts show. Many cases are fine; say so when they
are. Answer with a single JSON object and nothing else:

{"concern": true or false,
 "target": "the specific metric, field, or setting at issue, or null",
 "reason": "one sentence"}

%(content)s"""

ARTEFACT_BLOCK = """\
--- artefact: %(name)s ---
%(content)s
--- end of artefact ---
"""

# Reasoning traces, which several open models emit before their answer.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK_RE = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)
# Non-greedy, and applied to the last candidate: a reply often contains
# braces inside its reasoning, and a greedy match would span from the
# first brace of the thinking to the last brace of the answer.
_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


class ChatModel(Protocol):
    """The one call this module needs from a model backend."""

    def ask(self, prompt: str) -> str: ...


@dataclass
class OpenAICompatibleModel:
    """A model served over the OpenAI chat-completions API."""

    base_url: str
    model: str
    api_key: str = "local"
    temperature: float = 0.0
    # Reasoning models spend their budget thinking before they answer. At
    # 400 tokens two qwen3 variants returned empty content for every probe
    # and scored zero recall — a budget artefact that would have read as a
    # model that never noticed anything. The answer itself is one short
    # JSON object; the headroom is for the thinking in front of it.
    max_tokens: int = 4096

    def ask(self, prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content or ""


def parse_answer(text: str) -> dict[str, Any]:
    """Read the model's verdict out of its reply.

    A reply that cannot be parsed is recorded as unparseable rather than
    read as "no concern" — silently counting a malformed answer as a clean
    verdict would credit the model for a miss it never actually made.
    """
    raw = text or ""
    # Strip the reasoning trace first, so its braces cannot be mistaken for
    # the answer. An unterminated block means the model ran out of budget
    # mid-thought and never answered at all.
    body = _UNCLOSED_THINK_RE.sub("", _THINK_RE.sub("", raw)).strip()

    candidates = _JSON_RE.findall(body)
    payload = None
    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "concern" in parsed:
            payload = parsed
            break
    if payload is None:
        return {
            "parsed": False,
            "concern": None,
            "target": None,
            "reason": (body or raw)[:200],
        }
    concern = payload.get("concern")
    return {
        "parsed": True,
        "concern": bool(concern) if isinstance(concern, bool) else None,
        "target": payload.get("target"),
        "reason": str(payload.get("reason", ""))[:300],
    }


def _mentions(target: Any, localization: str, reason: str) -> bool:
    """Did the answer name the right thing?

    Matched on the words of the localisation key rather than the key
    itself, since a model writes "non-orthogonality", not
    "max_non_orthogonality".
    """
    if not localization:
        return False
    haystack = f"{target or ''} {reason or ''}".lower().replace("-", "_")
    tokens = [t for t in localization.lower().split("_") if len(t) > 2]
    return bool(tokens) and all(t in haystack for t in tokens)


def run_reasoning_probe(probe: Any, model: ChatModel, workdir: Path) -> dict[str, Any]:
    """Show the probe's artefacts to the model and score its answer."""
    case = workdir / probe.probe_id
    probe.write(case)
    # Every file the probe writes, not just the primary one. Some faults are
    # a mismatch between two artefacts — y+ values are only wrong relative to
    # the turbulence model that has to live with them — and showing the model
    # half of the evidence the tool reads would measure the harness rather
    # than the model.
    names = [probe.artefact, *sorted(probe.files)]
    blocks = "\n".join(
        ARTEFACT_BLOCK
        % {"name": name, "content": (case / name).read_text(encoding="utf-8")}
        for name in names
    )
    prompt = QUESTION % {"content": blocks}

    try:
        reply = model.ask(prompt)
        error = ""
    except Exception as exc:
        reply, error = "", f"{type(exc).__name__}: {exc}"

    answer = parse_answer(reply) if not error else {
        "parsed": False,
        "concern": None,
        "target": None,
        "reason": error,
    }
    detected = bool(answer["concern"])
    return {
        "probe_id": probe.probe_id,
        "fault_class": probe.fault_class,
        "fault_present": probe.fault_present,
        "expected_detector": probe.expected_detector,
        "tool_detectable": probe.tool_detectable,
        "detected": detected,
        "localised": bool(
            detected
            and _mentions(answer["target"], probe.localization, answer["reason"])
        ),
        "parsed": answer["parsed"],
        "target": answer["target"],
        "reason": answer["reason"],
        "error": error,
    }
