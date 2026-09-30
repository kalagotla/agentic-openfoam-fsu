# Evaluation results

What `docs/evaluation-plan.md` proposed, measured. This is the Phase 0–4
half of that plan: the harness exists and is tested, the fault corpus and
both detection arms run, and a first matrix of full runs has been scored.
Phases 5–9 — the novelty ladder, ablations, external baselines, the
longitudinal study, and human review — have not started.

What governs how much weight anything below can carry: two of eight cases
have four seeds under one model and two under a second; the other six have
a single run each. Every rate is reported with an interval that is wide
because it should be, and clustered by case where repeats exist.

Regenerate everything in this document with:

```bash
source /usr/lib/openfoam/openfoam2412/etc/bashrc   # recall needs $FOAM_TUTORIALS
uv run python scripts/eval/aggregate.py \
    --probes scripts/eval/results/probes --runs scripts/eval/results
```

## What was measured

| Arm | N | What it is |
|---|---|---|
| Unattended runs | 18 runs over 8 cases; 2 models, 4 seeds on two cases | Full author → mesh → solve → validate, level-5 override |
| Gated runs | 4 cases, `automation_level` 2 | The same cases under the automation gate |
| Ablation | 4 runs, 2 cases | The same cases with the consultant server withheld |
| Detection probes | 38 probes × 10 arms | Seeded faults judged by the consultant tools and by nine models |

The corpus held three annotations for every run (`corpus_state: seeded`),
so nothing here speaks to the empty-corpus arm the transfer experiment
needs. Runs were billed to a subscription; the dollar figures are what the
same tokens would have cost through the API, not what was spent.

## Half A — capability

| Case | Model | Reached | Validated | Mesh | Conv. | Coverage | Cites | Narr. prec. | Contra. | Narr. recall | Turns | Cost eq. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `cd-nozzle` | sonnet-5 | solved | — | no | yes | 1.00 | 0.53 | 0.94 | 0.06 | 0.79 | 227 | $11.00 |
| `channel-retau180` | sonnet-5 | validated | no | no | no | 0.91 | 0.85 | 1.00 | 0.00 | 0.77 | 160 | $6.32 |
| `flat-plate` | sonnet-5 | validated | no | yes | yes | 1.00 | 0.53 | 1.00 | 0.00 | 0.66 | 122 | $4.34 |
| `lid-cavity` | opus-5 | validated | yes | yes | no | 1.00 | 0.96 | 1.00 | 0.00 | 1.00 | 86 | $6.77 |
| `lid-cavity` | opus-5 | validated | yes | yes | no | 1.00 | 0.89 | 1.00 | 0.00 | 0.85 | 72 | $5.15 |
| `lid-cavity` | sonnet-5 | validated | yes | yes | no | 1.00 | 1.00 | 1.00 | 0.00 | 0.83 | 78 | $2.03 |
| `lid-cavity` | sonnet-5 | validated | yes | yes | no | 1.00 | 1.00 | 1.00 | 0.00 | 0.88 | 68 | $1.73 |
| `lid-cavity` | sonnet-5 | validated | yes | yes | no | 1.00 | 1.00 | 1.00 | 0.00 | 0.83 | 62 | $1.36 |
| `lid-cavity` | sonnet-5 | validated | yes | yes | yes | 1.00 | 0.93 | 1.00 | 0.00 | 0.92 | 69 | $1.74 |
| `lid-cavity-re1000` | sonnet-5 | validated | yes | yes | yes | 1.00 | 0.94 | 1.00 | 0.00 | 0.67 | 64 | $1.59 |
| `naca-0012` | sonnet-5 | solved | — | yes | no | 0.92 | — | 1.00 | 0.00 | 0.76 | — | — |
| `pitz-daily` | opus-5 | validated | yes | yes | yes | 1.00 | 0.53 | 1.00 | 0.00 | 0.90 | 98 | $9.65 |
| `pitz-daily` | opus-5 | validated | yes | yes | yes | 1.00 | 0.88 | 1.00 | 0.00 | 0.65 | 211 | $28.58 |
| `pitz-daily` | sonnet-5 | validated | no | yes | no | 1.00 | 0.77 | 1.00 | 0.00 | 0.40 | 57 | $1.49 |
| `pitz-daily` | sonnet-5 | solved | — | yes | no | 1.00 | 1.00 | 1.00 | 0.00 | 0.58 | 100 | $3.88 |
| `pitz-daily` | sonnet-5 | validated | yes | yes | no | 1.00 | 0.87 | 1.00 | 0.00 | 0.71 | 86 | $2.69 |
| `pitz-daily` | sonnet-5 | solved | — | yes | no | 1.00 | 0.91 | 1.00 | 0.00 | 0.92 | 138 | $4.89 |
| `taylor-green` | sonnet-5 | validated | yes | yes | no | 0.90 | 1.00 | 1.00 | 0.00 | 0.81 | 93 | $3.11 |

