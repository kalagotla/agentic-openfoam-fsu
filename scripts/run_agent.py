#!/usr/bin/env python3
"""Minimal MCP-driven agent harness for agentic-openfoam.

This script proves the workshop's load-bearing claim: the four MCP
servers don't depend on Claude Code (or any specific IDE). You can
drive them with the Anthropic Claude API or a local Ollama-hosted
model — the servers are unchanged.

How it works (roughly 4 conceptual steps):

  1. Read ``.mcp.json`` and spawn each server as a subprocess with
     stdio JSON-RPC transport (the standard MCP wire protocol).
  2. Ask each server for its tool list. Flatten into one set of tools
     the agent can call, prefixed with the server name (``openfoam__write_dict``)
     so we know how to route tool calls back.
  3. Read the system prompt — ``CLAUDE.md`` for Anthropic, the slim
     ``scripts/local_system_prompt.md`` for an OpenAI-compatible
     endpoint. Send the user's prompt + tools to the chosen backend.
  4. Loop: if the model emits tool calls, execute them via the
     appropriate MCP session, append the results to the message
     history, and call the model again. Stop when the model emits a
     final text response with no tool calls, or after ``--max-iters``.

Usage:

    # Backend 1: Anthropic API (bring your own ANTHROPIC_API_KEY)
    export ANTHROPIC_API_KEY=sk-ant-...
    uv run scripts/run_agent.py --backend anthropic \\
        --prompt "Set up and run the cases/scenarios/lid-cavity.yaml scenario"

    # Backend 2: any OpenAI-compatible server. They differ only in where
    # they listen, so the named backends are shorthand for a default port.

    # Local Ollama (free). Recommended model: gpt-oss:20b — emits real
    # OpenAI-style tool_calls.
    ollama serve &
    ollama pull gpt-oss:20b
    uv run scripts/run_agent.py --backend ollama --model gpt-oss:20b \\
        --prompt "List the available reference datasets"

    # A vLLM server, local or remote. With no --model the harness asks the
    # server what it is serving.
    uv run scripts/run_agent.py --backend vllm \\
        --base-url http://<host>:8000/v1 \\
        --prompt "Set up and run cases/scenarios/lid-cavity.yaml"

    # Anything else (LM Studio, llama.cpp, a hosted endpoint):
    uv run scripts/run_agent.py --backend openai \\
        --base-url https://<host>/v1 --api-key-env MY_KEY --model <name> \\
        --prompt "..."

    # See scripts/litellm_proxy.yaml if you want to drive Claude Code
    # (not this harness) with a local model.

Intentionally short and readable — the agent loop should be followable
in under 10 minutes of reading.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time as _time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Shared automation-level gate (same policy the Claude Code hook uses).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from automation_gate import gate_decision

# Default model picks. Override on the command line as needed.
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-7"
DEFAULT_OLLAMA_MODEL = "gpt-oss:20b"

# Any server speaking the OpenAI chat-completions API works — Ollama, vLLM,
# LM Studio, llama.cpp, or a hosted endpoint. They differ only in where they
# listen, so the backend is one code path with per-server defaults rather
# than one branch per vendor.
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_VLLM_BASE_URL = "http://localhost:8000/v1"
DEFAULT_LMSTUDIO_BASE_URL = "http://localhost:1234/v1"

# backend name -> (family, default base URL, default model)
BACKENDS: dict[str, tuple[str, str | None, str | None]] = {
    "anthropic": ("anthropic", None, DEFAULT_ANTHROPIC_MODEL),
    "openai": ("openai", None, None),
    "ollama": ("openai", DEFAULT_OLLAMA_BASE_URL, DEFAULT_OLLAMA_MODEL),
    "vllm": ("openai", DEFAULT_VLLM_BASE_URL, None),
    "lmstudio": ("openai", DEFAULT_LMSTUDIO_BASE_URL, None),
}


def resolve_backend(name: str) -> tuple[str, str | None, str | None]:
    """Map a backend name to its family, default endpoint, and default model."""
    try:
        return BACKENDS[name]
    except KeyError:
        raise SystemExit(
            f"Unknown backend {name!r}. Choose one of: {', '.join(sorted(BACKENDS))}"
        ) from None


def discover_model(base_url: str, api_key: str) -> str | None:
    """Ask an OpenAI-compatible server which model it is serving.

    A local server usually serves exactly one model, often under a long
    path-like name that is tedious to retype (and easy to get subtly wrong).
    Asking is more reliable than defaulting.
    """
    import json as _json
    import urllib.error
    import urllib.request

    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = _json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    data = payload.get("data") or []
    if not data:
        return None
    first = data[0]
    return first.get("id") if isinstance(first, dict) else None

# Output cap per model response. OpenFOAM dictionaries are long — a
# blockMeshDict with a graded multi-block topology runs to thousands of
# tokens — so a small cap truncates the agent mid-file.
MAX_RESPONSE_TOKENS = 16384

# We prefix MCP tool names with their server so the agent knows which
# server to route the call back to. Keep it filesystem-safe (no dots /
# slashes) since some backends are picky about tool-name characters.
TOOL_NAME_SEP = "__"


# ---------------------------------------------------------------------------
# Run ledger — what one run cost
# ---------------------------------------------------------------------------


class RunLedger:
    """Tally of one agent run: iterations, tool calls, tokens, wall-clock.

    Written out as JSON with ``--run-summary`` so a run's cost is a
    measured number rather than an estimate. Both backends update the same
    ledger, which is what makes an Anthropic run and an Ollama run
    comparable on the same axes.
    """

    def __init__(self, backend: str, model: str, prompt: str) -> None:
        self.backend = backend
        self.model = model
        self.prompt = prompt
        # Which endpoint served the run. Two local servers can host the same
        # model name and behave differently, so the record names both.
        self.base_url: str | None = None
        self.started_at = _time.time()
        self.finished_at: float | None = None
        self.iterations = 0
        self.stop_reason: str | None = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0
        self.tool_calls = 0
        self.tool_errors = 0
        self.per_tool: dict[str, int] = {}
        self.case_paths: list[str] = []

    def record_usage(self, usage: Any) -> None:
        """Absorb a response's usage block from either backend's shape."""
        if usage is None:
            return
        get = (
            usage.get
            if isinstance(usage, dict)
            else lambda k, d=0: getattr(usage, k, d) or d
        )
        self.input_tokens += int(get("input_tokens", 0) or get("prompt_tokens", 0))
        self.output_tokens += int(
            get("output_tokens", 0) or get("completion_tokens", 0)
        )
        self.cache_read_tokens += int(get("cache_read_input_tokens", 0))
        self.cache_write_tokens += int(get("cache_creation_input_tokens", 0))

    def record_tool(self, name: str, is_error: bool, args: dict[str, Any]) -> None:
        self.tool_calls += 1
        self.tool_errors += int(bool(is_error))
        self.per_tool[name] = self.per_tool.get(name, 0) + 1
        case_path = args.get("case_path") if isinstance(args, dict) else None
        if isinstance(case_path, str) and case_path not in self.case_paths:
            self.case_paths.append(case_path)

    def finish(self, reason: str) -> None:
        self.stop_reason = reason
        self.finished_at = _time.time()

    def to_dict(self) -> dict[str, Any]:
        end = self.finished_at or _time.time()
        return {
            "backend": self.backend,
            "base_url": self.base_url,
            "model": self.model,
            "prompt": self.prompt,
            "wall_clock_s": round(end - self.started_at, 3),
            "iterations": self.iterations,
            "stop_reason": self.stop_reason,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "per_tool": dict(sorted(self.per_tool.items())),
            "case_paths": self.case_paths,
        }


# ---------------------------------------------------------------------------
# MCP server discovery + tool routing
# ---------------------------------------------------------------------------


async def connect_servers(
    mcp_config: dict[str, Any],
    stack: AsyncExitStack,
) -> dict[str, ClientSession]:
    """Spawn each configured MCP server as a subprocess and return a
    name -> ClientSession map. The sessions are entered into the
    AsyncExitStack so they're torn down cleanly on exit."""
    sessions: dict[str, ClientSession] = {}
    for name, cfg in mcp_config["mcpServers"].items():
        params = StdioServerParameters(
            command=cfg["command"],
            args=cfg.get("args", []),
            env=cfg.get("env"),
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        sessions[name] = session
        print(f"[mcp] connected to '{name}' server", file=sys.stderr)
    return sessions


async def gather_tools(
    sessions: dict[str, ClientSession],
) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]]]:
    """Aggregate tools across servers.

    Returns:
      - tools_anthropic_style: list of {name, description, input_schema}
        in the format Anthropic accepts directly. (OpenAI/Ollama get
        translated separately in to_openai_tools.)
      - route_map: prefixed_name -> (server_name, raw_tool_name) so we
        know which session to call when the agent invokes a tool.
    """
    tools: list[dict[str, Any]] = []
    route: dict[str, tuple[str, str]] = {}
    for server, session in sessions.items():
        result = await session.list_tools()
        for tool in result.tools:
            prefixed = f"{server}{TOOL_NAME_SEP}{tool.name}"
            route[prefixed] = (server, tool.name)
            tools.append(
                {
                    "name": prefixed,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema,
                }
            )
    return tools, route


