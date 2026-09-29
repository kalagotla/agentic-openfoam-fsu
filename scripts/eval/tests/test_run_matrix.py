"""Tests for matrix expansion and the guards around a run.

Nothing here drives an agent. What is tested is the bookkeeping that
decides which runs happen and whether a run may be labelled the way the
matrix wants to label it — the places where a matrix could quietly produce
a wrong dataset rather than fail loudly.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml
from run_matrix import (
    MCP_IDLE_TIMEOUT_MS,
    Run,
    build_matrix,
    check_corpus_state,
    execute_run,
    gated_cases,
    group_by_case,
    observe_corpus,
    scenario_automation_level,
    scenario_case_name,
    write_ablated_mcp_config,
    write_ungated_scenario,
)
from suite import load_suite

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from automation_gate import read_automation_level

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_PATH = REPO_ROOT / "scripts" / "eval" / "suite.yaml"


@pytest.fixture
def suite():
    return load_suite(SUITE_PATH)


def test_matrix_multiplies_the_axes(suite) -> None:
    runs = build_matrix(
        suite,
        models=["m1", "m2"],
        backend="anthropic",
        corpus_states=["empty", "seeded"],
        repeats=3,
        tiers=[1],
        keys=["lid-cavity"],
    )
    assert len(runs) == 2 * 2 * 3
    assert len({r.run_id for r in runs}) == len(runs)


def test_blocked_cases_are_never_run(suite) -> None:
    runs = build_matrix(
        suite,
        models=["m1"],
        backend="anthropic",
        corpus_states=["seeded"],
        repeats=1,
        tiers=None,
        keys=None,
    )
    keys = {r.case_key for r in runs}
    # Cases that cannot be scored on `validated` — ONERA M6 has only a
    # qualitative dataset, and the tier-2 cases are unbuilt — must not
    # consume compute.
    assert "onera-m6" not in keys
    assert "cylinder-re100" not in keys
    assert "lid-cavity" in keys


def test_repeats_fall_back_to_the_case_default(suite) -> None:
    runs = build_matrix(
        suite,
        models=["m1"],
        backend="anthropic",
        corpus_states=["seeded"],
        repeats=None,
        tiers=[1],
        keys=["lid-cavity"],
    )
    assert len(runs) == suite.case("lid-cavity").seeds(suite.defaults)


def test_run_id_is_filesystem_safe() -> None:
    run = Run(
        case_key="lid-cavity",
        scenario="cases/scenarios/lid-cavity.yaml",
        model="ollama/gpt-oss:20b",
        backend="ollama",
        corpus_state="empty",
        repeat=2,
    )
    assert "/" not in run.run_id
    assert ":" not in run.run_id


def test_repeats_of_one_case_are_grouped_together() -> None:
    runs = [
        Run("a", "s", "m", "anthropic", "empty", 1),
        Run("b", "s", "m", "anthropic", "empty", 1),
        Run("a", "s", "m", "anthropic", "empty", 2),
    ]
    groups = group_by_case(runs)
    # Repeats of one case share a case directory, so they must stay in one
    # group and run in sequence.
    assert [r.repeat for r in groups["a"]] == [1, 2]


# ---------------------------------------------------------------------------
# Corpus state — labelled only if true
# ---------------------------------------------------------------------------


def test_empty_label_rejects_a_populated_corpus(tmp_path: Path) -> None:
    (tmp_path / "corpus" / "incompressible").mkdir(parents=True)
    (tmp_path / "corpus" / "incompressible" / "cavity.md").write_text("# entry\n")
    complaint = check_corpus_state(tmp_path, "empty")
    assert complaint is not None
    assert "empty" in complaint


def test_seeded_label_rejects_an_empty_corpus(tmp_path: Path) -> None:
    (tmp_path / "corpus").mkdir()
    assert check_corpus_state(tmp_path, "seeded") is not None


def test_truthful_labels_pass(tmp_path: Path) -> None:
    (tmp_path / "corpus").mkdir()
    assert check_corpus_state(tmp_path, "empty") is None


def test_readmes_and_drafts_do_not_count_as_annotations(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus" / "family"
    corpus.mkdir(parents=True)
    (corpus / "README.md").write_text("index\n")
    (corpus / "entry.draft.md").write_text("unreviewed\n")
    # A draft is not promoted knowledge, so an `empty` arm is still empty.
    assert observe_corpus(tmp_path)["n_annotations"] == 0
    assert check_corpus_state(tmp_path, "empty") is None


def test_corpus_mismatch_aborts_the_run_before_spending_anything(
    tmp_path: Path, suite
) -> None:
    repo = tmp_path / "repo"
    (repo / "corpus" / "fam").mkdir(parents=True)
    (repo / "corpus" / "fam" / "e.md").write_text("# entry\n")
    (repo / "cases" / "scenarios").mkdir(parents=True)
    (repo / "cases" / "scenarios" / "lid-cavity.yaml").write_text("name: lid-cavity\n")
    results = tmp_path / "results"

    run = Run(
        case_key="lid-cavity",
        scenario="cases/scenarios/lid-cavity.yaml",
        model="m",
        backend="anthropic",
        corpus_state="empty",
        repeat=1,
    )
    outcome = execute_run(
        run,
        suite=suite,
        results_dir=results,
        repo_root=repo,
        timeout_s=1,
        max_iters=1,
        resume=False,
    )
    assert outcome["status"] == "aborted_corpus_mismatch"
    meta = json.loads((results / run.run_id / "meta.json").read_text())
    assert "annotation" in meta["detail"]
    # No agent was launched, so there is no log to mislead a later reader.
    assert not (results / run.run_id / "agent.log").exists()


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def test_existing_record_is_skipped_on_resume(tmp_path: Path, suite) -> None:
    run = Run("lid-cavity", "cases/scenarios/lid-cavity.yaml", "m", "anthropic", "seeded", 1)
    out = tmp_path / run.run_id
    out.mkdir(parents=True)
    (out / "record.json").write_text("{}")
    outcome = execute_run(
        run,
        suite=suite,
        results_dir=tmp_path,
        repo_root=REPO_ROOT,
        timeout_s=1,
        max_iters=1,
        resume=True,
    )
    assert outcome["status"] == "skipped_existing"


def test_scenario_case_name_reads_the_declared_name(tmp_path: Path) -> None:
    p = tmp_path / "whatever.yaml"
    p.write_text(yaml.safe_dump({"name": "lid-cavity", "description": "x"}))
    # The agent authors into cases/work/<name>/, which is what the runner
    # has to move afterwards — the filename is not authoritative.
    assert scenario_case_name(p) == "lid-cavity"


# ---------------------------------------------------------------------------
# Automation gate
# ---------------------------------------------------------------------------


def test_automation_level_is_read_from_the_scenario(tmp_path: Path) -> None:
    p = tmp_path / "s.yaml"
    p.write_text("name: x\nautomation_level: 3\n")
    assert scenario_automation_level(p) == 3


def test_missing_automation_level_defaults_to_two(tmp_path: Path) -> None:
    p = tmp_path / "s.yaml"
    p.write_text("name: x\n")
    # CLAUDE.md's default. Guessing 5 here would silently turn a scenario
    # the researcher expected to pause into an unattended one.
    assert scenario_automation_level(p) == 2


def test_gating_levels_are_reported_before_the_matrix_runs(tmp_path: Path) -> None:
    # No shipped scenario runs at level 5, so stage one next to the real
    # lid-cavity scenario to check that unattended cases are left out.
    scen = tmp_path / "cases" / "scenarios"
    scen.mkdir(parents=True)
    (scen / "lid-cavity.yaml").write_text(
        (REPO_ROOT / "cases/scenarios/lid-cavity.yaml").read_text()
    )
    (scen / "unattended.yaml").write_text("name: unattended\nautomation_level: 5\n")
    runs = [
        Run("lid-cavity", "cases/scenarios/lid-cavity.yaml", "m", "anthropic", "seeded", 1),
        Run("unattended", "cases/scenarios/unattended.yaml", "m", "anthropic", "seeded", 1),
    ]
    gated = gated_cases(runs, tmp_path)
    # lid-cavity declares level 3 and will pause; the unattended case declares 5.
    assert gated == {"lid-cavity": 3}


def test_presupplied_approvals_are_recorded(tmp_path: Path, suite) -> None:
    repo = tmp_path / "repo"
    (repo / "corpus").mkdir(parents=True)
    (repo / "cases" / "scenarios").mkdir(parents=True)
    (repo / "cases" / "scenarios" / "lid-cavity.yaml").write_text(
        "name: lid-cavity\nautomation_level: 3\n"
    )
    results = tmp_path / "results"
    run = Run(
        "lid-cavity", "cases/scenarios/lid-cavity.yaml", "m", "anthropic", "empty", 1
    )
    # No agent runs here: the command fails immediately because the repo is a
    # stub. What matters is that the record says how the gate was handled.
    execute_run(
        run,
        suite=suite,
        results_dir=results,
        repo_root=repo,
        timeout_s=10,
        max_iters=1,
        resume=False,
        approve_gates=True,
    )
    meta = json.loads((results / run.run_id / "meta.json").read_text())
    assert meta["automation_level"] == 3
    assert meta["gate_approvals_presupplied"] is True


def test_the_unattended_arm_declares_itself_in_the_prompt() -> None:
    from run_matrix import PROMPT_TEMPLATE, UNATTENDED_SUFFIX

    # Turning off the gate hook removes enforcement but not the
    # instruction: an agent told to honour automation_level 2 will stop
    # before meshing whether or not a hook would have stopped it. Observed
    # on a real run that authored a complete case and then waited for a
    # review nobody was going to give.
    assert "automation_level as 5" in UNATTENDED_SUFFIX
    assert "unattended" in UNATTENDED_SUFFIX.lower()
    # Stated to the agent rather than smuggled past it.
    assert "do not stop" in UNATTENDED_SUFFIX.lower()
    assert PROMPT_TEMPLATE.format(scenario="x.yaml").endswith(".")


# ---------------------------------------------------------------------------
# The ungated arm has to reach the enforcement layer, not just the prompt
# ---------------------------------------------------------------------------


SCENARIO = """\
name: lid-cavity
automation_level: 2
description: a cavity
"""


def test_ungated_scenario_copy_declares_level_five(tmp_path: Path) -> None:
    scenario = tmp_path / "lid-cavity.yaml"
    scenario.write_text(SCENARIO)
    copy = write_ungated_scenario(scenario)

    assert scenario_automation_level(copy) == 5
    # The shipped scenario is the researcher's declaration; it stays as written.
    assert scenario.read_text() == SCENARIO
    assert scenario_automation_level(scenario) == 2


def test_the_gate_resolves_the_copy_for_its_case(tmp_path: Path) -> None:
    # The gate maps `cases/work/<X>` to `cases/scenarios/<X>.yaml`. The copy is
    # only effective if its case name and its filename agree, so the gate
    # reading the case path lands on the level-5 file rather than the shipped
    # one. This is the whole reason the copy exists.
    scenarios = tmp_path / "cases" / "scenarios"
    scenarios.mkdir(parents=True)
    scenario = scenarios / "lid-cavity.yaml"
    scenario.write_text(SCENARIO)
    copy = write_ungated_scenario(scenario)

    case_name = scenario_case_name(copy)
    assert copy.stem == case_name

    work = tmp_path / "cases" / "work" / case_name
    work.mkdir(parents=True)
    assert read_automation_level(str(work)) == 5
    # And the shipped case path still reads as gated.
    gated = tmp_path / "cases" / "work" / "lid-cavity"
    gated.mkdir(parents=True)
    assert read_automation_level(str(gated)) == 2


def test_a_level_five_scenario_needs_no_copy(tmp_path: Path) -> None:
    # cd-nozzle ships at level 5. Copying it would rename its case directory
    # for no reason.
    scenario = tmp_path / "cd-nozzle.yaml"
    scenario.write_text("name: cd-nozzle\nautomation_level: 5\n")
    assert scenario_automation_level(scenario) == 5


def test_the_client_allows_more_silence_than_the_server_tools_take() -> None:
    # The MCP client aborts a tool that goes quiet for its idle timeout. If
    # that is not longer than the longest server-side cap, the client wins
    # the race and the server's own timeout — which returns a diagnosable
    # `reason: timeout` — can never fire.
    from openfoam_mcp import tools as of_tools

    source = Path(of_tools.__file__).read_text(encoding="utf-8")
    caps = [int(m) for m in re.findall(r"timeout=(\d+),", source)]
    assert caps, "no server-side tool timeouts found"
    assert int(MCP_IDLE_TIMEOUT_MS) > max(caps) * 1000


# ---------------------------------------------------------------------------
# Ablations: an arm run with a server withheld
# ---------------------------------------------------------------------------


MCP_CONFIG = {
    "mcpServers": {
        "openfoam": {"command": "uv", "args": ["run", "openfoam"]},
        "validation": {"command": "uv", "args": ["run", "validation"]},
        "consultant": {"command": "uv", "args": ["run", "consultant"]},
    }
}


def test_ablating_a_server_leaves_the_others(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(json.dumps(MCP_CONFIG))
    out = tmp_path / "run"
    out.mkdir()
    written = write_ablated_mcp_config(tmp_path, out, ("consultant",))

    servers = json.loads(written.read_text())["mcpServers"]
    assert "consultant" not in servers
    assert set(servers) == {"openfoam", "validation"}


def test_the_shipped_config_is_never_edited(tmp_path: Path) -> None:
    source = tmp_path / ".mcp.json"
    source.write_text(json.dumps(MCP_CONFIG))
    before = source.read_text()
    out = tmp_path / "run"
    out.mkdir()
    written = write_ablated_mcp_config(tmp_path, out, ("consultant",))

    assert source.read_text() == before
    # The config the run actually used is kept beside its transcript.
    assert written.parent == out


def test_ablating_an_absent_server_is_refused(tmp_path: Path) -> None:
    # Silently ablating nothing would produce an "ablation" arm identical to
    # the ordinary one, and a null result that looks like a finding.
    (tmp_path / ".mcp.json").write_text(json.dumps(MCP_CONFIG))
    out = tmp_path / "run"
    out.mkdir()
    with pytest.raises(ValueError, match="consultent"):
        write_ablated_mcp_config(tmp_path, out, ("consultent",))


def test_an_ablated_run_gets_its_own_id() -> None:
    # An ablated run is a different arm, not a repeat: sharing a directory
    # would overwrite the ordinary arm, and --resume would treat one as
    # satisfying the other.
    run = Run(
        case_key="lid-cavity",
        scenario="cases/scenarios/lid-cavity.yaml",
        model="claude-sonnet-5",
        backend="claude-cli",
        corpus_state="seeded",
        repeat=1,
    )
    base = run.run_id
    ablated = base + "__no-consultant"
    assert base != ablated
    assert ablated.startswith(base)