`lid-cavity` and `pitz-daily` carry four sonnet seeds and two opus seeds
each; the other six cases have one run. `naca-0012` has no turn or cost figure because it ran to the
two-hour matrix timeout, cutting the stream before the summary that carries
them. An earlier attempt at that case, aborted by the harness defects below,
is kept unscored at `results/superseded/naca-0012__timeout-abort` — a run
the harness cut short is not a capability measurement.

Fourteen of eighteen runs reached a validation verdict. Rates are over runs that
reached the phase in question, so a run that stopped at meshing is not
counted as a validation failure. The clustered figure is the one to read:
four seeds of one case are four observations of that case, not four points
on the benchmark.

- **mesh_pass** 0.889 [0.67, 0.97], n = 18 — clustered 0.91 [0.62, 0.98], eff n = 11
- **converged** 0.333 [0.16, 0.56], n = 18 — clustered 0.31 [0.14, 0.56], eff n = 16
- **validated** 0.786 [0.52, 0.92], n = 14 — clustered 0.80 [0.49, 0.94], eff n = 10

Median cost equivalent $3.88, median 86 turns.

**H1 is not answered.** Parity is a claim about this tool against a
published competitor at comparable cost, and nothing here has been run
against Foam-Agent or any other system. The intervals also still span most
of the unit range — `validated` clustered at 0.75 with a [0.41, 0.93] bound
distinguishes almost nothing, and six of the eight cases rest on a single
run each. What the table does support is narrower and still worth stating:
the pipeline runs end to end on cases spanning laminar cavity flow, a
turbulent boundary layer, a periodic DNS box, a low-Re channel, and a
shock-carrying nozzle, and the failures it does have are legible.

The two runs that fell short are legible in exactly that way:

- **`cd-nozzle`** solved, validated, and self-reported PASS, but wrote no
  `metrics.json`, so the record scores its validation as unmeasured rather
  than trusting the banner. See *The trust hinge* below.
- **`naca-0012`** spent two hours and never reached validation. It is the
  most expensive case in the suite and the only one that exercises the
  retry loop hard: snappyHexMesh castellated and snapped cleanly but
  extruded almost no boundary layer, and four recorded repairs — medial-axis
  relaxation, an `includedAngle` fix, a `featureAngle` relaxation that made
  coverage worse and was reverted — left it accepting a mesh at roughly 9%
  layer coverage with the shortfall narrated. checkMesh then passed on core
  quality (max non-orthogonality 41.7, max skewness 0.59). simpleFoam
  diverged on a floating-point exception; the agent traced it to an erased
  outlet boundary condition, fixed it, converged — and then recorded that
  the converged answer was still physically wrong (Cd = 0.099, seven to
  nine times high; Cl = -0.018, wrong sign) and was diagnosing that when
  the clock ran out. Seven retries, two recorded failures, one left
  unresolved, and no false claim anywhere in the narration.

  That last part is the result worth keeping. The run was wrong about the
  aerodynamics and right about itself: it reported a mesh it was unhappy
  with, a solver that diverged, and a converged solution it did not
  believe. On the axis this repo optimises, an honest failure is the
  intended outcome — and it never reported a PASS it had not earned.

Two runs converged on `channel-retau180` and `flat-plate` and still failed
validation. Both are real physics results rather than setup defects: the
channel run diagnosed a low-Re k-epsilon model collapsing to a spurious
laminar state, and the flat-plate run missed the log-law on a
reference-applicability limit while passing Cf. Neither was retried, which
is the plan's rule at levels 1–4.

### The second model buys reproducibility, not capability

Two seeds of each cheap case under `claude-opus-5`, against four under
`claude-sonnet-5`.

| | `lid-cavity` | | `pitz-daily` | |
|---|---|---|---|---|
| | sonnet-5 (n=4) | opus-5 (n=2) | sonnet-5 (n=4) | opus-5 (n=2) |
| Verdicts | PASS ×4 | PASS ×2 | FAIL, PASS, PASS, REVIEW | PASS ×2 |
| Validated through the tested path | 4/4 | 2/2 | 1/4 | 2/2 |
| Left a `metrics.json` | 4/4 | 2/2 | 2/4 | 2/2 |
| Median cost equivalent | $1.74 | $5.96 | $3.28 | $19.11 |
| Median turns | 68 | 79 | 93 | 154 |

On `lid-cavity`, which the cheaper model already does every time, the
larger one changes nothing and costs 3.4× as much. On `pitz-daily`, the
case whose four sonnet seeds produced three different verdicts, both opus
runs passed, both validated through the tested path, and both left a
metrics file — at 5.8× the cost and 1.7× the turns.

**Two runs agreeing is weak evidence.** If the true pass rate were the 1
in 4 sonnet showed, two agreeing runs would still happen about one time in
sixteen; nothing here is significant at any conventional level. What can be
said is that the direction is consistent across three separate measures —
verdict, validation through the tested path, and whether a machine-checkable
metrics file exists at all — and that the extra reliability, if real, is
bought at roughly six times the cost on the case that needs it.

That also sharpens the cost picture. The median across the whole matrix is
$3.88, but the range now spans $1.36 to $28.58, and the expensive end is
not the hard physics — it is the easy case that the model kept re-authoring.