def _confirm_gate(raw_name: str, reason: str, args: dict[str, Any]) -> bool:
    """Prompt the operator on stdin to approve a gated phase. y → proceed."""
    case = args.get("case_path", "")
    sys.stderr.write(
        f"\n[automation gate] {reason}\n"
        f"  tool: {raw_name}   case: {case}\n"
        f"  Approve this step? [y/N] "
    )
    sys.stderr.flush()
    try:
        return input().strip().lower() in ("y", "yes")
    except EOFError:
        return False


# Content that "elides" a real dictionary body — what a weak model emits
# when it can't reproduce a long file: ``"??"``, ``"..."``, ``"…"``, ``""``.
# Real OpenFOAM dicts always carry keywords, so an all-punctuation body
# under a few dozen characters is unambiguously a placeholder.
_PLACEHOLDER_CONTENT_RE = re.compile(r"[\s?.=…\-_*]*")


def _is_placeholder_dict_content(content: Any) -> bool:
    """True if ``write_dict`` content is empty or an elision placeholder."""
    if not isinstance(content, str):
        return True
    stripped = content.strip()
    if not stripped:
        return True
    return len(stripped) < 40 and bool(_PLACEHOLDER_CONTENT_RE.fullmatch(stripped))


def _normalize_case_path(
    prefixed_name: str,
    args: dict[str, Any],
    tools_with_case_path: set[str],
    known_case_paths: list[str],
) -> str | None:
    """Force the ``case_path`` argument to the case directory the harness
    pre-created this run.

    Weak local models corrupt the long absolute path they must echo on
    every call (observed: ``"=??"``, ``"$HOME/some"``,
    ``"…/cases/work/lid-cont…???…"``). In this harness there is exactly
    one case directory per scenario, and it is the only valid target for
    any ``case_path``-taking tool, so substituting the known path whenever
    the model's value doesn't already match it is always correct. When the
    prompt referenced zero or several scenarios the substitution is
    ambiguous, so leave the argument untouched.

    Mutates ``args`` in place. Returns a one-line note when it changed
    something (for the operator log), else ``None``.
    """
    if prefixed_name not in tools_with_case_path or len(known_case_paths) != 1:
        return None
    canonical = known_case_paths[0]
    given = args.get("case_path")
    if given == canonical:
        return None
    args["case_path"] = canonical
    if given is None:
        return f"injected case_path={canonical} (model omitted it)"
    return f"corrected case_path {given!r} -> {canonical}"


