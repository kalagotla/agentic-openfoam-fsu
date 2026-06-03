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
  3. Read ``CLAUDE.md`` as the system prompt — the same instructions
     Claude Code reads. Send the user's prompt + tools to the chosen
     backend (Anthropic API or Ollama via its OpenAI-compatible
     endpoint).
  4. Loop: if the model emits tool calls, execute them via the
     appropriate MCP session, append the results to the message
     history, and call the model again. Stop when the model emits a
     final text response with no tool calls, or after ``--max-iters``.

Usage:

    # Backend 1: Anthropic API (bring your own ANTHROPIC_API_KEY)
    export ANTHROPIC_API_KEY=sk-ant-...
    uv run scripts/run_agent.py --backend anthropic \\
        --prompt "Set up and run the cases/scenarios/lid-cavity.yaml scenario"

    # Backend 2: Local Ollama (free). Recommended model: gpt-oss:20b
    # — emits real OpenAI-style tool_calls. See scripts/litellm_proxy.yaml
    # if you want to drive Claude Code (not this harness) with a local model.
    ollama serve &
    ollama pull gpt-oss:20b
    uv run scripts/run_agent.py --backend ollama --model gpt-oss:20b \\
        --prompt "List the available reference datasets"

Intentionally short and readable — the agent loop should be followable
in under 10 minutes of reading.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import os
import re
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Shared automation-level gate (same policy the Claude Code hook uses).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from automation_gate import gate_decision  # noqa: E402

# Default model picks. Override on the command line as needed.
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-7"
DEFAULT_OLLAMA_MODEL = "gpt-oss:20b"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"

# Iteration budgets differ by backend. A frontier Anthropic model lands a
# clean tool call almost every turn, so 50 is ample. A 20–30B local model
# corrupts roughly half its tool names / arguments and (for reasoning
# models like gpt-oss) regularly burns a turn entirely in the reasoning
# channel, returning an empty final channel — so it needs far more headroom
# to reach a validated case. Override with ``--max-iters``.
DEFAULT_ANTHROPIC_MAX_ITERS = 50
DEFAULT_OLLAMA_MAX_ITERS = 150

# How many non-productive turns in a row (empty final channel, or content
# that looks like a botched tool call we could not parse) the Ollama loop
# tolerates before giving up. A reasoning model often needs a nudge or two
# to emit into the final channel; a genuinely wedged one would otherwise
# spin out the whole iteration budget doing nothing.
MAX_CONSECUTIVE_STALLS = 12

# We prefix MCP tool names with their server so the agent knows which
# server to route the call back to. Keep it filesystem-safe (no dots /
# slashes) since some backends are picky about tool-name characters.
TOOL_NAME_SEP = "__"


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


def _closest_tool_name(
    garbled: str, route: dict[str, tuple[str, str]]
) -> str | None:
    """Snap a corrupted tool *name* back to the real one.

    Weak local models corrupt the tool name itself, not just its
    arguments (observed: ``"openfoam__copy_tpatch?"`` for
    ``copy_tutorial_dict``, ``"open..??"``). When exactly one known tool
    is a clear closest match we can route the call correctly; when the
    corruption is too severe to disambiguate (``"open..??"`` matches
    nothing well) we return ``None`` and let the caller report an
    unknown-tool error rather than dispatch to a guessed tool.
    """
    matches = difflib.get_close_matches(garbled, list(route), n=2, cutoff=0.6)
    if not matches:
        return None
    best = matches[0]
    if len(matches) > 1:
        # Require the winner to be clearly ahead of the runner-up so an
        # ambiguous garble never silently dispatches to the wrong tool.
        r_best = difflib.SequenceMatcher(None, garbled, best).ratio()
        r_next = difflib.SequenceMatcher(None, garbled, matches[1]).ratio()
        if r_best - r_next < 0.1:
            return None
    return best