### Seed variance, on the two cases that have it

Four seeds each of the two cheapest cases. The result is not the one the
novelty ladder predicts.

| | `lid-cavity` (N1) | `pitz-daily` (N0) |
|---|---|---|
| Verdicts | PASS, PASS, PASS, PASS | FAIL, PASS, PASS, REVIEW |
| Validated through the tested path | 4 of 4 | 2 of 4 |
| Retries | 0, 0, 0, 1 | 0, 3, 2, 5 |
| Turns | 62–78 (median 68) | 57–138 (median 93) |
| Cost equivalent | $1.36–$2.03 (1.5×) | $1.49–$4.89 (3.3×) |

`lid-cavity` is reproducible: every seed picked a 128×128 grid, passed both
Ghia centreline profiles inside the 5% band, and left a conforming metrics
file. `pitz-daily` is not: four seeds produced three different verdicts, two
of them left no `metrics.json` at all, and the most expensive run cost 3.3
times the cheapest.

**The unstable case is the one on the *lower* novelty rung.** N0 means a
tutorial exists with the same physics and geometry, which is supposed to be
the easiest thing the suite asks for. What separates the two is not distance
from the tutorial library but how tightly the acceptance criterion pins the
setup. Ghia gives `lid-cavity` two named profiles at fixed stations on a
fixed geometry, and there is essentially one case that answers it. The
`pitz-daily` scenario asks for a reattachment length against Armaly, which
every seed pursued by authoring a *different* domain — the first extended
the downstream section, another kept the tutorial contraction — and
reattachment is exquisitely sensitive to that choice.

So novelty level does not predict reproducibility, and a single run of a
case says little about the case. That is an argument for the plan's five
seeds, and also a warning about reading the one-seed rows in the table
above: six of the eight cases have exactly the evidence `pitz-daily` had
before this section existed.

## Half B(a) — groundedness

| Case | Citations | Resolved | Strong | Gapped decisions | Uncited-claim flags |
|---|---|---|---|---|---|
| `cd-nozzle` | 17 | 0.53 | 0.00 | 0.00 | 0 |
| `channel-retau180` | 13 | 0.85 | 0.69 | 0.07 | 0 |
| `flat-plate` | 15 | 0.53 | 0.47 | 0.00 | 0 |
| `lid-cavity` | 20 | 1.00 | 0.65 | 0.00 | 0 |
| `lid-cavity-re1000` | 18 | 0.94 | 0.72 | 0.00 | 0 |
| `naca-0012` | 0 | — | — | 0.00 | 0 |
| `pitz-daily` | 13 | 0.77 | 0.00 | 0.20 | 0 |
| `taylor-green` | 2 | 1.00 | 1.00 | 0.00 | 1 |

*Resolved* means the citation matched an entry in `corpus/references/` or a
corpus annotation. *Strong* means it matched by identifier or author-year
rather than by text. A decision is *gapped* when it left a consultant field
empty, which the schema renders as visible weakness rather than filling it.

Citation resolution ranges from 0.53 to 1.00. The low end is not
fabrication — `cd-nozzle` and `flat-plate` cite tutorial paths and OpenFOAM
source constants that resolve to no manifest entry, which is the corpus
hole the metric exists to expose. Gapped-decision rates are near zero
throughout, and `flag_uncited_claims` came back clean on seven of the eight
runs. `naca-0012` cites nothing at all: it spent its budget on meshing and
solver repair and never reached the decisions that carry citations.

The clearest evidence that the citation layer is load-bearing rather than
decorative comes from `lid-cavity`. Its verdict banner reads "v floored by
the reference typo, not the grid," and the reasoning cites the Ghia
dataset's own provenance note. That note is real:
`cases/lid-cavity/reference/README.md` documents a suspected typo at
`x = 0.9063` in the Re = 400 v-centerline, shipped as-printed because no
published source can adjudicate it. The run read the reference's
provenance, attributed an outlier to it, and did not quietly smooth the
data — the behaviour the reference README asks for.

## Half B(b) — narration fidelity

**One contradiction in 218 checkable claims, across all twenty-two scored
runs.** It is `cd-nozzle` writing "240x2x1 (960 cells)" for a mesh that has
480, and it is a real arithmetic slip in the final mesh entry.

Getting to that number required fixing the auditor nine times, in every
case because it called honest narration dishonest — the failure mode this
repo cares most about, since it would push an agent toward narrating less.
Those fixes are listed under *What the evaluation found in itself*.

Narration recall — the share of settings the case changed relative to its
template that the report explains — runs 0.40 to 0.83. The denominator
deserves a caveat: `suite.yaml` names a template for three of nineteen
cases, so five of the eight runs are scored against the template their own
report declares rather than a preregistered one. That is a weaker
denominator — the run chose it — and each record carries
`template_source` saying which it was.

Extractor coverage — the share of decisions producing any checkable claim
— runs 0.43 to 1.00. Qualitative rationale escapes the extractor entirely,
so the precision denominator is a subset of what the reports assert, and
the number above is a claim about concrete, resolvable assertions only.

