"""Tests for the run ledger in `scripts/run_agent.py`.

The ledger is where a run's cost stops being an estimate. It has to absorb
two different usage shapes — Anthropic's ``input_tokens`` / ``output_tokens``
and the OpenAI-compatible ``prompt_tokens`` / ``completion_tokens`` Ollama
returns — because the portability claim only means something if an
Anthropic run and a local run are counted on the same axes.
"""

from __future__ import annotations

from types import SimpleNamespace

from run_agent import RunLedger


def ledger() -> RunLedger:
    return RunLedger(backend="anthropic", model="test-model", prompt="do the thing")


def test_anthropic_usage_shape_is_absorbed() -> None:
    led = ledger()
    led.record_usage(
        SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            cache_read_input_tokens=5,
            cache_creation_input_tokens=7,
        )
    )
    d = led.to_dict()
    assert d["input_tokens"] == 100
    assert d["output_tokens"] == 20
    assert d["cache_read_tokens"] == 5
    assert d["cache_write_tokens"] == 7


def test_openai_usage_shape_is_absorbed() -> None:
    led = ledger()
    led.record_usage(SimpleNamespace(prompt_tokens=300, completion_tokens=40))
    d = led.to_dict()
    assert d["input_tokens"] == 300
    assert d["output_tokens"] == 40


def test_usage_accumulates_across_iterations() -> None:
    led = ledger()
    for _ in range(3):
        led.record_usage({"input_tokens": 10, "output_tokens": 1})
    assert led.to_dict()["input_tokens"] == 30


def test_absent_usage_is_survivable() -> None:
    # A backend that returns no usage block must not crash the run.
    led = ledger()
    led.record_usage(None)
    assert led.to_dict()["input_tokens"] == 0


def test_tool_calls_and_errors_are_tallied() -> None:
    led = ledger()
    led.record_tool("openfoam__run_blockmesh", False, {"case_path": "cases/work/x"})
    led.record_tool("openfoam__check_mesh", True, {"case_path": "cases/work/x"})
    led.record_tool("openfoam__check_mesh", False, {"case_path": "cases/work/y"})
    d = led.to_dict()
    assert d["tool_calls"] == 3
    assert d["tool_errors"] == 1
    assert d["per_tool"]["openfoam__check_mesh"] == 2
    # Case paths are deduplicated in first-seen order so the record says
    # which case a run actually touched.
    assert d["case_paths"] == ["cases/work/x", "cases/work/y"]


def test_stop_reason_and_wall_clock_are_recorded() -> None:
    led = ledger()
    led.iterations = 4
    led.finish("end_turn")
    d = led.to_dict()
    assert d["stop_reason"] == "end_turn"
    assert d["iterations"] == 4
    assert d["wall_clock_s"] >= 0


def test_unfinished_run_still_serialises() -> None:
    # A run killed mid-flight still has to produce a usable record.
    d = ledger().to_dict()
    assert d["stop_reason"] is None
    assert d["wall_clock_s"] >= 0