async def call_tool(
    sessions: dict[str, ClientSession],
    route: dict[str, tuple[str, str]],
    prefixed_name: str,
    args: dict[str, Any],
    tools_with_case_path: set[str] | None = None,
    known_case_paths: list[str] | None = None,
) -> tuple[str, bool]:
    """Invoke a tool via the appropriate MCP session.

    Returns (content_text, is_error). Tool results from MCP are a list
    of content blocks; we join the text blocks together — the four
    servers in this repo all return either JSON-serializable dicts or
    short strings, so this is sufficient.

    Before dispatch, two repairs guard against the garbage weak local
    models feed into tool arguments: ``case_path`` is snapped back to the
    pre-created case directory, and a ``write_dict`` call carrying empty /
    placeholder ``content`` (or record_step's arguments by mistake) is
    bounced back with a corrective error instead of writing a junk file.
    """
    if prefixed_name not in route:
        return (f"Error: unknown tool '{prefixed_name}'", True)
    server, raw_name = route[prefixed_name]

    note = _normalize_case_path(
        prefixed_name, args, tools_with_case_path or set(), known_case_paths or []
    )
    if note is not None:
        print(f"[harness] {note}", file=sys.stderr)

    if raw_name == "write_dict":
        if not args.get("content") and any(
            k in args for k in ("decision", "phase", "status", "when_it_breaks")
        ):
            return (
                "Error: this looks like a record_step call sent to write_dict. "
                "To narrate a step, call record_step with phase/status/title. "
                "write_dict needs case_path, dict_name, subdir, and the FULL "
                "file text in `content`.",
                True,
            )
        if _is_placeholder_dict_content(args.get("content")):
            return (
                "Error: write_dict `content` was empty or a placeholder "
                "('??', '...'). Never abbreviate file content. Prefer "
                "copy_tutorial_dict to transfer a tutorial file verbatim; only "
                "use write_dict with the complete dictionary text (FoamFile "
                "header through trailing separator) when no tutorial matches.",
                True,
            )

    # Human-in-the-loop: pause before gated phases per automation_level.
    decision, reason = gate_decision(raw_name, args)
    if decision == "ask":
        approved = await asyncio.to_thread(_confirm_gate, raw_name, reason, args)
        if not approved:
            return (
                f"BLOCKED by automation_level: {reason}. The researcher "
                f"declined this step — stop and ask how to proceed; do not retry.",
                True,
            )

    try:
        result = await sessions[server].call_tool(raw_name, args)
    except Exception as exc:
        # Surface ANY tool failure to the LLM as a structured error
        # string rather than crashing the harness.
        return (f"Error calling {server}.{raw_name}: {type(exc).__name__}: {exc}", True)
    parts: list[str] = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return ("\n".join(parts) if parts else "(no text content)", bool(result.isError))