## H3 — detection

| Arm | Recall | False alarms | Youden J | Localisation | Answered |
|---|---|---|---|---|---|
| `tool` | 1.000 [0.80, 1.00] n=15 | 0.091 [0.02, 0.38] n=11 | 0.9091 | 1.000 [0.80, 1.00] n=15 | 26/26 |
| `qwen3-30b-a3b` | 0.750 [0.41, 0.93] n=8 (clustered: 0.75 [0.30, 0.95], eff n=4) | 0.000 [0.00, 0.43] n=5 | 0.75 | 0.250 [0.07, 0.59] n=8 | 13/17 |
| `qwen3-30b` | 0.750 [0.41, 0.93] n=8 (clustered: 0.75 [0.30, 0.95], eff n=4) | 0.000 [0.00, 0.43] n=5 | 0.75 | 0.250 [0.07, 0.59] n=8 | 13/17 |
| `nemotron3-33b` | 0.600 [0.31, 0.83] n=10 | 0.000 [0.00, 0.35] n=7 | 0.6 | 0.200 [0.06, 0.51] n=10 | 17/17 |
| `qwen2.5-coder-32b` | 0.600 [0.31, 0.83] n=10 | 0.000 [0.00, 0.35] n=7 | 0.6 | 0.200 [0.06, 0.51] n=10 | 17/17 |
| `qwen3.6` | 0.562 [0.33, 0.77] n=16 | 0.000 [0.00, 0.26] n=11 | 0.5625 | 0.188 [0.07, 0.43] n=16 | 27/27 |
| `gpt-oss-20b` | 0.762 [0.55, 0.89] n=21 (clustered: 0.80 [0.49, 0.94], eff n=10) | 0.267 [0.11, 0.52] n=15 | 0.4952 | 0.333 [0.17, 0.55] n=21 | 36/38 |
| `qwen3-coder-30b` | 0.375 [0.18, 0.61] n=16 (clustered: 0.40 [0.17, 0.69], eff n=10) | 0.091 [0.02, 0.38] n=11 | 0.2841 | 0.188 [0.07, 0.43] n=16 | 27/27 |
| `llama3.3-70b` | 0.273 [0.13, 0.48] n=22 (clustered: 0.27 [0.10, 0.57], eff n=11) | 0.000 [0.00, 0.19] n=16 | 0.2727 | 0.091 [0.03, 0.28] n=22 | 38/38 |
| `qwen3.8-27b` | — | — | — | — | 0/17 |

The *clustered* figure, where one is shown, widens the interval to account
for probes that share a fault family: six mesh probes built from one
checkMesh log are not six independent observations, so the effective n is
smaller than the count. Where no clustered figure appears the arm's hits
were spread across families and the adjustment made no difference.

Arms differ in how much of the corpus they ran: `tool`, `gpt-oss-20b`, and
`llama3.3-70b` cover all 38 probes, two arms cover 27, and the rest cover
the 17 that existed when they were scored. The paired comparison below uses only the
probes both arms actually ran. The stale arms were not re-run because the
models had been removed from the local library by the time the corpus grew,
and one that was available took over an hour without finishing a single
pass while the case matrix held the CPU. `qwen3.8-27b` returned no usable
verdict on any probe, which is not a detection result and is reported as
absent rather than as zero recall.

| Arm | Recall Δ | Effect h | P(tool better) | Discordant | p | Holm sig. | κ |
|---|---|---|---|---|---|---|---|
| `qwen3-30b-a3b` | -0.250 | 1.05 | 0.90 | 2 | 0.5000 | no | +0.70 |
| `qwen3-30b` | -0.250 | 1.05 | 0.90 | 2 | 0.5000 | no | +0.70 |
| `gpt-oss-20b` | -0.286 | 1.13 | 0.98 | 4 | 0.1250 | no | +0.43 |
| `nemotron3-33b` | -0.333 | 1.23 | 0.96 | 3 | 0.2500 | no | +0.53 |
| `qwen2.5-coder-32b` | -0.333 | 1.23 | 0.96 | 3 | 0.2500 | no | +0.53 |
| `qwen3.6` | -0.400 | 1.37 | 1.00 | 6 | 0.0312 | no | +0.50 |
| `llama3.3-70b` | -0.600 | 1.77 | 1.00 | 9 | 0.0039 | yes | +0.32 |
| `qwen3-coder-30b` | -0.600 | 1.77 | 1.00 | 9 | 0.0039 | yes | +0.24 |

Two comparisons survive Holm correction. Everything else has a large
effect size and too few discordant pairs to reach significance — the
paired test can only see probes where the two arms disagree, and at 15
faulty probes there are two to six of them. That is a sample-size result,
not evidence of parity.

**The aggregate recall number hides the finding.** Split by fault class:

