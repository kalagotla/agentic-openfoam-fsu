"""Run a benchmark matrix and score every run.

Reads `suite.yaml`, expands it into runs (case x model x corpus state x
repeat), drives each through `scripts/run_agent.py`, moves the finished
case into the run's own results directory, and scores it with
`score_report.py`. Resumable: a run whose `record.json` already exists is
skipped, so an interrupted matrix continues rather than restarting.

Three things worth knowing about the design:

**Repeats, not seeds.** Neither the Anthropic API nor Ollama exposes a
sampling seed, so repeated runs of an identical configuration cannot be
made identical. A repeat index measures nondeterminism; it does not
reproduce it. Calling the axis `repeat` keeps that honest — a `seed`
label would imply a control the harness does not have.

**Concurrency is per case, not per run.** Every run of one scenario
authors into the same `cases/work/<name>/` path, so repeats of a case are
serialised while different cases run in parallel. Racing two repeats of
the same case would have them overwrite each other's case directory.

**Two ways to drive a run, and they are billed differently.** The
`claude-cli` backend shells out to Claude Code in headless mode, which
authenticates as the logged-in account — so runs are drawn from a Pro or
Max subscription. Every other backend goes through `run_agent.py`, whose
Anthropic path is an API-SDK client and can only spend API credit.

The distinction is easy to lose by accident: Claude Code prefers an API
key when `ANTHROPIC_API_KEY` is present in the environment, so a shell
that has sourced a `.env` will quietly bill the API even on a subscription
machine. This runner strips that variable from the `claude-cli`
environment for exactly that reason, and records which billing path a run
used.

**Gated runs stall unless the operator pre-approves them.** The automation
gate reads `automation_level` from the canonical scenario file and prompts
on stdin, and a subprocess with no stdin reads that prompt as a refusal —
so a level 1-3 scenario run unattended stops at its first gated tool.
`--approve-gates` feeds approvals, which is the operator answering in
advance rather than a bypass: the gate still fires, and the run record
says the approvals were pre-supplied so a paused-and-approved run is never
mistaken for one that was never gated. Without the flag the runner warns
up front instead of letting the matrix discover it one stall at a time.

**Corpus state is verified, never faked.** The `corpus_state` axis is
recorded and checked against what is actually on disk; the harness will
not quietly edit the researcher's corpus to match a label. Set the state
up out of band — a git worktree at the intended ref is the reproducible
way — and the runner refuses to mislabel a run whose corpus does not
match.

Usage:

    # See the matrix without running anything
    uv run python scripts/eval/run_matrix.py --tier 1 --dry-run

    # Run tier 1 on one model, 3 repeats, 2 cases at a time
    uv run python scripts/eval/run_matrix.py --tier 1 --models claude-opus-5 \\
        --repeats 3 --jobs 2
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from score_report import score_case
from suite import Suite, SuiteCase, load_suite

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITE = Path(__file__).resolve().parent / "suite.yaml"
DEFAULT_RESULTS = Path(__file__).resolve().parent / "results"

# The single-turn fact belongs in every run's prompt, gated or not: this is
# a headless invocation, so anything the agent postpones to a later turn is
# lost. naca-0012 ended having launched a 30-minute mesh and said it would
# "check back in ~10 minutes"; there was no next turn to check back in.
PROMPT_TEMPLATE = (
    "Set up and run the case described in {scenario}. You are running "
    "headless with no further turns: the run ends when you stop, so carry "
    "each step through to its result rather than deferring it to a later "
    "check-in. If a long tool call is aborted, retry or reduce the work "
    "until it completes within the call."
)

# The throughput arm's prompt. Disabling the gate hook removes enforcement
# but not the instruction: a run with the hook off still stopped before
# meshing because CLAUDE.md tells the agent to honour the scenario's
# automation_level in its own behaviour, and it did — authoring the whole
# case, narrating it, and waiting for a review that was never coming.
#
# That compliance is a result worth having, and it means an unattended arm
# has to declare itself. This is the plan's level-5 arm stated to the agent
# rather than smuggled past it, and every record says the override was
# applied so no one reads these runs as level-2 behaviour.
UNATTENDED_SUFFIX = (
    " This is an unattended benchmark run: treat automation_level as 5 "
    "(Auto) for this run regardless of what the scenario declares, and do "
    "not stop for researcher approval at any phase. Narrate every step as "
    "usual."
)

# Backends that shell out to Claude Code rather than run_agent.py.
CLAUDE_CLI_BACKENDS = frozenset({"claude-cli", "claude-code"})

# Variables that would divert a Claude Code run onto API billing. Removed
# from the child environment so a subscription run stays a subscription run.
API_BILLING_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

# Claude Code aborts an MCP tool that sends no progress for its idle
# timeout, which defaults to 1800s — exactly the cap `run_snappy_hex_mesh`
# sets on snappy itself. The client therefore wins the race and the
# server's own timeout can never fire, so a long mesh comes back as a
# client abort with no log to diagnose. Observed on naca-0012: snappy was
# still carving when the tool was aborted, and the run ended with the agent
# deferring to a turn that headless mode never provides.
#
# The client is given more silence than the longest server-side tool cap so
# the server's timeout stays the authoritative one.
MCP_IDLE_TIMEOUT_MS = "2700000"  # 45 min

# Settings handed to Claude Code for a throughput run: the project's own
# settings with the automation-gate hook removed. Every shipped scenario
# declares level 2 or 3, which gates meshing and solving, so an unattended
# matrix would otherwise stop at the first mesh step of every case.
#
# This is the operator choosing to run the level-5 arm the plan describes,
# not the agent talking its way past a gate: it takes an explicit flag, the
# shipped settings are untouched, and the run record says the gate was off
# and that HITL compliance is therefore unmeasurable for that run.
UNGATED_SETTINGS_NAME = "benchmark-ungated-settings.json"


@dataclass(frozen=True)
class Run:
    """One cell of the matrix."""

    case_key: str
    scenario: str
    model: str
    backend: str
    corpus_state: str
    repeat: int
    # Which endpoint served the run. Two servers can host the same model
    # name and behave differently, so it belongs in the record.
    base_url: str | None = None

    @property
    def run_id(self) -> str:
        # Local servers name models with paths and tags
        # ("meta-llama/Llama-3.3-70B", "gpt-oss:20b"), neither of which is
        # safe in a directory name.
        model_slug = (self.model or "auto").replace("/", "-").replace(":", "-")
        return f"{self.case_key}__{model_slug}__{self.corpus_state}__r{self.repeat}"


# ---------------------------------------------------------------------------
# Matrix construction
# ---------------------------------------------------------------------------


def build_matrix(
    suite: Suite,
    *,
    models: list[str],
    backend: str,
    corpus_states: list[str],
    repeats: int | None,
    tiers: list[int] | None,
    keys: list[str] | None,
    base_url: str | None = None,
) -> list[Run]:
    """Expand the suite into runs, skipping cases that cannot be scored."""
    runs: list[Run] = []
    for case in suite.runnable():
        if tiers and case.tier not in tiers:
            continue
        if keys and case.key not in keys:
            continue
        n = repeats if repeats is not None else case.seeds(suite.defaults)
        for model in models:
            for state in corpus_states:
                for r in range(1, n + 1):
                    runs.append(
                        Run(
                            case_key=case.key,
                            scenario=str(case.scenario),
                            # "auto" defers the choice to the server, which is
                            # how a single-model local endpoint is addressed.
                            model="" if model == "auto" else model,
                            backend=backend,
                            corpus_state=state,
                            repeat=r,
                            base_url=base_url,
                        )
                    )
    return runs


def scenario_case_name(scenario_path: Path) -> str:
    """The `name:` a scenario declares — where the agent authors the case."""
    import yaml

    data = yaml.safe_load(scenario_path.read_text(encoding="utf-8")) or {}
    return str(data.get("name") or scenario_path.stem)


# ---------------------------------------------------------------------------
# Corpus state
# ---------------------------------------------------------------------------


def observe_corpus(repo_root: Path) -> dict[str, Any]:
    """What the corpus actually holds right now."""
    corpus = repo_root / "corpus"
    entries = sorted(
        str(p.relative_to(repo_root))
        for p in corpus.rglob("*.md")
        if p.name != "README.md" and ".draft." not in p.name
    )
    return {"n_annotations": len(entries), "annotations": entries}


def check_corpus_state(repo_root: Path, declared: str) -> str | None:
    """Return a complaint if the corpus on disk contradicts the label.

    Silently running a `corpus_state: empty` arm against a populated corpus
    would invalidate the transfer experiment and leave no trace, so a
    mismatch stops the run instead.
    """
    observed = observe_corpus(repo_root)
    n = observed["n_annotations"]
    if declared == "empty" and n:
        return (
            f"corpus_state='empty' but {n} annotation(s) are present: "
            f"{', '.join(observed['annotations'][:3])}"
            f"{' …' if n > 3 else ''}"
        )
    if declared == "seeded" and not n:
        return "corpus_state='seeded' but the corpus holds no annotations"
    return None


# ---------------------------------------------------------------------------
# Executing one run
# ---------------------------------------------------------------------------


# Suffix for the throwaway scenario an ungated run is driven from. The gate
# hook resolves `cases/work/<X>` to `cases/scenarios/<X>.yaml`, so a level-5
# declaration only reaches it through a file at that path — a `--settings`
# file with the hooks block stripped does not, because project settings
# still load. Observed on a real run: naca-0012 was handed ungated settings,
# and the hook denied `run_blockmesh` twice anyway.
UNGATED_SCENARIO_SUFFIX = ".benchmark-ungated"

# Ablations: an arm run with one server withheld, to turn a design claim
# into a difference. The plan's §5 asks what the consultant is worth; the
# only way to answer is to run the same case without it.
ABLATABLE_SERVERS = ("consultant", "validation", "research_assistant")
ABLATED_MCP_NAME = "benchmark-ablated-mcp.json"


def write_ablated_mcp_config(repo_root: Path, out_dir: Path, drop: tuple[str, ...]) -> Path:
    """The project's MCP config with named servers removed.

    Written into the run's own output directory rather than over
    `.mcp.json`, so the shipped config is never touched and the file the
    run used is kept beside its transcript.
    """
    source = repo_root / ".mcp.json"
    config = json.loads(source.read_text(encoding="utf-8"))
    servers = config.get("mcpServers", {})
    missing = [name for name in drop if name not in servers]
    if missing:
        raise ValueError(f"cannot ablate absent server(s): {', '.join(missing)}")
    config["mcpServers"] = {
        name: spec for name, spec in servers.items() if name not in drop
    }
    target = out_dir / ABLATED_MCP_NAME
    target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return target


def write_ungated_scenario(scenario_path: Path) -> Path:
    """A copy of the scenario declaring level 5, beside the original.

    The shipped scenario is the researcher's declaration and is never
    edited — this is the operator declaring the plan's level-5 arm in the
    one place the enforcement layer looks. The copy is removed when the run
    ends, and the run record names it so a throughput run is never mistaken
    for a gated one.
    """
    import yaml

    data = yaml.safe_load(scenario_path.read_text(encoding="utf-8")) or {}
    name = str(data.get("name") or scenario_path.stem)
    data["name"] = name + UNGATED_SCENARIO_SUFFIX
    data["automation_level"] = 5
    target = scenario_path.with_name(
        scenario_path.stem + UNGATED_SCENARIO_SUFFIX + scenario_path.suffix
    )
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return target


def scenario_automation_level(scenario_path: Path, default: int = 2) -> int:
    """The `automation_level` a scenario declares (default 2, per CLAUDE.md)."""
    import yaml

    try:
        data = yaml.safe_load(scenario_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return default
    try:
        return int(data.get("automation_level", default))
    except (TypeError, ValueError):
        return default


def gated_cases(runs: list[Run], repo_root: Path) -> dict[str, int]:
    """Selected cases whose level makes the gate fire, keyed to their level."""
    out: dict[str, int] = {}
    for r in runs:
        level = scenario_automation_level(repo_root / r.scenario)
        if level <= 3:
            out[r.case_key] = level
    return out


def execute_run(
    run: Run,
    *,
    suite: Suite,
    results_dir: Path,
    repo_root: Path,
    timeout_s: int,
    max_iters: int,
    resume: bool,
    approve_gates: bool = False,
    ungated: bool = False,
    ablate: tuple[str, ...] = (),
) -> dict[str, Any]:
    # An ablated run is a different arm, not a repeat of the ordinary one:
    # it must not land in the same directory, and `--resume` must not treat
    # one as satisfying the other.
    run_id = run.run_id + (("__no-" + "-".join(ablate)) if ablate else "")
    out_dir = results_dir / run_id
    record_path = out_dir / "record.json"
    if resume and record_path.is_file():
        return {"run_id": run_id, "status": "skipped_existing"}

    out_dir.mkdir(parents=True, exist_ok=True)
    shipped_scenario = repo_root / run.scenario
    declared_level = scenario_automation_level(shipped_scenario)
    # Only the Claude Code backend has a hook to get past; run_agent.py
    # applies the same policy in-process and honours --approve-gates.
    needs_copy = (
        ungated
        and run.backend in CLAUDE_CLI_BACKENDS
        and declared_level <= 3
    )
    ungated_scenario = write_ungated_scenario(shipped_scenario) if needs_copy else None
    scenario_path = ungated_scenario or shipped_scenario
    case_name = scenario_case_name(scenario_path)
    work_case = repo_root / "cases" / "work" / case_name

    meta: dict[str, Any] = {
        **asdict(run),
        "run_id": run_id,
        "scenario_case_name": case_name,
        "git_commit": _git_commit(repo_root),
        "corpus": observe_corpus(repo_root),
        "automation_level": declared_level,
        # Recorded so a run that paused and was approved in advance is never
        # read as a run that was never gated.
        "gate_approvals_presupplied": approve_gates,
        # Which servers the run could not reach. Empty is the ordinary arm;
        # a populated list makes every number below an ablation result.
        "ablated_servers": list(ablate),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    try:
        complaint = check_corpus_state(repo_root, run.corpus_state)
        if complaint:
            meta["status"] = "aborted_corpus_mismatch"
            meta["detail"] = complaint
            (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
            return {"run_id": run_id, "status": "aborted_corpus_mismatch"}

        if work_case.exists():
            # A leftover from an earlier attempt would be picked up as this
            # run's output, so park it rather than authoring on top of it.
            parked = out_dir / "preexisting_case"
            shutil.move(str(work_case), str(parked))
            meta["parked_preexisting_case"] = str(parked)

        prompt = PROMPT_TEMPLATE.format(
            scenario=str(scenario_path.relative_to(repo_root))
        )
        if ungated:
            prompt += UNATTENDED_SUFFIX
        child_env = dict(os.environ)
        uses_claude_cli = run.backend in CLAUDE_CLI_BACKENDS

        if uses_claude_cli:
            settings_path = (
                write_ungated_settings(repo_root, out_dir) if ungated else None
            )
            # An ungated run is unattended by definition, so ordinary tool
            # permissions cannot be left to a prompt nobody will answer.
            mcp_config = (
                write_ablated_mcp_config(repo_root, out_dir, ablate)
                if ablate
                else None
            )
            cmd = _claude_cli_command(
                run, repo_root, prompt, approve_gates or ungated,
                settings_path, mcp_config,
            )
            # Claude Code prefers an API key when one is present, which would
            # silently move a subscription run onto API billing.
            for var in API_BILLING_VARS:
                child_env.pop(var, None)
            child_env.setdefault(
                "CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT", MCP_IDLE_TIMEOUT_MS
            )
            meta["mcp_idle_timeout_ms"] = child_env[
                "CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT"
            ]
            meta["billing"] = "subscription"
            # This backend has no turn cap; the timeout is the only bound.
            meta["max_iters_enforced"] = False
            # Pre-approval cannot switch off a hook-based gate here, so a gated
            # scenario still pauses. Recorded so a paused run is not read as a
            # run that was allowed to proceed.
            meta["gate_bypass_effective"] = False
            # The hook is never switched off — it is driven from a scenario copy
            # that declares level 5, so it allows rather than being bypassed.
            meta["gate_hook_disabled"] = False
            meta["ungated_via_scenario_copy"] = (
                str(ungated_scenario.relative_to(repo_root)) if ungated_scenario else None
            )
            meta["gate_off"] = ungated
            # With the gate off there is nothing to comply with, so the metric
            # is absent for this run rather than trivially perfect.
            meta["hitl_measurable"] = not ungated
            meta["automation_level_override"] = 5 if ungated else None
        else:
            cmd = [
                sys.executable,
                str(repo_root / "scripts" / "run_agent.py"),
                "--backend",
                run.backend,
                "--prompt",
                prompt,
                "--max-iters",
                str(max_iters),
                "--run-summary",
                str(out_dir / "run_summary.json"),
            ]
            if run.model:
                cmd += ["--model", run.model]
            if run.base_url:
                cmd += ["--base-url", run.base_url]
            meta["billing"] = "api" if run.backend == "anthropic" else "local"
            meta["max_iters_enforced"] = True
        log_path = out_dir / "agent.log"
        started = time.time()
        try:
            with log_path.open("w") as log:
                proc = subprocess.run(
                    cmd,
                    cwd=repo_root,
                    env=child_env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    # Approvals the operator supplies in advance. With none, the
                    # gate reads EOF as a refusal and the run stops there.
                    input=("y\n" * 200) if approve_gates else "",
                    text=True,
                    timeout=timeout_s,
                    check=False,
                )
            meta["exit_code"] = proc.returncode
            meta["status"] = "completed" if proc.returncode == 0 else "agent_error"
        except subprocess.TimeoutExpired:
            meta["exit_code"] = None
            meta["status"] = "timeout"
        meta["wall_clock_s"] = round(time.time() - started, 2)
        meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Move the authored case in beside its record so the artefacts and the
        # numbers derived from them stay together, and the next repeat of this
        # case starts from a clean path.
        case_dest = out_dir / "case"
        if work_case.exists():
            shutil.move(str(work_case), str(case_dest))
        meta["case_present"] = case_dest.exists()
        if meta.get("status") == "completed" and not case_dest.exists():
            # A clean exit having authored nothing is not a completed run. The
            # usual cause is a tool the agent was refused, which it reports in
            # prose and then stops — leaving an exit code of zero behind.
            meta["status"] = "no_case_authored"

        if uses_claude_cli:
            # Claude Code writes its transcript to stdout rather than a summary
            # file, so the ledger is reconstructed from the stream.
            run_summary = parse_claude_stream(log_path.read_text(errors="replace"))
            run_summary["model"] = run.model or "default"
            (out_dir / "run_summary.json").write_text(
                json.dumps(run_summary, indent=2) + "\n"
            )
        else:
            run_summary = _read_json(out_dir / "run_summary.json") or {}
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

        if case_dest.exists():
            record = score_case(
                case_dest,
                suite_entry=suite.case(run.case_key).raw,
                run_meta={**meta, "cost": run_summary},
                root=repo_root,
            )
        else:
            # No case directory means nothing to score. Record that rather than
            # omitting the run, so a matrix's failures stay countable.
            record = {
                "run": {**meta, "cost": run_summary},
                "suite": {"key": run.case_key},
                "capability": {
                    "setup_success": False,
                    "mesh_pass": None,
                    "converged": None,
                    "validated": None,
                    "first_try_validated": None,
                    "n_retries": 0,
                },
                "trust": None,
            }
        record_path.write_text(json.dumps(record, indent=2) + "\n")
        return {"run_id": run_id, "status": meta["status"]}
    finally:
        if ungated_scenario is not None:
            # Transient by construction: the shipped scenario is the
            # researcher's declaration and stays as written.
            ungated_scenario.unlink(missing_ok=True)


def parse_claude_stream(text: str) -> dict[str, Any]:
    """Summarise a Claude Code ``stream-json`` transcript into ledger shape.

    Produces the same fields `run_agent.py`'s RunLedger emits, so a run is
    scored identically whichever backend produced it. Cost is carried as
    ``cost_usd_equivalent``: on a subscription nothing is charged, and the
    figure is what the same tokens would have cost through the API — useful
    for comparing arms, misleading if read as a bill.
    """
    summary: dict[str, Any] = {
        "backend": "claude-cli",
        "iterations": None,
        "stop_reason": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "tool_calls": 0,
        "tool_errors": 0,
        "per_tool": {},
        "permission_denials": [],
        "session_id": None,
        "cost_usd_equivalent": None,
        "billing": "subscription",
    }
    per_tool: dict[str, int] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        # `message` is a dict on assistant/user turns and a plain string on
        # system notices — the automation gate's prompt arrives that way —
        # so its type has to be checked rather than assumed.
        inner = message.get("message")
        content = inner.get("content") if isinstance(inner, dict) else None
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    name = str(block.get("name", "?"))
                    per_tool[name] = per_tool.get(name, 0) + 1
                    summary["tool_calls"] += 1
                elif block.get("type") == "tool_result" and block.get("is_error"):
                    summary["tool_errors"] += 1

        if message.get("type") != "result":
            continue
        summary["iterations"] = message.get("num_turns")
        summary["stop_reason"] = message.get("stop_reason") or message.get("subtype")
        summary["session_id"] = message.get("session_id")
        summary["cost_usd_equivalent"] = message.get("total_cost_usd")
        summary["permission_denials"] = message.get("permission_denials") or []
        usage = message.get("usage") or {}
        summary["input_tokens"] = int(usage.get("input_tokens") or 0)
        summary["output_tokens"] = int(usage.get("output_tokens") or 0)
        summary["cache_read_tokens"] = int(usage.get("cache_read_input_tokens") or 0)
        summary["cache_write_tokens"] = int(
            usage.get("cache_creation_input_tokens") or 0
        )

    summary["per_tool"] = dict(sorted(per_tool.items()))
    return summary


def write_ungated_settings(repo_root: Path, out_dir: Path) -> Path:
    """Project settings with the automation-gate hook stripped out.

    Everything else — permissions, enabled MCP servers — is carried over,
    so the only difference from a normal run is the gate. Written into the
    run's own directory rather than the repo, so it travels with the record
    that says it was used.
    """
    source = repo_root / ".claude" / "settings.json"
    try:
        settings = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        settings = {}
    settings.pop("hooks", None)
    # Turning off the gate is not enough on its own. The project's allow
    # list names a handful of tools, so an unattended run was denied
    # prepare_case and record_step and stopped to ask for access — exiting
    # cleanly, having authored nothing. A benchmark run needs the whole
    # surface of the four servers, granted at server level.
    permissions = settings.setdefault("permissions", {})
    allow = permissions.setdefault("allow", [])
    for server in ("openfoam", "validation", "consultant", "research_assistant"):
        entry = f"mcp__{server}"
        if entry not in allow:
            allow.append(entry)
    target = out_dir / UNGATED_SETTINGS_NAME
    target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return target


def _claude_cli_command(
    run: Run,
    repo_root: Path,
    prompt: str,
    approve_gates: bool,
    settings_path: Path | None = None,
    mcp_config: Path | None = None,
) -> list[str]:
    """Headless Claude Code, billed to the logged-in account's plan."""
    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--mcp-config",
        str(mcp_config or repo_root / ".mcp.json"),
    ]
    if run.model:
        cmd += ["--model", run.model]
    # A permission mode does NOT override the automation gate. The gate is a
    # PreToolUse hook returning "ask", and a run under bypassPermissions was
    # still stopped at the validation record_step exactly as
    # automation_level 3 asks — verified on a real run. That is the correct
    # behaviour: a safety gate a flag could switch off would not be one.
    #
    # So the mode here only governs ordinary tool permissions, and gated
    # scenarios pause under this backend no matter what. Unattended matrix
    # runs need scenarios that declare level 4 or 5.
    cmd += [
        "--permission-mode",
        "bypassPermissions" if approve_gates else "acceptEdits",
    ]
    if settings_path is not None:
        cmd += ["--settings", str(settings_path)]
    return cmd