# ---------------------------------------------------------------------------
# Backend: Anthropic Claude API
# ---------------------------------------------------------------------------


def to_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["input_schema"],
        }
        for t in tools
    ]


async def run_anthropic(
    sessions: dict[str, ClientSession],
    tools: list[dict[str, Any]],
    route: dict[str, tuple[str, str]],
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_iters: int,
    tools_with_case_path: set[str],
    known_case_paths: list[str],
    ledger: RunLedger | None = None,
    client: Any | None = None,
    max_tokens: int = MAX_RESPONSE_TOKENS,
) -> None:
    """Drive the agent loop against Anthropic's tool-use API."""
    if client is None:
        try:
            import anthropic
        except ImportError as exc:
            sys.exit(
                "anthropic SDK not installed. Run `uv sync` from the repo root "
                "or install with `uv add anthropic`. (" + str(exc) + ")"
            )
        client = anthropic.AsyncAnthropic()
    anthropic_tools = to_anthropic_tools(tools)
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]

    for iteration in range(max_iters):
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=anthropic_tools,
            messages=messages,
        )
        if ledger is not None:
            ledger.iterations = iteration + 1
            ledger.record_usage(getattr(response, "usage", None))

        assistant_blocks: list[dict[str, Any]] = []
        tool_uses: list[Any] = []
        for block in response.content:
            if block.type == "text":
                print(f"\n[agent] {block.text}")
                assistant_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
                tool_uses.append(block)
        messages.append({"role": "assistant", "content": assistant_blocks})

        # A max_tokens stop is a truncation, not an answer: the model was
        # cut off mid-response, usually partway through a long dictionary.
        # Treating it as completion ends the run silently with the case
        # half-authored, so ask for the rest instead.
        if response.stop_reason == "max_tokens" and not tool_uses:
            print("[harness] response hit the output cap; asking for the rest.")
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response was cut off at the output limit. "
                        "Continue from where you stopped. If you were writing a "
                        "dictionary, re-issue the tool call with the complete "
                        "content — do not abbreviate or elide any part of it."
                    ),
                }
            )
            continue

        if not tool_uses:
            print(f"\n[harness] done after {iteration + 1} iteration(s).")
            if ledger is not None:
                ledger.finish(str(response.stop_reason or "end_turn"))
            return

        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            print(f"[tool] {tu.name}({json.dumps(tu.input)[:120]}...)")
            content, is_error = await call_tool(
                sessions, route, tu.name, tu.input,
                tools_with_case_path, known_case_paths,
            )
            entry: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": content,
            }
            if is_error:
                entry["is_error"] = True
            if ledger is not None:
                ledger.record_tool(tu.name, is_error, tu.input)
            tool_results.append(entry)
        messages.append({"role": "user", "content": tool_results})

    print(f"\n[harness] hit max-iters ({max_iters}); stopping.")
    if ledger is not None:
        ledger.finish("max_iters")


# ---------------------------------------------------------------------------
# Backend: Ollama (OpenAI-compatible API)
# ---------------------------------------------------------------------------


def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


_TOOL_CALL_HINTS = ('"name"', "'name'", "tool_call", "function_call", "<|tool_call")