| Fault class | Detector | tool | gpt-oss-20b | llama3.3-70b |
|---|---|---|---|---|
| Mesh quality | `assess_mesh_quality` | 5/5 | 5/5 | 4/6 |
| Residual history | `assess_residuals` | 4/4 | 1/4 | 1/4 |
| Wall treatment (y+) | `assess_y_plus` | 6/6 | 4/6 | 1/6 |
| Setup contradictions | none — reasoning only | not read | 6/7 | 0/6 |
| Localisation (all faulty probes) | | 15/15 | 7/22 | 2/22 |

Four separate things are going on:

1. **Mesh quality is near parity.** A checkMesh log with a max
   non-orthogonality of 78 degrees is legible to anyone; the tool adds
   little detection there.
2. **Residual history is where the engineering earns its place.** The tool
   catches 4/4; every model catches 1/4. Classifying a convergence
   trajectory as stalled, oscillating, or one-field-stalled means reading a
   series, and the models read the last line.
3. **Wall treatment separates models from each other.** Across the arms
   that ran the class, y+ recall spans 1/6 to 6/6 — `qwen3-coder-30b` at
   1/6, `qwen3.6` at 4/6, `gpt-oss-20b` at 6/6 in one session and 4/6 in
   another. This is where judgement rather than a threshold does the work:
   y+ of 12 is wrong for a wall function, wrong for a low-Re model, and
   merely marginal for kOmegaSST, so the fault is in the pairing. It is
   also the class most exposed to the session drift described below —
   the same model's two passes differ by two probes here.
4. **Setup contradictions are the model's alone.** Eleven probes put two
   files in conflict — a steady `ddtScheme` under a transient solver, RAS
   selected with no solver for k or epsilon, an over-specified inlet with
   both p and U fixed at each end. No consultant tool reads them, so the
   tool arm reports them as not-run rather than as misses. gpt-oss-20b
   catches 6 of 7 and raises no false alarm on any of the five clean
   controls, including both hard negatives — a write interval equal to the
   end time, and a purged time history. This is the share of detection the
   model provides and the engineering does not.

   It is also where the models differ most from each other. llama3.3-70b,
   more than three times the size, catches **none** of the six. Reading two
   dictionaries against each other is not a capability that tracks parameter
   count, which is worth knowing before choosing a model to run this tool.

**Localisation is the consistent, large gap.** The tool names the offending
metric or patch on every faulty probe it reads; the best model manages 7 of
22 and the 70B model 2 of 22. Models notice that something is wrong far more often than they can say
what. For a researcher deciding what to fix, that difference matters more
than the recall column.

Variance decomposition over the probe set: fault class 34%, arm 48%,
residual 18%.

### The model arms are not reproducible across sessions

`gpt-oss:20b` answered three consecutive passes identically — 0 of 38
verdicts differing. Against a pass taken hours earlier it disagreed on 6 of
the 27 probes the two share: four clean probes newly flagged, two faults
newly missed, and one answer that arrived unparseable. Same weights digest,
same endpoint, same prompt, temperature zero.

Between the two passes the local model library changed around it — models
were removed and a much larger one added — so the runtime the 20B model was
scheduled into was not the same runtime, even though the model was. The
cause is not established here; the effect is, and it bounds what a model
row in the table above means. Determinism within a session is not
determinism across sessions, and every model arm here is one session.

The practical consequence: differences between model arms of the size seen
in the table are not safely attributable to the models. The tool arm has no
such problem — it is deterministic code reading a fixed artefact — which is
itself part of what the comparison is measuring.

### The mesh thresholds at every operating point

Recall only means something next to the false-alarm rate it was bought at,
so the mesh bands were swept — scaled together from strict to permissive —
with the curve driven through the same `assess_mesh_quality` an agent
calls rather than a re-implementation of it.

| Factor | Recall | False alarms | Youden J | Localisation |
|---|---|---|---|---|
| 0.6 | 1.000 [0.57, 1.00] | 0.750 [0.30, 0.95] | 0.250 | 1.000 |
| 0.7 | 1.000 [0.57, 1.00] | 0.500 [0.15, 0.85] | 0.500 | 1.000 |
| 0.8 | 1.000 [0.57, 1.00] | 0.250 [0.05, 0.70] | 0.750 | 1.000 |
| 0.9 | 1.000 [0.57, 1.00] | 0.250 [0.05, 0.70] | 0.750 | 1.000 |
| 1 ←ships | 1.000 [0.57, 1.00] | 0.250 [0.05, 0.70] | 0.750 | 1.000 |
| 1.1 | 1.000 [0.57, 1.00] | 0.250 [0.05, 0.70] | 0.750 | 1.000 |
| 1.25 | 0.800 [0.38, 0.96] | 0.250 [0.05, 0.70] | 0.550 | 0.400 |
| 1.5 | 0.800 [0.38, 0.96] | 0.250 [0.05, 0.70] | 0.550 | 0.400 |
| 2 | 0.600 [0.23, 0.88] | 0.250 [0.05, 0.70] | 0.350 | 0.200 |
| 3 | 0.600 [0.23, 0.88] | 0.250 [0.05, 0.70] | 0.350 | 0.200 |
| 4 | 0.600 [0.23, 0.88] | 0.000 [0.00, 0.49] | 0.600 | 0.200 |
| 6 | 0.600 [0.23, 0.88] | 0.000 [0.00, 0.49] | 0.600 | 0.200 |

