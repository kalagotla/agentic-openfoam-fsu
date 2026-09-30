# Evaluation harness

Implements [`docs/evaluation-plan.md`](../../docs/evaluation-plan.md).
Nothing here drives OpenFOAM or an LLM directly — it *runs* the agent via
`scripts/run_agent.py` and *scores* the artefacts a run leaves behind.

| Module | Job |
|---|---|
| `report_parse.py` | Full-fidelity `REPORT.md` parser — entries, consultant fields, citations, retry chains, tables, verdict banner, decisions index |
| `metrics.py` | Per-run metric functions: citation resolution, decision coverage, field completeness, gaps, origin tags, retries, HITL, phases, verdict |
| `score_report.py` | Case directory → one structured record. Delegates verdicts to the tools that own them |
| `suite.yaml` / `suite.py` | The benchmark manifest and its loader, with honesty checks |
| `run_matrix.py` | Expands the suite into runs, drives them, scores them |
| `foam_dict.py` | OpenFOAM dictionary reader, pure Python — no sourced environment needed to score a run |
| `narration_audit.py` | Does `REPORT.md` describe the case that actually ran? Recall, precision, contradiction rate |
| `faults/injectors.py` | The fault corpus: mesh, residual, and wall-treatment probes with known ground truth |
| `probe_runner.py` / `reasoning_probe.py` | The two detection arms — the tools, and a model at any OpenAI-compatible endpoint |
| `stats.py` / `aggregate.py` | Wilson intervals, Beta posteriors, cluster adjustment, McNemar, Holm; records to tables |
| `tests/` | Golden + round-trip tests. The scorer's numbers are only as good as these |

## Running an audit

```bash
# One run scored
uv run python scripts/eval/score_report.py <case> --suite scripts/eval/suite.yaml --case-key lid-cavity

# Narration vs artefact (needs $FOAM_TUTORIALS for the recall half)
uv run python scripts/eval/narration_audit.py <case> --template incompressible/icoFoam/cavity/cavity

# A matrix
uv run python scripts/eval/run_matrix.py --tier 1 --dry-run
```

## Source OpenFOAM before scoring

The recall half of the narration audit diffs the case against the tutorial
it was templated on, so it needs `$FOAM_TUTORIALS`. `run_matrix.py` scores
each run as it finishes, in whatever environment it was launched from — so
a matrix started without OpenFOAM sourced produces records whose
`narration.recall` is `None` with `recall_unavailable` saying why. Nothing
is lost: re-run `score_report.py` over the finished run directories with
the environment sourced and the recall numbers fill in.

```bash
source /usr/lib/openfoam/openfoam2412/etc/bashrc   # or: of2412
uv run python scripts/eval/score_report.py <results>/<run>/case \
    --suite scripts/eval/suite.yaml --case-key <key> \
    --run-meta <merged meta + run_summary> -o <results>/<run>/record.json
```

## On measuring honesty honestly

Both the citation resolver and the narration auditor were wrong the first
time they met a real run — and wrong in the same direction, calling honest
narration dishonest. The citation matcher scored `Ghia & Shin (1982)` as
unresolved because the manifest keys it `ghia_1982`. The narration auditor
called a report a liar five ways: `\bslip\b` fired inside "no-slip", a
tutorial path was read as a claim about the solver, a rejected alternative
was read as an adopted one, "second-order upwind" was read as the scheme
name `upwind`, and a grid-convergence sequence was read as three wrong
mesh claims.

Every one of those is pinned by a test now, because a metric that calls
honest work dishonest is worse than no metric. It would push an agent
toward narrating less, which is the opposite of what this repo is for. The
same instinct runs through the rest: unresolved and unmeasured are
reported as `None` rather than `False`, declared absences are held out of
the citation denominator, and template settings a case never copied are
held out of the recall denominator.

## Why the parser is tested against the emitter

`tests/test_report_parse.py` drives the real `record_step` /
`finalize_report` and parses what they emit, so the parser cannot drift
from the format without a test going red. It *also* parses a frozen
fixture (`tests/fixtures/report_golden.md`), so a parser regression is
caught even if emitter and parser change in lockstep.

That mirrors the repo's own trust rule: the verdict belongs to tested
code. An evaluation whose measuring instrument is untested would inherit
exactly the flaw it exists to detect.

## Running

```bash
uv run pytest scripts/eval/tests -q
```