_SCENARIO_RE = re.compile(r"cases/scenarios/([A-Za-z0-9_\-]+)\.yaml")


def _inline_referenced_scenarios(
    prompt: str, repo_root: Path
) -> tuple[str, list[str]]:
    """If the user's prompt references ``cases/scenarios/<name>.yaml``,
    inline the file contents and pre-create ``cases/work/<name>/`` so a
    local model without a generic file-read tool — and without a
    case-directory-creation MCP tool — can still get the case set up.
    Claude Code papers over both gaps via its built-in Read/Bash tools;
    the bare harness needs the explicit pre-injection.

    Returns ``(prompt, work_dirs)`` where ``work_dirs`` is the list of
    absolute case directories created here. The harness uses it to
    auto-correct the ``case_path`` argument when a weak model corrupts
    the long absolute path it is asked to echo on every tool call.
    """
    seen: set[str] = set()
    extras: list[str] = []
    work_dirs: list[str] = []
    for match in _SCENARIO_RE.finditer(prompt):
        rel = match.group(0)
        if rel in seen:
            continue
        seen.add(rel)
        path = repo_root / rel
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # write_dict requires the case directory to already exist (it
        # only creates the subdir under it). Pre-create here.
        scenario_name = match.group(1)
        work_dir = repo_root / "cases" / "work" / scenario_name
        work_dir.mkdir(parents=True, exist_ok=True)
        abs_work_dir = str(work_dir.resolve())
        work_dirs.append(abs_work_dir)
        extras.append(
            f"\n\n=== Inlined contents of {rel} ===\n{content}\n=== end {rel} ===\n"
            f"\nIMPORTANT — case directory.\n"
            f"The case directory has already been created at:\n"
            f"  {abs_work_dir}\n"
            f"Use this EXACT absolute path as the `case_path` argument for every\n"
            f"tool call (`write_dict`, `copy_tutorial_dict`, `run_blockmesh`,\n"
            f"`run_solver`, `record_step`, etc.). Do not invent a different path,\n"
            f"do not use a relative path, do not prepend `/home/` or any other\n"
            f"prefix. The path above is the one and only correct case_path."
        )
    final_prompt = prompt + "".join(extras) if extras else prompt
    return final_prompt, work_dirs


def _looks_like_attempted_tool_call(content: str) -> bool:
    """Heuristic: does this content look like the model *tried* to emit
    a tool call (vs. a real final-answer text)? Used to decide whether
    to retry with a corrective message or terminate the loop."""
    if not content:
        return False
    text = content.strip()
    if any(text.startswith(c) for c in "{["):
        return True
    return any(hint in text for hint in _TOOL_CALL_HINTS)