Two things follow, and the second is not flattering.

**The shipped thresholds are well placed.** Factor 1.0 ties the best Youden
J on this corpus (0.750), on a plateau running from 0.8 to 1.1. Tightening
below 0.8 buys no recall and triples the false alarms; loosening past 1.1
starts dropping faults. The bands are not uniquely optimal — anything in
that window scores the same — but they are not arbitrary either.

**On mesh faults the tool does not beat a 20B local model.** Restricted to
the nine mesh probes, gpt-oss-20b scores 5/5 recall with *zero* false
alarms. The tool scores 5/5 with one. And the curve shows the tool cannot
buy that quiet at any threshold: at a false-alarm budget of 0% its recall
falls to 0.600, because reaching zero requires factor 4, which drops three
faults on the way. Matched at the model's operating point, the model wins
this class outright.

The false alarm it cannot shed is `mesh_clean_boundary_layer` — a clean
mesh with an aspect ratio of 320, high by design because that is what a
resolved boundary layer looks like. No scalar threshold on aspect ratio
separates it from a defect, which is a statement about the metric rather
than about the tuning.

So the case for the consultant tools is narrower than the aggregate recall
column suggests, and it rests on the two things the sweep does not touch:
residual-pattern classification, where the tool is 4/4 against 1/4, and
localisation, where it names the offending metric on every faulty probe it
reads against the best model's 7 of 22. On mesh quality specifically, the
honest summary is parity at best.

### The residual classifier, swept the same way

Its cuts are not oriented alike — a smaller oscillation cut flags more, a
smaller stall cut flags less — so the knob is a *sensitivity* defined to
move every branch toward flagging at once, rather than a plain scale.

| Sensitivity | Recall | False alarms | Youden J |
|---|---|---|---|
| 0.6 | 0.750 [0.30, 0.95] | 0.000 [0.00, 0.56] | 0.750 |
| 0.7 | 1.000 [0.51, 1.00] | 0.000 [0.00, 0.56] | 1.000 |
| 1.0 ←ships | 1.000 [0.51, 1.00] | 0.000 [0.00, 0.56] | 1.000 |
| 2.0 | 1.000 [0.51, 1.00] | 0.000 [0.00, 0.56] | 1.000 |
| 6.0 | 1.000 [0.51, 1.00] | 0.000 [0.00, 0.56] | 1.000 |

**This detector has margin the mesh one does not.** Across a ten-fold
sensitivity range it never raises a false alarm on a clean residual
history, and holds 4/4 from 0.7 upward. Where the mesh detector cannot
reach zero false alarms at any threshold, this one cannot be pushed into
one. Seven probes, so the intervals are wide — but the shape is the point,
and it agrees with the per-class split: residual history is where the
engineering earns its place.

y+ stays at a fixed operating point. Its bands are per
turbulence-model-class rather than a single scale, so there is no one knob
to sweep, and the sweep reports that rather than folding it in.

Reproduce with:

```bash
uv run python scripts/eval/roc_sweep.py --workdir <scratch>          # both
uv run python scripts/eval/roc_sweep.py --workdir <scratch> \
    --detector assess_residuals
```

## The first ablation — the consultant withheld

Four runs of the two cheap cases with the consultant server absent from the
MCP config, against the ordinary sonnet runs of the same cases. Paired on
case *and* model, because the ordinary arm holds two models and this one
holds a single cheaper model.

| Case | n | Validated | Citations resolved | Decision coverage | Cost eq. |
|---|---|---|---|---|---|
| `lid-cavity` | 4 → 2 | 1.00 → 1.00 | 0.98 → 0.94 | 1.00 → 1.00 | $1.72 → $1.79 |
| `pitz-daily` | 4 → 2 | 0.50 → — | 0.89 → 0.83 | 1.00 → 0.88 | $3.24 → $1.92 |

**On `lid-cavity` the consultant makes no measurable difference.** Both
ablated runs passed, validated through the tested path, kept full decision
coverage, and cost the same. That is the expected result and worth stating
plainly: for a case whose reference pins the setup completely, the
consultant is not what makes the run succeed.

The `pitz-daily` column is where a difference might live, and it is not
established. Citation resolution drops 0.89 → 0.83 and decision coverage
1.00 → 0.88, both in the direction the design predicts — without
`get_tutorial_annotation` there are fewer resolvable citations to make —
but both are within the spread the ordinary arm already shows across its
own four seeds.

**Validation reads `—` because neither ablated run left a `metrics.json`.**
Both self-reported PASS. That looks alarming until it is put beside the
ordinary arm, where two of four seeds did the same. At 2 of 2 against 2 of
4 it is not distinguishable from the variance already there.

Across the whole matrix the gap is now **5 of 22 runs finalizing a verdict
with nothing machine-checkable behind it**. That is the clearest actionable
finding in this document, and it is a contract problem rather than an agent
one: `CLAUDE.md` step 7 requires the analysis script to *print* its result,
and only the archive section requires it to be written down.