def _git_commit(repo_root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Driving the matrix
# ---------------------------------------------------------------------------


def group_by_case(runs: list[Run]) -> dict[str, list[Run]]:
    groups: dict[str, list[Run]] = {}
    for r in runs:
        groups.setdefault(r.case_key, []).append(r)
    return groups


def run_matrix(
    runs: list[Run],
    *,
    suite: Suite,
    results_dir: Path,
    repo_root: Path,
    jobs: int,
    timeout_s: int,
    max_iters: int,
    resume: bool,
    approve_gates: bool = False,
    ungated: bool = False,
    ablate: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    groups = group_by_case(runs)
    outcomes: list[dict[str, Any]] = []

    def run_group(case_key: str, group: list[Run]) -> list[dict[str, Any]]:
        out = []
        for r in group:
            print(f"[matrix] {r.run_id}", flush=True)
            out.append(
                execute_run(
                    r,
                    suite=suite,
                    results_dir=results_dir,
                    repo_root=repo_root,
                    timeout_s=timeout_s,
                    max_iters=max_iters,
                    resume=resume,
                    approve_gates=approve_gates,
                    ungated=ungated,
                    ablate=ablate,
                )
            )
        return out

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = [
            pool.submit(run_group, key, group) for key, group in groups.items()
        ]
        for f in futures:
            outcomes.extend(f.result())
    return outcomes


def describe(runs: list[Run], suite: Suite) -> str:
    lines = [f"{len(runs)} run(s) across {len(group_by_case(runs))} case(s):", ""]
    for key, group in group_by_case(runs).items():
        case: SuiteCase = suite.case(key)
        lines.append(
            f"  {key:26} tier {case.tier}  {case.novelty}  "
            f"{case.compute_weight:6}  {len(group)} run(s)"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    ap.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    ap.add_argument(
        "--backend",
        default="claude-cli",
        help=(
            "claude-cli drives headless Claude Code and is billed to the "
            "logged-in account's subscription. anthropic, ollama, vllm, "
            "lmstudio, and openai go through run_agent.py; the anthropic one "
            "spends API credit."
        ),
    )
    ap.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible endpoint for a local or remote server.",
    )
    ap.add_argument(
        "--models",
        nargs="+",
        default=["claude-opus-5"],
        help=(
            "Model names to sweep. Pass 'auto' to let the server say what it "
            "is serving (one run per endpoint)."
        ),
    )
    ap.add_argument(
        "--corpus-states",
        nargs="+",
        default=["seeded"],
        choices=["empty", "seeded"],
        help="Corpus arms to run. Verified against the corpus on disk, never faked.",
    )
    ap.add_argument("--repeats", type=int, default=None)
    ap.add_argument("--tier", type=int, nargs="+", dest="tiers")
    ap.add_argument("--case", nargs="+", dest="keys", help="Run only these case keys")
    ap.add_argument("--jobs", type=int, default=1, help="Cases in parallel")
    ap.add_argument("--timeout", type=int, default=7200, help="Per-run timeout (s)")
    ap.add_argument("--max-iters", type=int, default=120)
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument(
        "--ablate",
        nargs="+",
        default=[],
        choices=list(ABLATABLE_SERVERS),
        help=(
            "Withhold these MCP servers from the run. The arm that turns a "
            "design claim into a difference: --ablate consultant answers "
            "what the consultant is worth by running the same case without "
            "it. The shipped .mcp.json is untouched; the config the run "
            "actually used is written into its own output directory."
        ),
    )
    ap.add_argument(
        "--ungated",
        action="store_true",
        help=(
            "Run the throughput arm: hand Claude Code a copy of the project "
            "settings with the automation-gate hook removed. Every shipped "
            "scenario declares level 2 or 3, so without this an unattended "
            "matrix stalls at the first meshing step of every case. The "
            "shipped settings are untouched and each record says the gate "
            "was off, which makes HITL compliance unmeasurable for that run."
        ),
    )
    ap.add_argument(
        "--approve-gates",
        action="store_true",
        help=(
            "Pre-supply approvals for the automation gate. The gate still "
            "fires and the run record says the approvals were pre-supplied. "
            "Without this, a level 1-3 scenario stalls when run unattended."
        ),
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    suite = load_suite(args.suite)
    runs = build_matrix(
        suite,
        models=args.models,
        backend=args.backend,
        corpus_states=args.corpus_states,
        repeats=args.repeats,
        tiers=args.tiers,
        keys=args.keys,
        base_url=args.base_url,
    )
    print(describe(runs, suite))

    gated = gated_cases(runs, args.repo_root)
    if gated and args.ungated:
        listing = ", ".join(f"{k} (level {v})" for k, v in sorted(gated.items()))
        print(
            f"\n[matrix] NOTE: running ungated. {listing} would otherwise "
            "pause; each is driven from a level-5 copy of its scenario, so "
            "the gate allows rather than being switched off, and HITL "
            "compliance is not measurable from these runs."
        )
    elif gated:
        listing = ", ".join(f"{k} (level {v})" for k, v in sorted(gated.items()))
        if args.backend in CLAUDE_CLI_BACKENDS:
            print(
                f"\n[matrix] NOTE: {listing} will pause at the automation gate, "
                "and --approve-gates cannot prevent it on this backend: the "
                "gate is a Claude Code hook and no permission mode overrides "
                "it. The run still completes its work and stops at the gated "
                "step. For unattended throughput, use scenarios declaring "
                "automation_level 4 or 5."
            )
        elif not args.approve_gates:
            print(
                f"\n[matrix] WARNING: {listing} will pause at the automation "
                "gate. Unattended, the gate reads no-stdin as a refusal and "
                "these runs stop at their first gated tool. Pass "
                "--approve-gates to supply approvals in advance, or run them "
                "with an operator present."
            )

    if args.dry_run:
        return 0
    if not runs:
        print("[matrix] nothing to run.")
        return 0

    args.results_dir.mkdir(parents=True, exist_ok=True)
    outcomes = run_matrix(
        runs,
        suite=suite,
        results_dir=args.results_dir,
        repo_root=args.repo_root,
        jobs=args.jobs,
        timeout_s=args.timeout,
        max_iters=args.max_iters,
        resume=not args.no_resume,
        approve_gates=args.approve_gates,
        ungated=args.ungated,
        ablate=tuple(args.ablate),
    )
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o["status"]] = counts.get(o["status"], 0) + 1
    print("\n[matrix] " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
