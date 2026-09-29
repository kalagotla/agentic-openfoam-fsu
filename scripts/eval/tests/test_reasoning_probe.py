"""Tests for the model-judged detection arm.

Driven by scripted models rather than a live endpoint, so the scoring is
pinned without a network. The cases that matter most are the degenerate
ones: a model that answers in prose, one that errors, and one that agrees
with everything. Each would quietly corrupt a recall number if handled
carelessly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from faults.injectors import Probe, clean_mesh, severe_non_orthogonality
from probe_runner import run_all, score
from reasoning_probe import parse_answer, run_reasoning_probe


class ScriptedModel:
    """Returns a fixed reply, and records what it was asked."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class BrokenModel:
    def ask(self, prompt: str) -> str:
        raise ConnectionError("endpoint unreachable")


def answer(concern: bool, target: str | None = None, reason: str = "") -> str:
    return json.dumps({"concern": concern, "target": target, "reason": reason})


# ---------------------------------------------------------------------------
# Parsing the reply
# ---------------------------------------------------------------------------


def test_a_clean_json_answer_is_read() -> None:
    parsed = parse_answer(answer(True, "max_non_orthogonality", "78 degrees is severe"))
    assert parsed["parsed"] is True
    assert parsed["concern"] is True
    assert parsed["target"] == "max_non_orthogonality"


def test_json_wrapped_in_chatter_is_still_read() -> None:
    # Models preface answers. The verdict is still in there.
    reply = "Sure! Here is my assessment:\n\n" + answer(False, None, "looks fine") + "\n"
    assert parse_answer(reply)["concern"] is False


def test_prose_without_json_is_unparseable_not_clean() -> None:
    parsed = parse_answer("The mesh looks fine to me, no concerns at all.")
    # Reading this as "no concern" would credit the model with a correct
    # clean verdict it never actually gave in the required form.
    assert parsed["parsed"] is False
    assert parsed["concern"] is None


def test_json_missing_the_verdict_field_is_unparseable() -> None:
    assert parse_answer('{"target": "skewness"}')["parsed"] is False


def test_empty_reply_is_unparseable() -> None:
    assert parse_answer("")["parsed"] is False


# ---------------------------------------------------------------------------
# Scoring one probe
# ---------------------------------------------------------------------------


def test_a_correct_catch_is_detected_and_localised(tmp_path: Path) -> None:
    model = ScriptedModel(
        answer(True, "non-orthogonality", "Max non-orthogonality of 78.4 is severe")
    )
    result = run_reasoning_probe(severe_non_orthogonality(), model, tmp_path)
    assert result["detected"] is True
    assert result["localised"] is True


def test_a_vague_catch_is_detected_but_not_localised(tmp_path: Path) -> None:
    model = ScriptedModel(answer(True, "something", "This mesh looks bad"))
    result = run_reasoning_probe(severe_non_orthogonality(), model, tmp_path)
    # Noticing and diagnosing are different capabilities, and the ladder
    # keeps them apart.
    assert result["detected"] is True
    assert result["localised"] is False


def test_a_miss_is_recorded(tmp_path: Path) -> None:
    model = ScriptedModel(answer(False, None, "Mesh looks acceptable"))
    assert run_reasoning_probe(severe_non_orthogonality(), model, tmp_path)["detected"] is False


def test_a_false_alarm_on_a_clean_probe_is_recorded(tmp_path: Path) -> None:
    model = ScriptedModel(answer(True, "aspect ratio", "Concerned about the mesh"))
    result = run_reasoning_probe(clean_mesh(), model, tmp_path)
    assert result["fault_present"] is False
    assert result["detected"] is True


def test_a_backend_failure_is_data_not_a_crash(tmp_path: Path) -> None:
    result = run_reasoning_probe(severe_non_orthogonality(), BrokenModel(), tmp_path)
    assert result["detected"] is False
    assert "ConnectionError" in result["error"]
    assert result["parsed"] is False