**What this ablation does not yet test.** The consultant's detection tools
are what the probe corpus measures, and no probe runs inside a case. An
ablation that would move a number needs a case seeded with a fault the
consultant catches and the agent would otherwise miss — which is the Tier 3
corpus applied to a whole run rather than an artefact, and is not built.

## The automation gate

Four cases were run with `automation_level: 2` and no approver present.
All four authored a complete case and stopped before meshing; three of the
four surfaced an explicit `pending_review` entry saying what they were
waiting for. None proceeded.

That is the gate working, and it held even against an attempt to bypass
it: those runs were launched with a settings file that had the hooks block
stripped out. Project settings load alongside `--settings`, so the hook was
never actually disabled — and the agent stopped anyway, because
`CLAUDE.md` tells it to honour the declared level in its own behaviour.

`hitl_compliance` as the plan defines it is still unmeasured. These runs
show the gate stops work; they do not measure whether an agent complies
with a level when an approver *is* present, which needs an interactive arm.

## The trust hinge

The plan's first mechanism is that the pass/fail number belongs to tested
code. Across eight runs the machinery held — but the artefact it produces
is not always left behind:

- Seventeen of twenty-two runs wrote a `postProcessing/analysis/metrics.json`
  — mostly in the `checks` shape the scorer expects, one (`taylor-green`) in
  a `checks_by_name` variant it also accepts. The file has no enforced
  schema, so the scorer tolerates both rather than rejecting a valid run
  over its layout.
- **Five runs wrote plots but no `metrics.json`** — `cd-nozzle`, two
  `pitz-daily` seeds, and both ablated `pitz-daily` runs. Taking `cd-nozzle`
  as the example, its `validate.py`
  prints `<<<ANALYSIS_RESULT>>>` and the JSON, which is all `CLAUDE.md`
  step 7 literally requires, and nothing persists it. The run finalized
  PASS; the record scores its validation as unmeasured, because a banner is
  the agent's word and the metrics file is the evidence.
- `naca-0012` never reached analysis.

The scorer behaves correctly here — it reports `None` rather than crediting
the self-reported verdict. The gap is in the contract: `CLAUDE.md` requires
`metrics.json` only in the archive-replay section, so a run that never
archives can pass without leaving a machine-checkable verdict. Making step
7 require the file would close it.

With four seeds this is now a rate rather than an anecdote: **three of
fourteen runs finalized a verdict without leaving a `metrics.json`** — one
`cd-nozzle` and two `pitz-daily`. All three self-reported PASS or REVIEW,
and none of the three can be checked. The scorer records them as unmeasured,
which is right, but the contract is what allows it: `CLAUDE.md` step 7
requires the script to *print* its result, and only the archive section
requires it to be written down.

## What the evaluation found in itself

Every one of these was found by running the harness against real runs, and
each is fixed with a test.

**The auditor called honest narration dishonest, five ways.**

1. A *family folder* was accepted as a template. `suite.yaml` named
   `incompressible/icoFoam/cavity`, which contains cases rather than being
   one, so no template settings were read and every setting in the case
   counted as an unnarrated addition. Cavity recall read 0.58 where it is
   0.73.
2. *Superseded mesh steps* were checked against the final case.
   `cd-nozzle` narrated four meshes and why it moved between them, and the
   three it abandoned scored as eleven false claims — 0.61 precision for
   the most thorough mesh narration in the matrix.
3. *Physics described in prose* was read as configuration. "The bulk of the
   channel is running effectively laminar, not turbulent" — a diagnosis of
   a failed run — was scored as a false claim that the case declares
   `simulationType laminar`.
4. *A value quoted from the template* was read as a claim about the case.
   "That template uses the identical topology, just at its own domain scale
   (scale 0.333)" contradicted a case that scales by 1.
5. *Negations and departures* were read as assertions. "(no symmetryPlane
   cut)" and "swapped from icoFoam" both scored as claims that the case
   used the thing being ruled out.

**The auditor also missed real errors.** The cell-count pattern required
two digits per dimension, so `240x2x1` — a quasi-1-D duct mesh — was
invisible, and a narration's own stated total was never checked against its
own dimensions. Both are now checked, and together they are what caught the
one genuine contradiction in the matrix.

**The detection arm was showing the model half the evidence.** A y+ fault
lives in the pairing of the turbulence model with the wall data, and the
reasoning probe sent only the primary artefact. gpt-oss-20b scored 0/6 on
the class and its overall recall read 0.44. Shown every file the tool
reads, the same model catches all six and scores 0.81. Left unfixed, this
would have produced a large, entirely fabricated tool advantage — the exact
result the evaluation is meant to establish.

**The ungated arm never reached the gate.** It stripped the hooks block
from a `--settings` file, but project settings load alongside it, so the
hook stayed live and denied `run_blockmesh`; the record claimed
`gate_hook_disabled: true` regardless. Ungated runs are now driven from a
level-5 copy of the scenario placed where the gate looks, and the record
says which file the level came from.