def _unwrap_tool_envelope(args: dict[str, Any]) -> dict[str, Any]:
    """Unwrap an OpenAI tool-call envelope a model echoed INTO its arguments.

    Some weak models emit ``{"name": "<tool>", "arguments": "{...}"}`` as the
    *arguments* of an already-named tool call — the call envelope nested one
    level too deep (the inner ``arguments`` is usually a JSON string). Detect
    that exact shape and return the inner argument dict so the real call goes
    through; otherwise return ``args`` unchanged.
    """
    if not isinstance(args, dict) or "arguments" not in args:
        return args
    if not set(args) <= {"name", "arguments", "parameters"}:
        return args
    inner = args.get("arguments", args.get("parameters"))
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except json.JSONDecodeError:
            return args
    return inner if isinstance(inner, dict) else args


def _backfill_record_step(args: dict[str, Any]) -> list[str]:
    """Fill in ``record_step``'s required fields when a weak model omits them.

    ``record_step`` is optional narration, but ``phase`` / ``status`` /
    ``title`` have no defaults, so a single omission triggers a hard schema
    rejection that derails the run (observed: a model that supplies rich
    ``decision`` / ``why`` fields but drops ``title``, then loops on the
    error). The narration is worth keeping when the model did supply the
    reasoning, so synthesize the missing scaffolding rather than fail.

    Mutates ``args`` in place. Returns one note per field filled.
    """
    if not isinstance(args, dict):
        return []
    notes: list[str] = []
    if not args.get("status"):
        args["status"] = "info"
        notes.append("filled record_step status='info'")
    if not args.get("phase"):
        args["phase"] = "note"
        notes.append("filled record_step phase='note'")
    if not str(args.get("title") or "").strip():
        seed = str(args.get("decision") or args.get("phase") or "progress note").strip()
        args["title"] = seed[:80] or "progress note"
        notes.append(f"filled record_step title={args['title']!r}")
    return notes


def _repair_unknown_kwargs(args: dict[str, Any], allowed: set[str]) -> list[str]:
    """Rename or drop argument keys the tool's schema doesn't define.

    Weak local models invent slightly-wrong keyword names (observed:
    ``retries_of`` for ``retry_of``). FastMCP validates strictly and
    rejects the *entire* call on a single unexpected keyword, so a
    one-character slip wastes a whole turn. When an unknown key clearly
    matches exactly one real parameter we rename it; otherwise we drop it,
    so a genuinely missing required argument surfaces as a clean
    missing-argument error instead of an opaque unexpected-keyword one.

    Mutates ``args`` in place. Returns one note per repair (for the log).
    """
    if not allowed or not isinstance(args, dict):
        return []
    notes: list[str] = []
    for key in [k for k in args if k not in allowed]:
        match = difflib.get_close_matches(key, sorted(allowed), n=1, cutoff=0.72)
        if match and match[0] not in args:
            args[match[0]] = args.pop(key)
            notes.append(f"renamed arg {key!r} -> {match[0]!r}")
        else:
            args.pop(key)
            notes.append(f"dropped unknown arg {key!r}")
    return notes