def test_the_model_sees_the_artefact_and_no_hint_of_the_answer(tmp_path: Path) -> None:
    model = ScriptedModel(answer(False))
    probe = severe_non_orthogonality()
    run_reasoning_probe(probe, model, tmp_path)
    prompt = model.prompts[0]
    assert "78.4" in prompt  # the artefact itself
    # Nothing that reveals a fault was planted, or which one. A clean
    # control has to be indistinguishable in framing, or the false-alarm
    # rate means nothing.
    for leak in ("fault", "injected", "severe non-orthogonality probe", probe.probe_id):
        assert leak not in prompt


# ---------------------------------------------------------------------------
# The whole arm
# ---------------------------------------------------------------------------


def test_a_yes_model_scores_perfect_recall_and_is_caught_by_the_controls() -> None:
    result = run_all(model=ScriptedModel(answer(True, "everything", "concerned")))
    s = result["summary"]
    assert result["arm"] == "model"
    assert s["recall"]["point"] == 1.0
    # The whole reason recall never travels alone.
    assert s["false_alarm_rate"]["point"] == 1.0


def test_a_no_model_scores_zero_recall_and_no_false_alarms() -> None:
    s = run_all(model=ScriptedModel(answer(False)))["summary"]
    assert s["recall"]["point"] == 0.0
    assert s["false_alarm_rate"]["point"] == 0.0


def test_the_model_arm_covers_probes_the_tool_arm_cannot() -> None:
    tool = run_all()["summary"]
    model = run_all(model=ScriptedModel(answer(True, "x", "y")))["summary"]
    # The reasoning-only probe sits out of the tool arm and is scored in
    # the model arm, so the model arm's denominator is larger.
    assert model["n_run"] > tool["n_run"]
    assert tool["n_not_run"] >= 1
    assert model["n_not_run"] == 0


def test_both_arms_score_the_same_probes_comparably() -> None:
    # The point of running every probe through both: the tool-attributable
    # and model-attributable shares of detection are otherwise guesswork.
    tool = run_all()
    model = run_all(model=ScriptedModel(answer(True, "x", "y")))
    tool_ids = {o["probe_id"] for o in tool["outcomes"]}
    model_ids = {o["probe_id"] for o in model["outcomes"]}
    assert tool_ids == model_ids


@pytest.mark.parametrize(
    "reply", ["not json at all", "", '{"concern": "maybe"}', "{broken json"]
)
def test_unusable_replies_never_count_as_a_catch(reply: str, tmp_path: Path) -> None:
    result = run_reasoning_probe(severe_non_orthogonality(), ScriptedModel(reply), tmp_path)
    assert result["detected"] is False
    assert result["localised"] is False


def test_scoring_ignores_probes_the_arm_did_not_run() -> None:
    from probe_runner import ProbeOutcome

    ran = ProbeOutcome("a", "mesh", True, "assess_mesh_quality", True, True, True, "ok")
    skipped = ProbeOutcome(
        "b", "mesh", True, "reasoning", False, False, False, "not run in this arm"
    )
    s = score([ran, skipped])
    # The skipped probe must not depress recall — it was never asked.
    assert s["recall"]["point"] == 1.0
    assert s["n_not_run"] == 1


def test_the_model_sees_every_artefact_the_tool_reads(tmp_path: Path) -> None:
    # A y+ fault lives in the pairing of two files: the turbulence model and
    # the wall data. Showing the model only the first would score the harness,
    # not the model — it would have no way to answer.
    probe = Probe(
        probe_id="pairing",
        fault_class="physics",
        fault_present=True,
        expected_detector="assess_y_plus",
        artefact="constant/turbulenceProperties",
        content="RASModel        kEpsilon;\n",
        files={"postProcessing/yPlus/1000/yPlus.dat": "1000 walls 0.4 2.1 1.2\n"},
    )
    seen: list[str] = []

    class Recorder:
        def ask(self, prompt: str) -> str:
            seen.append(prompt)
            return '{"concern": true, "target": "y+", "reason": "sublayer"}'

    run_reasoning_probe(probe, Recorder(), tmp_path)
    assert "kEpsilon" in seen[0]
    assert "2.1" in seen[0]
    assert "postProcessing/yPlus/1000/yPlus.dat" in seen[0]