**The client timeout pre-empted the server's.** Claude Code aborts an MCP
tool silent for 1800 s and `run_snappy_hex_mesh` caps snappy at 1800 s, so
the client always won and the server's diagnosable timeout could never
fire. The child environment now allows 45 minutes of silence, with a test
asserting the ordering against the actual server-side caps. Verified by
re-running the case: snappy completed, and the run went on to mesh
quality, three solver attempts, and a physics diagnosis.

**Deferred work is lost in headless mode.** Told its mesh had been aborted,
the agent said it would check back in ten minutes and stopped. The run
prompt now states that there is no later turn; the re-run deferred
nothing.

**Recall was silently unmeasured.** `run_matrix.py` scores each run in
whatever environment it was launched from, and without `$FOAM_TUTORIALS`
the recall half reports `None`. Documented, with the re-scoring command.

**Two REPORT.md parsers exist** — one in the eval scorer, one inside
`draft_annotation_from_report` — and nothing checked that they agree. They
do, on the golden fixture, and a test now says so.

## Field rendering was not exercised

Step 8 of the workflow — render a field with `export_field_image` for a
visual sanity check — did not run anywhere in this matrix. Two runs
(`pitz-daily`, `cd-nozzle`) recorded it as a warning after `pvbatch` timed
out, and the two OpenFOAM-sourced tests that exercise it fail the same way,
so it is reproducible rather than a per-run fluke. On this machine
`pvbatch --version` does not return, which puts the cause outside the repo:
ParaView is installed and hangs.

The consequence for the results above is narrow but real. Every verdict
here rests on the sampled-profile comparison and the matplotlib overlays
the analysis scripts draw themselves; none of it was cross-checked against
a rendered field, so a solution that is wrong in a way the sampled lines
do not cross would not have been seen. Restoring rendering is a
prerequisite for taking a passing run as visually confirmed.

The rest of the suite is green: 703 tests pass with OpenFOAM sourced and
those two rendering tests deselected. Without OpenFOAM, 693 pass and 12
environment-dependent tests skip with a stated reason rather than passing
vacuously.

## What is still open

**Compute budget.** `naca-0012` exhausted a two-hour per-run timeout
without validating, and it is the only N2 external-aero case in the suite.
Either the budget rises for `compute_weight: medium` and above, or the
case is scored on a coarser target than Cl/Cd — as it stands, the N2 rung
has one case and no verdict from it.

**Statistical power.** One model. Two of eight cases have four seeds; the
plan asks for 7 cases × 2 frontier models × 5 seeds for H1. No second model
has been run at all, which is the larger gap — the seed work above shows
within-case variance is real and case-dependent, and nothing here bounds
between-model variance.

**Detection scale.** 38 probes against the plan's ~400. All four classes in
the taxonomy now have probes — mesh, numerics, physics (wall treatment), and
setup — but the mesh curve rests on nine probes and the residual curve on
seven, so every interval on both spans more than half the unit range. They
establish the shape and the matched-rate comparison, not the numbers. y+
is still judged at a fixed point: its bands are per turbulence-model-class
rather than one scale, so it has no single knob to sweep and cannot yet be
matched to a model's false-alarm rate.

**Suite coverage.** Four suite entries (`onera-m6-transonic`,
`cylinder-re100`, `heated-cavity`, `custom-inlet-bc`) have no scenario YAML.
`poiseuille` now has one, along with an analytic reference generated and
verified against the momentum equation — it is the suite's only
parameter-free comparison, where `u/u_max = 1-(y/h)^2` holds for every
fluid, gap, and pressure gradient, so agreement cannot be manufactured by
rescaling. It has not been run yet.

`onera-m6` is blocked: its shipped scenario flies a symmetric-section
stand-in, so the measured AGARD Cp cannot be scored against it, and the M6
rung of the novelty ladder therefore has no quantitatively scored case. N3
and N4 are unexercised, so H4's degradation curve has no points.

**H4 and H5 are untouched.** No calibration curve, no `silent_wrong_rate`,
no empty-corpus arm, no longitudinal study. H5 is the plan's flagship and
its critical path.

**No external baseline.** Half A's claim is comparative and nothing has
been compared to Foam-Agent or any other published system. The
consultant-off ablation above is the first of the three the plan asks for;
narration-off and self-reported-validation are unrun, and the one that ran
is on two cases at two seeds.

**CI covers Tier 0 only.** `.github/workflows/tier0.yml` runs the test
suite, the tool arm over the fault corpus, and the detection curve on every
push, and fails if the skip count grows past the twelve tests that need
OpenFOAM. The nightly Tier 1 smoke run — one cheap case end to end against
a live model — is still unwired, and it is the one that would catch a
regression the unit tests cannot see.

**Portability caveat stands.** Every run here used Claude Code with
`CLAUDE.md` as its system prompt. The automation gate is enforced only
under that client, so `hitl_compliance` is not comparable across the
portability matrix until the deferred model-agnostic work lands.