def _extract_inline_tool_calls(
    content: str,
    valid_tool_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Some Ollama-hosted models (e.g. qwen2.5-coder) emit tool calls as
    JSON inside ``message.content`` instead of populating the
    OpenAI-style ``tool_calls`` field. Recover by parsing ``content``
    for ``{"name": ..., "arguments": ...}`` shapes and returning them as
    synthesized tool-call dicts. Returns [] if nothing parseable.
    """
    if not content:
        return []
    text = content.strip()
    # Strip ```json ... ``` fences if present.
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    # Some models leak chat-template tokens like ``<|im_start|>`` /
    # ``<|im_end|>`` or trailing escape characters into the content.
    # Be tolerant: find the first ``{`` or ``[`` and try to decode the
    # JSON value starting there with raw_decode (which ignores trailing
    # junk).
    start = next((i for i, ch in enumerate(text) if ch in "{["), -1)
    if start < 0:
        return []
    try:
        parsed, _end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return []
    items = parsed if isinstance(parsed, list) else [parsed]
    calls: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict) or "name" not in item:
            continue
        name = item["name"]
        # Reject hallucinated / garbage tool names (e.g. ``"???"``,
        # ``"OpenAI??Wait"``) when we know the valid surface — otherwise
        # we cheerfully dispatch nonsense to the MCP layer.
        if valid_tool_names is not None and name not in valid_tool_names:
            continue
        args = item.get("arguments", item.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append({"id": f"inline-{i}", "name": name, "arguments": args})
    return calls


async def run_openai_compatible(
    sessions: dict[str, ClientSession],
    tools: list[dict[str, Any]],
    route: dict[str, tuple[str, str]],
    model: str,
    base_url: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    max_iters: int,
    tools_with_case_path: set[str],
    known_case_paths: list[str],
    ledger: RunLedger | None = None,
) -> None:
    """Drive the agent loop against any OpenAI-compatible chat API."""
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        sys.exit(
            "openai SDK not installed. Run `uv sync` from the repo root "
            "or install with `uv add openai`. (" + str(exc) + ")"
        )

    # Ollama ignores the key but requires the field to be non-empty; vLLM
    # may enforce a real one. The caller resolves which to send.
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    openai_tools = to_openai_tools(tools)
    valid_tool_names: set[str] = {t["name"] for t in tools}
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for iteration in range(max_iters):
        try:
            # Hosted gateways occasionally answer 200 with an error body and
            # no choices (rate limit, upstream timeout). Retry those briefly
            # instead of crashing the run.
            for attempt in range(4):
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=openai_tools,
                    max_tokens=16384,
                )
                if response.choices:
                    break
                err = getattr(response, "error", None) or getattr(response, "model_extra", None)
                print(f"[harness] empty response from the server ({str(err)[:200]}); retrying")
                await asyncio.sleep(5 * (attempt + 1))
            else:
                raise RuntimeError("server returned no choices after 4 attempts")
            if ledger is not None:
                ledger.iterations = iteration + 1
                ledger.record_usage(getattr(response, "usage", None))
        except Exception as exc:
            # Ollama returns HTTP 500 with a tool-call-parse error when the
            # model emits garbage in the tool_calls slot ("error parsing tool
            # call: raw=..."). Recover by pushing a corrective user message
            # rather than aborting the whole run.
            err_text = str(exc)
            if "error parsing tool call" in err_text or "InternalServerError" in type(exc).__name__:
                print(f"[harness] Ollama rejected the model's tool call: {err_text[:200]}")
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous tool call could not be parsed by the runtime. "
                            "Emit exactly one well-formed tool call (valid JSON arguments, "
                            "no surrounding prose, no chat-template tokens). Do NOT use "
                            "elision placeholders like \"...\" or \"??\" anywhere in the "
                            "arguments — write every value in full or omit the key. Or "
                            "reply with a final plain-text summary if you are done."
                        ),
                    }
                )
                continue
            raise
        choice = response.choices[0]
        msg = choice.message
        finish_reason = getattr(choice, "finish_reason", None)

        # Normalize tool calls into a single list of {id, name, args} so
        # we can handle both the OpenAI-style ``tool_calls`` field and
        # the inline-JSON fallback used by some Ollama models uniformly.
        normalized_calls: list[dict[str, Any]] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError as exc:
                    args = {"__parse_error__": str(exc), "__raw__": tc.function.arguments}
                normalized_calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
        elif msg.content:
            inline = _extract_inline_tool_calls(msg.content, valid_tool_names)
            if inline:
                print("[harness] recovered tool calls from message content (model didn't use tool_calls field).")
                normalized_calls = inline

        # Append assistant message (text + any tool calls). Skip
        # entirely when the model produced nothing of either kind —
        # appending a content-less assistant message wedges some
        # OpenAI-compat servers.
        if normalized_calls or (msg.content and not _looks_like_attempted_tool_call(msg.content)):
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if msg.content and not normalized_calls:
                assistant_msg["content"] = msg.content
                print(f"\n[agent] {msg.content}")
            if normalized_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])},
                    }
                    for c in normalized_calls
                ]
            messages.append(assistant_msg)

        if not normalized_calls:
            # Distinguish "model gave a final-answer text" from "model
            # tried to emit a tool call but produced unparseable text".
            # In the latter case, push a corrective message and let it
            # try again instead of silently terminating mid-task.
            if _looks_like_attempted_tool_call(msg.content or ""):
                print("[harness] content looks like an attempted tool call but didn't parse — sending corrective message.")
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response looked like an attempted tool call but "
                            "could not be parsed. Emit exactly one tool call using the "
                            "OpenAI tool_calls format (or, if you must inline it, a single "
                            "valid JSON object on its own with the keys \"name\" and "
                            "\"arguments\" — no chat-template tokens, no surrounding text, "
                            "no trailing escape characters, and no elision placeholders "
                            "like \"...\" or \"??\" inside the arguments). If you are "
                            "finished, reply with a plain-text summary instead."
                        ),
                    }
                )
                continue
            # Truly empty response: model emitted neither tool_calls nor
            # final-answer text. Most common with reasoning models that
            # hit the token cap during internal reasoning. Nudge them.
            if not (msg.content or "").strip() and finish_reason in ("length", "stop"):
                print(f"[harness] empty response (finish_reason={finish_reason}); nudging the model to continue.")
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was empty — no tool call and no text. "
                            "Continue the task: either call the next tool, or give a final "
                            "plain-text summary if you believe the task is complete."
                        ),
                    }
                )
                continue
            print(f"\n[harness] done after {iteration + 1} iteration(s). (finish_reason={finish_reason})")
            if ledger is not None:
                ledger.finish(str(finish_reason or "stop"))
            return

        for c in normalized_calls:
            args = c["arguments"]
            if isinstance(args, dict) and "__parse_error__" in args:
                err = f"Error: model emitted invalid JSON args: {args['__parse_error__']}"
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": err})
                continue
            print(f"[tool] {c['name']}({json.dumps(args)[:120]}...)")
            content, is_error = await call_tool(
                sessions, route, c["name"], args,
                tools_with_case_path, known_case_paths,
            )
            if ledger is not None:
                ledger.record_tool(c["name"], is_error, args)
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": content})

    print(f"\n[harness] hit max-iters ({max_iters}); stopping.")
    if ledger is not None:
        ledger.finish("max_iters")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def load_system_prompt(
    repo_root: Path,
    backend: str,
    override_path: Path | None = None,
) -> str:
    """Read the system prompt.

    Defaults differ by backend family, not vendor: Anthropic gets the full
    CLAUDE.md workflow contract (~600 lines, written for frontier models),
    and every OpenAI-compatible endpoint gets the slim
    ``scripts/local_system_prompt.md``, because the models usually served
    that way lose the thread under the full contract.

    That default is about model capability rather than which server is in
    front of it, so a large model behind vLLM should be given the full
    contract with ``--system-prompt-file CLAUDE.md``.
    """
    if override_path is not None:
        if not override_path.is_file():
            sys.exit(f"--system-prompt-file {override_path} does not exist.")
        return override_path.read_text(encoding="utf-8")
    family, _, _ = resolve_backend(backend)
    if family == "openai":
        slim = repo_root / "scripts" / "local_system_prompt.md"
        if slim.is_file():
            return slim.read_text(encoding="utf-8")
    claude_md = repo_root / "CLAUDE.md"
    if not claude_md.is_file():
        return "You are a helpful CFD agent. Use the available MCP tools."
    return claude_md.read_text(encoding="utf-8")


def load_mcp_config(repo_root: Path, config_path: Path | None) -> dict[str, Any]:
    path = config_path or (repo_root / ".mcp.json")
    if not path.is_file():
        sys.exit(f"No .mcp.json found at {path}. Pass --mcp-config to override.")
    return json.loads(path.read_text(encoding="utf-8"))


async def amain(args: argparse.Namespace) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    mcp_config = load_mcp_config(repo_root, args.mcp_config)
    system_prompt = load_system_prompt(repo_root, args.backend, args.system_prompt_file)
    user_prompt, known_case_paths = _inline_referenced_scenarios(args.prompt, repo_root)
    if user_prompt != args.prompt:
        print("[harness] inlined referenced scenario YAML(s) into the prompt.", file=sys.stderr)

    ledger = RunLedger(
        backend=args.backend,
        model=args.model,
        prompt=args.prompt,
    )
    ledger.base_url = args.base_url

    try:
        await _drive(args, mcp_config, system_prompt, user_prompt, known_case_paths, ledger)
    finally:
        if getattr(args, "run_summary", None):
            # Written in a finally block: a run that dies on an API error or
            # a timeout still cost something, and losing the tally would
            # make the failure look free.
            args.run_summary.parent.mkdir(parents=True, exist_ok=True)
            args.run_summary.write_text(json.dumps(ledger.to_dict(), indent=2) + "\n")
            print(f"[harness] run summary → {args.run_summary}", file=sys.stderr)


async def _drive(
    args: argparse.Namespace,
    mcp_config: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    known_case_paths: list[str],
    ledger: RunLedger,
) -> None:
    """Connect the servers and run the agent loop on the chosen backend."""
    async with AsyncExitStack() as stack:
        sessions = await connect_servers(mcp_config, stack)
        tools, route = await gather_tools(sessions)
        print(
            f"[harness] {len(tools)} tools across {len(sessions)} server(s).",
            file=sys.stderr,
        )

        # Tools that accept a ``case_path`` argument — derived from each
        # tool's input schema so the case_path auto-correction tracks the
        # servers without a hardcoded list.
        tools_with_case_path = {
            t["name"]
            for t in tools
            if "case_path" in ((t["input_schema"] or {}).get("properties") or {})
        }

        family, _, _ = resolve_backend(args.backend)
        if family == "anthropic":
            await run_anthropic(
                sessions=sessions,
                tools=tools,
                route=route,
                model=args.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_iters=args.max_iters,
                tools_with_case_path=tools_with_case_path,
                known_case_paths=known_case_paths,
                ledger=ledger,
            )
        else:
            await run_openai_compatible(
                sessions=sessions,
                tools=tools,
                route=route,
                model=args.model,
                base_url=args.base_url,
                api_key=args.api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_iters=args.max_iters,
                tools_with_case_path=tools_with_case_path,
                known_case_paths=known_case_paths,
                ledger=ledger,
            )


def _resolve_runtime(args: argparse.Namespace) -> None:
    """Settle endpoint, key, and model before anything connects.

    Resolved up front so a misconfigured run fails in a sentence rather
    than after four MCP servers have started.
    """
    family, default_base_url, default_model = resolve_backend(args.backend)

    if family == "anthropic":
        args.base_url = None
        args.api_key = None
        args.model = args.model or default_model
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit(
                "ANTHROPIC_API_KEY is not set. Either export it, or point "
                "--backend at a local OpenAI-compatible server "
                "(ollama / vllm / lmstudio)."
            )
        return

    args.base_url = (
        args.base_url
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OLLAMA_BASE_URL")
        or default_base_url
    )
    if not args.base_url:
        sys.exit(
            f"--backend {args.backend} needs an endpoint: pass --base-url or "
            "set $OPENAI_BASE_URL."
        )
    # Ollama ignores the key but rejects an empty field, so a placeholder is
    # the working default when no key is configured.
    args.api_key = os.environ.get(args.api_key_env) or "local"

    args.model = args.model or default_model
    if not args.model:
        args.model = discover_model(args.base_url, args.api_key)
        if args.model:
            print(f"[harness] serving model: {args.model}", file=sys.stderr)
    if not args.model:
        sys.exit(
            f"No model given and {args.base_url} did not answer /models. "
            "Pass --model explicitly."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--backend",
        choices=sorted(BACKENDS),
        required=True,
        help=(
            "Agent runtime. 'anthropic' uses ANTHROPIC_API_KEY. Every other "
            "choice speaks the OpenAI chat-completions API and differs only "
            "in its default endpoint: 'ollama' (localhost:11434), 'vllm' "
            "(localhost:8000), 'lmstudio' (localhost:1234), or 'openai' with "
            "an explicit --base-url for anything else."
        ),
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="Natural-language task for the agent.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Model name. Default for anthropic: {DEFAULT_ANTHROPIC_MODEL}. "
        f"Default for ollama: {DEFAULT_OLLAMA_MODEL}.",
    )
    parser.add_argument(
        "--max-iters",
        type=int,
        default=50,
        help="Hard cap on agent iterations (each iteration = one model call + any tool calls).",
    )
    parser.add_argument(
        "--mcp-config",
        type=Path,
        default=None,
        help="Path to an MCP config file. Defaults to .mcp.json at the repo root.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "OpenAI-compatible API endpoint. Defaults to the chosen backend's "
            "conventional port, or $OPENAI_BASE_URL / $OLLAMA_BASE_URL."
        ),
    )
    parser.add_argument(
        "--ollama-base-url",
        dest="base_url",
        help="Deprecated alias for --base-url.",
    )
    parser.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help=(
            "Environment variable holding the API key for an OpenAI-compatible "
            "endpoint. Ollama ignores the value but needs the field non-empty; "
            "a vLLM server started with --api-key enforces it."
        ),
    )
    parser.add_argument(
        "--run-summary",
        type=Path,
        default=None,
        help=(
            "Write a JSON tally of the run (iterations, tool calls, tokens, "
            "wall-clock) to this path. What the evaluation harness reads to "
            "put a measured cost on a run."
        ),
    )
    parser.add_argument(
        "--system-prompt-file",
        type=Path,
        default=None,
        help=(
            "Override the system prompt. Default is CLAUDE.md at the repo root. "
            "Pass a path to a slimmer file when driving smaller local models "
            "that struggle with the full contract."
        ),
    )

    args = parser.parse_args()
    _resolve_runtime(args)

    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        print("\n[harness] interrupted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