async def call_tool(
    sessions: dict[str, ClientSession],
    route: dict[str, tuple[str, str]],
    prefixed_name: str,
    args: dict[str, Any],
    tools_with_case_path: set[str] | None = None,
    known_case_paths: list[str] | None = None,
    tool_arg_names: dict[str, set[str]] | None = None,
) -> tuple[str, bool]:
    """Invoke a tool via the appropriate MCP session.

    Returns (content_text, is_error). Tool results from MCP are a list
    of content blocks; we join the text blocks together — the four
    servers in this repo all return either JSON-serializable dicts or
    short strings, so this is sufficient.

    Before dispatch, several repairs guard against the garbage weak local
    models feed into tool calls: a corrupted tool *name* is snapped back to
    the nearest real tool, ``case_path`` is snapped back to the pre-created
    case directory, argument keys the schema doesn't define are renamed or
    dropped (a one-character slip like ``retries_of`` no longer fails the
    whole call), and a ``write_dict`` call carrying empty / placeholder
    ``content`` (or record_step's arguments by mistake) is bounced back with
    a corrective error instead of writing a junk file. A frontier model
    never trips these, so they are inert on the Anthropic backend.
    """
    if prefixed_name not in route:
        repaired = _closest_tool_name(prefixed_name, route)
        if repaired is None:
            return (f"Error: unknown tool '{prefixed_name}'", True)
        print(
            f"[harness] corrected tool name {prefixed_name!r} -> {repaired}",
            file=sys.stderr,
        )
        prefixed_name = repaired
    server, raw_name = route[prefixed_name]

    # Unwrap a tool-call envelope the model nested into its own arguments
    # before anything reads the (otherwise nested) real arguments.
    unwrapped = _unwrap_tool_envelope(args)
    if unwrapped is not args:
        print("[harness] unwrapped nested tool-call envelope from arguments", file=sys.stderr)
        args = unwrapped

    note = _normalize_case_path(
        prefixed_name, args, tools_with_case_path or set(), known_case_paths or []
    )
    if note is not None:
        print(f"[harness] {note}", file=sys.stderr)

    if tool_arg_names is not None:
        for kw_note in _repair_unknown_kwargs(
            args, tool_arg_names.get(prefixed_name, set())
        ):
            print(f"[harness] {kw_note}", file=sys.stderr)

    # record_step is optional narration; never let a missing required field
    # hard-fail it and derail the run. Backfill phase/status/title.
    if raw_name == "record_step":
        for rs_note in _backfill_record_step(args):
            print(f"[harness] {rs_note}", file=sys.stderr)

    # Once the run's case directory holds authored files, a ``prepare_case``
    # on it is never the right move: with ``overwrite=False`` the tool
    # refuses (non-empty dir) and weak models misread that refusal as a hard
    # block and abandon the run; with ``overwrite=True`` it would ``rmtree``
    # every dict and the mesh authored so far. Intercept the non-empty case
    # with a guiding no-op pointing back at the productive path — overwrite
    # the one bad file in place. An *empty* pre-created dir falls through so
    # the normal first-call ``prepare_case`` (the Anthropic workflow opens
    # with one) still runs.
    if raw_name == "prepare_case" and args.get("case_path") in (known_case_paths or []):
        case_dir = Path(args["case_path"])
        if case_dir.is_dir() and any(case_dir.iterdir()):
            print("[harness] intercepted prepare_case on the run's non-empty case dir", file=sys.stderr)
            return (
                json.dumps(
                    {
                        "success": True,
                        "note": (
                            "The case directory already exists and holds your authored "
                            "files — you do not need prepare_case. To fix a file you got "
                            "wrong, call write_dict or copy_tutorial_dict again with the "
                            "same dict_name; it overwrites in place. Do NOT clear or "
                            "recreate the directory and do NOT abandon the run over "
                            "leftover files — just re-author the offending dict and re-run."
                        ),
                    }
                ),
                False,
            )

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
    tool_arg_names: dict[str, set[str]],
) -> None:
    """Drive the agent loop against Anthropic's tool-use API."""
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
            max_tokens=4096,
            system=system_prompt,
            tools=anthropic_tools,
            messages=messages,
        )

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

        if response.stop_reason == "end_turn" or not tool_uses:
            print(f"\n[harness] done after {iteration + 1} iteration(s).")
            return

        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            print(f"[tool] {tu.name}({json.dumps(tu.input)[:120]}...)")
            content, is_error = await call_tool(
                sessions, route, tu.name, tu.input,
                tools_with_case_path, known_case_paths, tool_arg_names,
            )
            entry: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": content,
            }
            if is_error:
                entry["is_error"] = True
            tool_results.append(entry)
        messages.append({"role": "user", "content": tool_results})

    print(f"\n[harness] hit max-iters ({max_iters}); stopping.")


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


