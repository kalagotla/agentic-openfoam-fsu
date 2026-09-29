"""Tests for the Anthropic agent loop's stop conditions.

One bug motivated these: a response that hit the output cap arrived with
no tool_use blocks, and the loop read "no tool calls" as "the agent is
finished". A run truncated partway through writing a blockMeshDict was
reported as a completed run with an empty case directory. The distinction
between "stopped" and "was cut off" is what these pin.

The loop takes an injected client so it can be driven with scripted
responses — no API key, no network.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from run_agent import RunLedger, run_anthropic


class FakeMessages:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        # Snapshot the message list: the loop mutates it in place, so a
        # stored reference would show a later state than the call saw.
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        if not self.responses:
            raise AssertionError("loop asked for more responses than scripted")
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.messages = FakeMessages(responses)


def text_response(text: str, stop_reason: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def drive(responses: list[Any], max_iters: int = 5) -> tuple[FakeClient, RunLedger]:
    client = FakeClient(responses)
    ledger = RunLedger(backend="anthropic", model="fake", prompt="p")
    asyncio.run(
        run_anthropic(
            sessions={},
            tools=[],
            route={},
            model="fake",
            system_prompt="sys",
            user_prompt="do it",
            max_iters=max_iters,
            tools_with_case_path=set(),
            known_case_paths=[],
            ledger=ledger,
            client=client,
        )
    )
    return client, ledger


def test_end_turn_finishes_the_run() -> None:
    client, ledger = drive([text_response("All done.", "end_turn")])
    assert ledger.stop_reason == "end_turn"
    assert len(client.messages.calls) == 1


def test_truncated_response_is_continued_not_treated_as_done() -> None:
    client, ledger = drive(
        [
            text_response("Here is the blockMeshDict: vertices (", "max_tokens"),
            text_response("Finished.", "end_turn"),
        ]
    )
    # The cut-off response must not end the run.
    assert ledger.stop_reason == "end_turn"
    assert len(client.messages.calls) == 2
    # The continuation asks for the whole file rather than a patch, because
    # a re-issued partial dictionary is worse than none.
    follow_up = client.messages.calls[1]["messages"][-1]
    assert follow_up["role"] == "user"
    assert "cut off" in follow_up["content"]
    assert "do not abbreviate" in follow_up["content"]


def test_repeated_truncation_still_respects_max_iters() -> None:
    # A model that keeps overrunning must not loop forever.
    client, ledger = drive([text_response("...", "max_tokens") for _ in range(3)], max_iters=3)
    assert ledger.stop_reason == "max_iters"
    assert len(client.messages.calls) == 3


def test_usage_is_tallied_across_the_continuation() -> None:
    _, ledger = drive(
        [
            text_response("cut off", "max_tokens"),
            text_response("done", "end_turn"),
        ]
    )
    # Both calls count: a truncated response was still paid for.
    assert ledger.to_dict()["input_tokens"] == 20
    assert ledger.to_dict()["iterations"] == 2


def test_output_cap_is_large_enough_for_a_dictionary() -> None:
    client, _ = drive([text_response("done", "end_turn")])
    # 4096 truncated the agent mid-blockMeshDict; the cap has to clear a
    # realistic graded multi-block file.
    assert client.messages.calls[0]["max_tokens"] >= 16384
