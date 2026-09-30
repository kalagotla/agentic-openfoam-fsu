"""Tests for backend resolution in `scripts/run_agent.py`.

The MCP servers are meant to be driven by whatever model a user has, so
"can this run against a local server" is a claim the repo makes and these
check it. They cover the resolution that happens *before* anything
connects — endpoint, key, model — because that is where a local-model run
usually goes wrong, and a misconfiguration should fail in a sentence
rather than after four servers have started.
"""

from __future__ import annotations

import argparse

import pytest
from run_agent import (
    BACKENDS,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_VLLM_BASE_URL,
    _resolve_runtime,
    load_system_prompt,
    resolve_backend,
)


def args_for(backend: str, **kw) -> argparse.Namespace:
    base = {
        "backend": backend,
        "model": None,
        "base_url": None,
        "api_key_env": "OPENAI_API_KEY",
    }
    base.update(kw)
    return argparse.Namespace(**base)


def test_every_named_backend_resolves() -> None:
    for name in BACKENDS:
        family, _, _ = resolve_backend(name)
        assert family in ("anthropic", "openai")


def test_unknown_backend_names_the_alternatives() -> None:
    with pytest.raises(SystemExit) as exc:
        resolve_backend("gpt5-turbo-max")
    assert "vllm" in str(exc.value)


def test_local_backends_default_to_their_conventional_ports(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    a = args_for("ollama")
    _resolve_runtime(a)
    assert a.base_url == DEFAULT_OLLAMA_BASE_URL

    b = args_for("vllm", model="some-model")
    _resolve_runtime(b)
    assert b.base_url == DEFAULT_VLLM_BASE_URL


def test_explicit_base_url_wins(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://from-env:9/v1")
    a = args_for("vllm", base_url="http://explicit:8000/v1", model="m")
    _resolve_runtime(a)
    assert a.base_url == "http://explicit:8000/v1"


def test_environment_endpoint_is_used_when_no_flag(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://remote-dgx:8000/v1")
    a = args_for("openai", model="m")
    _resolve_runtime(a)
    assert a.base_url == "http://remote-dgx:8000/v1"


def test_generic_openai_backend_requires_an_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        _resolve_runtime(args_for("openai", model="m"))
    assert "--base-url" in str(exc.value)


def test_missing_key_falls_back_to_a_placeholder(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    a = args_for("ollama", model="m")
    _resolve_runtime(a)
    # Ollama ignores the value but rejects an empty field.
    assert a.api_key == "local"


def test_a_configured_key_is_picked_up(monkeypatch) -> None:
    monkeypatch.setenv("MY_VLLM_KEY", "sk-local-abc")
    a = args_for("vllm", model="m", api_key_env="MY_VLLM_KEY")
    _resolve_runtime(a)
    assert a.api_key == "sk-local-abc"


def test_model_is_discovered_when_not_given(monkeypatch) -> None:
    import run_agent

    monkeypatch.setattr(
        run_agent, "discover_model", lambda _u, _k: "meta-llama/Llama-3.3-70B"
    )
    a = args_for("vllm")
    _resolve_runtime(a)
    # A local server usually hosts one model under a long path-like name;
    # asking beats making the user retype it.
    assert a.model == "meta-llama/Llama-3.3-70B"


def test_undiscoverable_model_fails_clearly(monkeypatch) -> None:
    import run_agent

    monkeypatch.setattr(run_agent, "discover_model", lambda _u, _k: None)
    with pytest.raises(SystemExit) as exc:
        _resolve_runtime(args_for("vllm"))
    assert "--model" in str(exc.value)


def test_anthropic_needs_its_key_and_says_so(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        _resolve_runtime(args_for("anthropic"))
    message = str(exc.value)
    assert "ANTHROPIC_API_KEY" in message
    # And points at the local alternatives rather than dead-ending.
    assert "vllm" in message


def test_anthropic_keeps_its_default_model(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    a = args_for("anthropic")
    _resolve_runtime(a)
    assert a.model == DEFAULT_ANTHROPIC_MODEL
    assert a.base_url is None


def test_system_prompt_default_follows_the_backend_family(tmp_path) -> None:
    (tmp_path / "CLAUDE.md").write_text("full contract")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "local_system_prompt.md").write_text("slim")

    assert load_system_prompt(tmp_path, "anthropic") == "full contract"
    # Every OpenAI-compatible endpoint gets the slim prompt by default, not
    # just Ollama — the default tracks model capability, not vendor.
    for backend in ("ollama", "vllm", "lmstudio", "openai"):
        assert load_system_prompt(tmp_path, backend) == "slim"


def test_system_prompt_override_beats_the_default(tmp_path) -> None:
    (tmp_path / "CLAUDE.md").write_text("full contract")
    override = tmp_path / "custom.md"
    override.write_text("bespoke")
    # A large model behind vLLM should be given the full contract.
    assert load_system_prompt(tmp_path, "vllm", override) == "bespoke"