async def run_ollama(
    sessions: dict[str, ClientSession],
    tools: list[dict[str, Any]],
    route: dict[str, tuple[str, str]],
    model: str,
    base_url: str,
    system_prompt: str,
    user_prompt: str,
    max_iters: int,
    tools_with_case_path: set[str],
    known_case_paths: list[str],
    tool_arg_names: dict[str, set[str]],
) -> None:
    """Drive the agent loop against Ollama's OpenAI-compatible API."""
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        sys.exit(
            "openai SDK not installed. Run `uv sync` from the repo root "
            "or install with `uv add openai`. (" + str(exc) + ")"
        )

    # Ollama requires a non-empty api_key field even though it ignores
    # the value. "ollama" is the conventional placeholder.
    client = AsyncOpenAI(base_url=base_url, api_key="ollama")
    openai_tools = to_openai_tools(tools)
    valid_tool_names: set[str] = {t["name"] for t in tools}
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Consecutive non-productive turns (rejected/garbled tool call or an
    # empty final channel). Reset to 0 the moment the model emits a real
    # tool call. Bounds an otherwise-silent spin if the model wedges.
    stalls = 0

    # Has the solver completed a successful run yet? Weak models tend to
    # "finish" with a prose summary while the solver is still erroring on a
    # dictionary, so we refuse to accept a final answer until at least one
    # ``run_solver`` has succeeded. A successful run is the only result that
    # carries ``walltime_s`` (failures return just reason + log_tail), which
    # makes this signal independent of the possibly-garbled tool name.
    solver_ran_ok = False

    for iteration in range(max_iters):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=openai_tools,
                max_tokens=16384,
            )
        except Exception as exc:
            # Ollama returns HTTP 500 with a tool-call-parse error when the
            # model emits garbage in the tool_calls slot ("error parsing tool
            # call: raw=..."). Recover by pushing a corrective user message
            # rather than aborting the whole run.
            err_text = str(exc)
            if "error parsing tool call" in err_text or "InternalServerError" in type(exc).__name__:
                stalls += 1
                print(
                    f"[harness] Ollama rejected the model's tool call "
                    f"({stalls}/{MAX_CONSECUTIVE_STALLS}): {err_text[:200]}"
                )
                if stalls >= MAX_CONSECUTIVE_STALLS:
                    print(f"\n[harness] {stalls} non-productive turns in a row; stopping.")
                    return
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
                stalls += 1
                print(
                    "[harness] content looks like an attempted tool call but didn't "
                    f"parse ({stalls}/{MAX_CONSECUTIVE_STALLS}) — sending corrective message."
                )
                if stalls >= MAX_CONSECUTIVE_STALLS:
                    print(f"\n[harness] {stalls} non-productive turns in a row; stopping.")
                    return
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
            # Empty response: the model emitted neither a tool call nor any
            # final-answer text. This is the dominant outcome for a reasoning
            # model like gpt-oss, which routinely spends a whole turn in its
            # reasoning channel and returns an empty final channel — and it
            # does so with finish_reason "length", "stop", OR None. An empty
            # turn is never task completion, so nudge regardless of the
            # finish_reason rather than mistaking the silence for "done".
            if not (msg.content or "").strip():
                stalls += 1
                print(
                    f"[harness] empty response (finish_reason={finish_reason}); nudging "
                    f"the model to continue ({stalls}/{MAX_CONSECUTIVE_STALLS})."
                )
                if stalls >= MAX_CONSECUTIVE_STALLS:
                    print(f"\n[harness] {stalls} empty turns in a row; stopping.")
                    return
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
            # Real final-answer prose with no tool call. Only accept it as
            # "done" once the solver has actually run — otherwise a weak model
            # ends the run with a plan/summary while the case is still failing
            # to solve (observed: it narrates "rerun simpleFoam" instead of
            # calling run_solver). Nudge it back to executing the fix.
            if not solver_ran_ok:
                stalls += 1
                print(
                    "[harness] model tried to finish but the solver has not run "
                    f"successfully yet ({stalls}/{MAX_CONSECUTIVE_STALLS}); nudging to continue."
                )
                if stalls >= MAX_CONSECUTIVE_STALLS:
                    print(f"\n[harness] {stalls} non-productive turns in a row; stopping.")
                    return
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You are NOT done: the solver has not completed a successful "
                            "run yet. Do not stop and do not just describe what to do — "
                            "DO it. Read the most recent run_solver error (its log_tail "
                            "names the dictionary and line at fault), fix that file in "
                            "place by calling write_dict or copy_tutorial_dict, then call "
                            "run_solver again. Only once the solver runs to a converged "
                            "result should you move on to validation."
                        ),
                    }
                )
                continue
            print(f"\n[harness] done after {iteration + 1} iteration(s). (finish_reason={finish_reason})")
            return

        # The model emitted at least one real tool call — forward progress,
        # so the stall streak is broken.
        stalls = 0
        for c in normalized_calls:
            args = c["arguments"]
            if isinstance(args, dict) and "__parse_error__" in args:
                err = f"Error: model emitted invalid JSON args: {args['__parse_error__']}"
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": err})
                continue
            print(f"[tool] {c['name']}({json.dumps(args)[:120]}...)")
            content, _is_error = await call_tool(
                sessions, route, c["name"], args,
                tools_with_case_path, known_case_paths, tool_arg_names,
            )
            if '"walltime_s"' in content:
                solver_ran_ok = True
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": content})

    print(f"\n[harness] hit max-iters ({max_iters}); stopping.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def load_system_prompt(
    repo_root: Path,
    backend: str,
    override_path: Path | None = None,
) -> str:
    """Read the system prompt.

    Defaults differ by backend: Anthropic gets the full CLAUDE.md
    workflow contract (~600 lines, designed for frontier models);
    Ollama gets the slim ``scripts/local_system_prompt.md`` because
    local 20–30B models lose the thread under the full contract.
    Pass ``--system-prompt-file`` to override.
    """
    if override_path is not None:
        if not override_path.is_file():
            sys.exit(f"--system-prompt-file {override_path} does not exist.")
        return override_path.read_text(encoding="utf-8")
    if backend == "ollama":
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

    async with AsyncExitStack() as stack:
        sessions = await connect_servers(mcp_config, stack)
        tools, route = await gather_tools(sessions)
        print(
            f"[harness] {len(tools)} tools across {len(sessions)} server(s).",
            file=sys.stderr,
        )

        # Per-tool argument-name maps, both derived from the schemas the
        # servers advertise (no hardcoded lists): which tools take a
        # ``case_path`` (for path auto-correction), and the full set of
        # valid argument names per tool (for unknown-kwarg repair).
        tools_with_case_path = {
            t["name"]
            for t in tools
            if "case_path" in ((t["input_schema"] or {}).get("properties") or {})
        }
        tool_arg_names = {
            t["name"]: set(((t["input_schema"] or {}).get("properties") or {}).keys())
            for t in tools
        }

        # A frontier model lands a clean call almost every turn; a local
        # 20–30B model wastes many turns on garbled calls, so it gets a
        # larger budget. An explicit --max-iters overrides either default.
        if args.max_iters is not None:
            max_iters = args.max_iters
        elif args.backend == "ollama":
            max_iters = DEFAULT_OLLAMA_MAX_ITERS
        else:
            max_iters = DEFAULT_ANTHROPIC_MAX_ITERS

        if args.backend == "anthropic":
            await run_anthropic(
                sessions=sessions,
                tools=tools,
                route=route,
                model=args.model or DEFAULT_ANTHROPIC_MODEL,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_iters=max_iters,
                tools_with_case_path=tools_with_case_path,
                known_case_paths=known_case_paths,
                tool_arg_names=tool_arg_names,
            )
        elif args.backend == "ollama":
            await run_ollama(
                sessions=sessions,
                tools=tools,
                route=route,
                model=args.model or DEFAULT_OLLAMA_MODEL,
                base_url=args.ollama_base_url,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_iters=max_iters,
                tools_with_case_path=tools_with_case_path,
                known_case_paths=known_case_paths,
                tool_arg_names=tool_arg_names,
            )
        else:
            sys.exit(f"Unknown backend: {args.backend}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--backend",
        choices=["anthropic", "ollama"],
        required=True,
        help="Agent runtime. 'anthropic' uses ANTHROPIC_API_KEY; "
        "'ollama' uses a local Ollama instance.",
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
        default=None,
        help="Hard cap on agent iterations (each iteration = one model call + any "
        f"tool calls). Default depends on backend: {DEFAULT_ANTHROPIC_MAX_ITERS} "
        f"for anthropic, {DEFAULT_OLLAMA_MAX_ITERS} for ollama (which wastes more "
        "turns on garbled tool calls).",
    )
    parser.add_argument(
        "--mcp-config",
        type=Path,
        default=None,
        help="Path to an MCP config file. Defaults to .mcp.json at the repo root.",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
        help=f"Ollama OpenAI-compatible API endpoint. Default: {DEFAULT_OLLAMA_BASE_URL}.",
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

    if args.backend == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(
            "ANTHROPIC_API_KEY is not set. Either export it or use --backend ollama."
        )

    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        print("\n[harness] interrupted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
