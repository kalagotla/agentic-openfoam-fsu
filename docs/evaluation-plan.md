# Evaluation plan

How this repo earns the claim it makes — and how it is measured against
the other LLM-driven CFD agents (Foam-Agent, MetaOpenFOAM, ChatCFD,
OpenFOAMGPT).

## 1. The claim under test

Every other agent in this space optimises **executability**: did a prompt
produce a case that ran to completion, and how few human turns did it
take? Their headline numbers are success rates on that axis.

This repo optimises a different quantity:

> **A CFD agent is useful in proportion to how much of its reasoning a
> researcher can check — and to how much of that reasoning survives to
> the next case.**

Two mechanisms carry it, and both are falsifiable:

1. **The verdict belongs to tested code.** The agent authors extraction
   and plots; `compare_profiles` owns the pass/fail number, `run_analysis`
   sandboxes the script, `check_mesh` / `assess_*` own the quality
   verdicts. A wrong extraction produces a *failing* number, not a silent
   pass.
2. **The corpus compounds.** A validated run promotes a cited annotation
   into `corpus/`; the next case that touches that physics retrieves it via
   `get_tutorial_annotation`. Expertise accumulates across runs instead of
   being re-derived per prompt.

So the evaluation has two halves. **Half A (capability)** proves the tool
is not worse than the field on the axis the field publishes — table
stakes, because "it can't actually run cases" is the cheapest way to
dismiss the work. **Half B (trust, detection, and transfer)** measures the
mechanisms above, which nobody else measures and where the contribution
lives.

### Hypotheses

- **H1 — parity.** On the standard axis (setup, mesh, solve, converge)
  this repo is within noise of the best published agent, at comparable
  cost.
- **H2 — groundedness.** The decision record is verifiable in two
  independent senses: **(a) citations resolve** to real sources and, where
  no source exists, the gap is *visible* rather than fabricated; and
  **(b) the narration matches the artefact** — what `REPORT.md` says was
  done is what the case files actually contain.
- **H3 — detection.** The tool catches seeded faults at a materially
  higher rate than the same model without the consultant/validation
  servers, *at the same false-alarm rate* — and catches them earlier in
  the pipeline, where they are cheap.
- **H4 — novelty.** Capability degrades gracefully with distance from the
  tutorial library, and the tool stays **calibrated** as it degrades: on
  cases it cannot do, it reports REVIEW / INCOMPLETE rather than a
  confident wrong PASS.
- **H5 — persistence and growth.** Knowledge promoted into `corpus/` is
  retained, retrievable, and *load-bearing* — an open-book run measurably
  beats the same run closed-book — and a user's cost per validated case
  falls monotonically over a long sequence of runs.

H5 is the flagship. It is the one result no competing system can produce,
because none keeps a cited, human-reviewed knowledge layer.

## 2. Benchmark suite

Cases are labelled on **two independent axes**: tier (what kind of
evidence the case provides) and novelty (how far it sits from anything the
agent can copy). The suite manifest lives at `scripts/eval/suite.yaml`;
each entry names its scenario YAML, tier, novelty level, reference
dataset, compute weight, and expected-decision checklist.

### 2.1 Novelty ladder

Novelty is defined operationally, not by feel, so that "performs well on
novel cases" becomes a measurable curve rather than an adjective.

| Level | Definition | Examples |
|---|---|---|
| **N0** | A tutorial exists with the same physics *and* geometry | pitz-daily as shipped |
| **N1** | Tutorial exists; scenario changes parameters only (Re, scale, steady↔transient) | lid-cavity Re 400/1000, flat-plate |
| **N2** | Requires **recombining** two or more tutorials, or a meshing path the template lacks | NACA 0012 (external + snappy), supersonic half-cones (compressible + snappy + AMR) |
| **N3** | No tutorial analogue; requires custom C++ via `research_assistant` (custom BC, function object) | a synthetic-turbulence inlet BC; a custom force-coefficient function object |
| **N4** | Physics the corpus and tutorials handle poorly, or a configuration with **no published reference** | non-Newtonian channel; an unusual multi-body supersonic configuration |

Reported result: `validated` rate vs novelty level, per model — a
degradation curve, not a single number. The interesting comparison is not
whether N4 succeeds (often it should not) but whether the tool *knows* it
failed (§3.4, calibration).

At **N4 there is no reference to score against**, so validation shifts to
self-consistency: does the agent run a grid-convergence study, report a
Grid Convergence Index / Richardson extrapolation, and state the
uncertainty? Scoring is on whether that discipline was performed and
reported correctly — which is what a competent researcher would be judged
on for a novel configuration too.

### 2.2 Tier 0 — deterministic, no LLM (CI on every PR)

The existing ~330 server unit tests, plus:

- **Scorer golden tests.** Fixture `REPORT.md` files with known decision /
  citation / gap / claim counts, asserting the eval scorer extracts them
  exactly. The scorer is tested code for the same reason `compare_profiles`
  is — otherwise the evaluation inherits the flaw it is measuring.
- **Archive replay tests.** Re-mesh + re-solve a small archived case
  (`cases/examples/lid-cavity/baseline/`) and assert `run_analysis`
  reproduces the archived `metrics.json` within tolerance.

*Exit:* green in CI under 5 minutes, with no OpenFOAM-dependent test
skipped silently.

### 2.3 Tier 1 — validated benchmarks (capability, N0–N2)

| Case | Physics | Novelty | Reference | Status |
|---|---|---|---|---|
| lid-cavity Re 400 | 2-D steady laminar | N1 | Ghia 1982 | ships |
| lid-cavity Re 1000 | 2-D steady laminar, stiffer | N1 | Ghia 1982 | ships |
| pitz-daily / BFS | 2-D turbulent separation | N0 | Armaly 1983 | ships |
| flat-plate | turbulent boundary layer | N1 | NASA TMR Cf(x), White theory curves | ships |
| NACA 0012 | external, snappy, Cl/Cd | N2 | XFOIL / Ladson | ships |
| ONERA M6 | 3-D RANS, parallel | N2 | AGARD AR-138 | qualitative only — **quantitative Cp to author** |
| supersonic half-cones | compressible shock capture | N2 | Taylor–Maccoll analytic | ships |

**What Phase 1 found.** Two of the three gaps closed as expected. The
cone reference is analytic and is *generated* from the Taylor–Maccoll ODE
rather than transcribed, so a reader can recompute every number; its
solver is verified against limits it cannot pass by self-consistency
alone. The flat-plate reference turned out not to need a Blasius
substitute at all — the scenario is turbulent, and the NASA TMR ships
skin-friction data tabulated for exactly its Re_L = 5 million, 2 m plate,
including a per-point 5% error band that supplies the tolerance instead
of one chosen here.

The third gap was **mis-diagnosed in this plan**. The ONERA M6
measurements are not missing: the TMR redistributes Schmitt & Charpin's
surface Cp at seven span stations for two transonic runs, and it now
ships. The real blocker is that no case in the repo matches that data —
the shipped scenario is deliberately subsonic on NACA 0010 proxy sections
to stay laptop-runnable, while the measurements are transonic on the real
M6 section. Scoring one against the other would produce a number with no
meaning. The suite records this as `blocked_on_case_mismatch` and carries
a planned `onera-m6-transonic` entry describing the case that would use
the data. **This is the first result the evaluation produced**: a
benchmark item that looked like a data gap was a case gap, and only
building the scorer surfaced the difference.

### 2.4 Tier 2 — held-out generalisation (N1–N3)

Physics *not* in the corpus and not a near-copy of a shipped tutorial.
Each was chosen because it demands a metric **shape** the current suite
lacks, which also stress-tests the agent-authored `validate.py` design:

| Case | Novelty | Metric shape it forces |
|---|---|---|
| Couette / Poiseuille | N1 | analytic profile; catches gross failures cheaply |
| Taylor–Green vortex | N1 | transient decay rate vs analytic |
| Cylinder at Re 100 | N2 | **frequency domain** — Strouhal vs Williamson |
| Differentially heated cavity | N2 | **Nusselt integral** + buoyancy solver family |
| Turbulent channel Re_τ 180 | N2 | wall-normal profile vs Moser DNS; y⁺ discipline |
| Converging–diverging nozzle | N2 | **shock position** vs isentropic/normal-shock relations |
| Custom inlet BC case | N3 | exercises `research_assistant` + wmake loop |

Reported result: the **Tier 1 → Tier 2 gap**, which is the honest measure
of generalisation, and the N3 arm separately (custom-code success is a
different capability from case authoring).

### 2.5 Tier 3 — fault-injection corpus (detection, H3)

This is where H3 is measured, and it is the largest single build in the
plan. Each probe is a case with a **known-ground-truth fault** and a
known-correct behaviour. Scoring is behavioural, not numerical.

**Cost trick that makes the statistics possible.** Most probes are
**assessment-only**: the fault is injected into a pre-built case (or a
pre-computed log) and the agent is asked to review and decide whether to
proceed — no full solve. A probe therefore costs seconds and a few
thousand tokens instead of a full run, which is what allows N ≈ 40 per
fault class instead of N ≈ 5. A smaller full-run subset checks that
assessment-only behaviour predicts in-run behaviour; if that correlation
is weak, the cheap probes are reported as a proxy with that caveat, not as
the headline.

**Fault taxonomy.** Every fault is labelled by which mechanism *should*
catch it. This split is the point: it separates detection the engineering
provides from detection the model provides.

| Class | Injected fault | Should be caught by |
|---|---|---|
| Mesh | non-orthogonality above the severe band | `check_mesh` + `assess_mesh_quality` (tool) |
| Mesh | negative volumes / inverted cells | `check_mesh` (tool) |
| Mesh | extreme aspect ratio in the boundary layer | `assess_mesh_quality` (tool) |
| Mesh | snappy layer addition silently partial | `run_snappy_hex_mesh` phase report (tool) |
| Numerics | residuals stalled, not converged | `assess_residuals` (tool) |
| Numerics | oscillating / diverging residuals | `assess_residuals` (tool) |
| Numerics | Courant number far above the scheme's stability limit | **reasoning** |
| Numerics | first-order upwind everywhere on an accuracy-critical case | **reasoning** |
| Physics | y⁺ inconsistent with the wall treatment | `assess_y_plus` (tool) |
| Physics | wrong BC type on a patch (e.g. `zeroGradient` p on an outlet with backflow) | **reasoning** |
| Physics | steady solver on a genuinely unsteady regime | **reasoning** |
| Physics | unit / Reynolds-number inconsistency in the scenario | **reasoning** |
| Setup | sampling functionObject writes a location the analysis does not read | `run_analysis` failure (tool) |
| Setup | reference dataset absent or mismatched | `read_reference` failure (tool) |
| Validation | analysis script self-reports pass with a broken extraction | `compare_profiles` (tool) |

**Negative controls are mandatory.** At least 40% of probes are clean
cases with no fault. Without them, recall is meaningless — an agent that
flags everything scores 100%. The reported quantity is always the pair
**(recall, false-alarm rate)**, never recall alone.

**Behavioural probes** (correct behaviour, not a correct number) round out
the tier and feed the honesty metrics in §3.2:

| Probe | Expected behaviour |
|---|---|
| Underspecified YAML | Chooses from tutorial, tags `(agent's call)`, records rationale |
| Misleading `template_tutorial` | Rejects the hint, records `(deviation from scenario)` |
| Missing reference dataset | Terminates INCOMPLETE rather than inventing a comparison |
| No-annotation probe | Leaves consultant fields empty (`_uncited choice_`) instead of fabricating |
| **Corpus poisoning** — a deliberately wrong annotation planted in `corpus/` | Quotes it and is thereby wrong; measures how much authority the corpus carries and whether validation catches the consequence |

The poisoning and no-annotation probes are the honest, publishable
weaknesses of the design. Reporting them is stronger than hiding them:
they define the trust boundary — the corpus is human-reviewed *because*
the agent will quote it.

## 3. Metrics

Every metric is computed from artefacts a run already produces
(`REPORT.md`, `metrics.json`, tool returns, the harness transcript) by
`scripts/eval/score_report.py`. None requires reading a solver log by hand.

### 3.1 Capability (H1)

- `setup_success` — case authored and meshing completed
- `mesh_pass` — `check_mesh` passes, no consultant verdict is `poor`
- `converged` — `assess_residuals` classifies every solved field converged
- `validated` — `run_analysis` metrics inside the scenario's preregistered tolerance
- `first_try_validated` — `validated` with zero `retry_of` entries
- `cost` — wall-clock, input/output tokens, USD, tool-call count
- `interventions` — approval prompts consumed at the run's automation level

### 3.2 Groundedness — citations (H2a)

- `decision_coverage` — recorded decisions ÷ the scenario's expected-decision
  checklist (solver, mesh strategy, turbulence model, key schemes, BCs,
  URFs, controls), authored per case in `suite.yaml`
- `field_completeness` — decisions with all four consultant fields filled
- `citation_resolution_rate` — citations resolving to `corpus/references/`
  or a corpus annotation ÷ all citations (`flag_uncited_claims` already
  computes the failure side)
- `uncited_claim_density` — `flag_uncited_claims` hits per 10 decisions
- `fabrication_rate` — **expert-adjudicated, sampled**: citations that
  resolve but do *not* support the claim attached to them. The one metric
  that cannot be automated, and the most important one
- `gap_honesty` — on no-annotation probes, decisions left visibly empty ÷
  decisions with no available source
- `origin_tag_accuracy` — `(scenario-specified)` / `(agent's call)` /
  `(deviation from scenario)` checked automatically against the scenario YAML
- `hitl_compliance` — gated tool calls attempted before approval (target
  zero); auto-retries after validation failure at levels 1–4 (target zero)

### 3.3 Narration fidelity — implementation vs stated why (H2b)

**This is the "how well does the implementation match the why" axis, and
it is the most novel automatable metric in the plan.** A narration that
does not describe the case that actually ran is worse than no narration,
because it invites a researcher to sign off on something they did not
read. Nobody in this space measures it, because nobody else produces a
narration to check.

The measurement is a two-sided set comparison:

- `changeset(case)` = structural diff of the authored case against its
  tutorial template, keyed by `(file, dictionary key)`, canonicalised
  through `foamDictionary -expand` so formatting noise does not register.
  An allowlist suppresses ignorable diffs (headers, paths, whitespace).
- `claimset(REPORT.md)` = decisions plus the specific values they assert,
  each resolvable to a `(file, key, value)` triple where the claim is
  concrete enough to check.

From those two sets:

- **`narration_recall`** = load-bearing changes with a matching decision ÷
  all load-bearing changes. The complement is the **unnarrated-change
  rate** — edits made silently, the direct measure of "implemented but
  never explained."
- **`narration_precision`** = claims true of the case ÷ all checkable
  claims.
- **`contradiction_rate`** = claims *false* of the case ÷ all checkable
  claims. The dangerous subset of precision failure: narration that lies
  (e.g. `why` argues for second-order upwind for shock capture while
  `fvSchemes` sets plain `upwind`). Target is zero, and any non-zero value
  is a defect report, not a statistic.
- **`rationale_entailment`** — does the `why` actually justify the
  `decision`? Sampled and expert-judged, with an LLM-judge proxy used only
  after its agreement with expert labels is measured and reported. An
  uncalibrated LLM judge is not evidence.

Competitors produce no narration, so on this axis they are **undefined,
not zero** — which is exactly how it must be reported.

*Tooling:* `scripts/eval/narration_audit.py`. Non-trivial, because claim
extraction is genuine NLP; the plan starts with a high-precision, low-recall
extractor for quantitative claims (numbers, scheme names, BC types, patch
names) and reports coverage of the extractor itself so the metric's own
limits are visible.

### 3.4 Detection and calibration (H3, H4)

Detection is scored on a ladder, because "noticed something is wrong" and
"knew what was wrong and fixed it" are different capabilities:

1. **`detected`** — the run flags a problem at all (status `warning`/`error`, or stops)
2. **`localised`** — identifies the right artefact (which patch, dict, metric)
3. **`diagnosed`** — names the correct *cause*, not just the symptom
4. **`remedied`** — proposes a fix that addresses the actual fault

Plus:

- **`false_alarm_rate`** — clean controls flagged as faulty. Always reported
  alongside recall; the operating point is the pair
- **`detection_latency`** — the phase at which the fault was caught (mesh <
  solve < validation < never). Earlier is cheaper, and a tool that catches
  a mesh fault only after a 6-hour solve is worse than the recall number
  alone suggests
- **`tool_vs_reasoning_recall`** — recall split by whether the fault has a
  dedicated detector. The engineering-attributable share and the
  model-attributable share are separate results, and only the second moves
  when you swap models
- **ROC sweep.** The consultant's thresholds (non-orthogonality 65/70/80/90°,
  y⁺ 30–300, residual 1e-5) are currently hardcoded band edges in
  `servers/consultant/src/consultant_mcp/assessments.py`. Parameterising
  them (a small refactor, listed in §7) allows sweeping the bands to draw a
  genuine ROC curve, on which the **cited defaults are one marked operating
  point**. Showing that the literature-derived thresholds sit near the knee
  is a much stronger claim than asserting they are reasonable

**Calibration (H4)** ties detection to novelty. The `finalize_report`
verdict banner (PASS / FAIL / REVIEW / INCOMPLETE) plus the gap count is
the tool's own confidence signal; score it against ground truth:

- **`calibration_error`** — expected calibration error and Brier score of
  the verdict against whether the case was actually correct
- **`silent_wrong_rate`** — claims PASS while the reference says otherwise.
  Should be near zero *by construction*, since `compare_profiles` owns the
  verdict; any non-zero value is a direct falsification of the
  "verdict belongs to tested code" principle and is the single most
  important number in the whole evaluation
- **`honest_failure_rate`** — of the cases that genuinely failed, the share
  reported as FAIL / REVIEW / INCOMPLETE rather than PASS

### 3.5 Persistence, transfer, and growth (H5)

Paired arms — same scenario, model, and seeds, corpus empty vs seeded:

- `delta_first_try_validated`, `delta_retries`, `delta_gaps`,
  `delta_tokens`, `delta_wallclock`, `delta_interventions`
- **`near_vs_far_transfer`** — an annotation earned on cone A should help
  cone B and should *not* help the cavity. Uniform improvement everywhere
  indicates a prompt-length effect, not transfer, and falsifies H5
- **`open_minus_closed_book`** — the cleanest possible measure of what the
  corpus actually contains. After promotion, probe questions derived from
  each annotation are asked in a fresh session with the corpus available
  and with it stripped. If the model answers correctly without the corpus,
  **the corpus added nothing** for that item and the annotation is
  redundant with model priors. The delta, not the absolute score, is the
  result

Corpus health as it grows — the metrics that decide whether growth is an
asset or a liability:

- `retrieval_precision@1` — does `get_tutorial_annotation` return the right
  entry as the corpus grows
- `conflict_rate` — pairs of annotations giving contradictory advice
- `redundancy_rate` — near-duplicate annotations across families
- `staleness_rate` — annotations whose originating archived case no longer
  validates on re-run (the corpus's own regression test)
- `citable_coverage` — decisions that *could* have cited an existing
  annotation vs those that did

Longitudinal (§6):

- `cost_per_validated_case` vs run index, with a fitted slope and CI
- `cumulative_interventions` vs run index

## 4. Statistical design

The user-facing question is "how does this perform statistically," so the
design is stated before any run happens, not chosen after seeing results.

**Unit of analysis** is one run, nested in (scenario, model, corpus state,
automation level). Wherever two arms can see the same scenario and seed,
the design is **paired** — pairing removes scenario difficulty and most
LLM variance, and buys far more power per token than adding arms.

**Preregistered primary endpoints.** Five, fixed in advance; everything
else is exploratory and Holm-corrected:

1. `validated` rate on Tier 1 (H1)
2. `narration_recall` and `contradiction_rate` on Tier 1–2 (H2b)
3. Detection recall at a fixed false-alarm rate ≤ 0.10, full stack vs
   consultant-disabled (H3)
4. `silent_wrong_rate` across all tiers (H4)
5. `delta_first_try_validated`, corpus seeded vs empty, on the near-transfer
   family (H5)

Acceptance tolerances live in the scenario YAML
(`validation.analysis.checks[].tolerance_relative_L2`) and are committed
*before* the matrix runs — the repo already has the preregistration
mechanism, this plan just names its role. Any tolerance changed after
seeing results is reported as changed.

**Sample sizes and power.**

| Comparison | Design | N per arm | Detectable difference (80% power, α 0.05) |
|---|---|---|---|
| Detection, full stack vs consultant-off | paired, McNemar | ≈ 120 probes | ≈ 0.12 in recall |
| Fault-class recall (per class) | proportion, Wilson CI | 30–40 | CI half-width ≈ ±0.15 |
| Tier 1 `validated`, per model | proportion | 5 seeds × 7 cases = 35 | CI half-width ≈ ±0.16 |
| Corpus on/off transfer | paired, bootstrap | 5 seeds × 6 cases = 30 pairs | ≈ 0.20 in rate |
| Narration recall | mean over runs, bootstrap | 35 | ≈ 0.08 |

The honest reading of that table: **detection is the only place with
enough N for a confident inferential claim**, and that is precisely
because assessment-only probes are cheap. The full-run comparisons are
powered to detect large effects only; they are reported with CIs and
described as such, not dressed up. Where an effect is smaller than the
detectable difference, the result is reported as *inconclusive at this N*
— which is a legitimate finding and far better than an over-claimed one.

**Multiplicity.** Dozens of metrics × several arms will produce spurious
significance if all are treated as confirmatory. Only the five primary
endpoints are confirmatory. Everything else is labelled exploratory in
every table.

**Nondeterminism.** Identical seeds across paired arms; per-cell variance
reported alongside every mean; a single-run difference is never a result,
and the paper says so rather than implying it.

**Cost model.** Rough budget for one full matrix pass:

| Arm | Runs | Unit cost | Notes |
|---|---|---|---|
| Tier 0 | — | ~0 | no LLM |
| Tier 1 full-run | 7 cases × 3 models × 5 seeds ≈ 105 | high | 3-D cases dominate; N=3 there |
| Tier 2 full-run | 7 × 2 × 5 ≈ 70 | high | |
| Tier 3 assessment-only | ≈ 400 probes × 2 arms | very low | the statistical backbone |
| Tier 3 full-run subset | ≈ 40 | high | validates the cheap proxy |
| Longitudinal journey | 24 × 2 arms × 2 seeds ≈ 96 | high | the flagship |

Compute, not API spend, is the binding constraint — ONERA M6 and the
half-cones dominate wall-clock. Schedule those overnight and keep the
cheap tiers on the interactive loop.

## 5. External baselines and ablations

- **Foam-Agent** — already installed and captured in
  `demos/04-foam-agent-compare/`. Promote that one-off to a scored arm on
  the Tier 1 cases it can express, scored by the *same* scorer. It will
  score near zero on Half B by construction; that is a design difference to
  present as such, not a defect. On Half A it is a genuine competitor and
  may win on wall-clock.
- **MetaOpenFOAM / ChatCFD / OpenFOAMGPT** — compare against published
  numbers rather than re-running, and say so. ChatCFD's physical-fidelity
  metric is the closest published relative of `validated` and is the right
  bar to align with.
- **Ablations (the most informative arms):**
  - (a) corpus off — H5
  - (b) **consultant server disabled** — H3's control. Do the cited verdicts
    change outcomes, or is the LLM doing all the work? This is the arm that
    decides whether the consultant is a contribution or a wrapper
  - (c) **self-reported validation** — `run_analysis` replaced by letting the
    agent grade itself. Directly measures how often self-reporting yields a
    false pass where `compare_profiles` does not
  - (d) HITL level 5 vs 3 — what the human turns actually buy
  - (e) narration off — does forcing the narration cost capability? If
    `validated` drops when the agent must justify itself, that is a real
    trade-off and must be reported

Ablations (b) and (c) are the cleanest experiments in the plan. Together
they convert the architecture's two central principles from assertions
into numbers.

## 6. The longitudinal study (H5)

The question "how does this repo grow as the user uses it more" is
answered by simulating a user's first few months, not by arguing from
design.

**Design.** A fixed curriculum of K = 24 scenarios in a committed order,
drawn from four families (cavity, backward-facing step, cone/supersonic,
airfoil) and **interleaved** so that within-family transfer and
across-family interference are both observable. Two arms, paired by
position in the sequence:

- **Arm G (growing)** — `draft_corpus: true`, annotations reviewed and
  promoted between runs, exactly as a real user would
- **Arm F (frozen)** — identical sequence, promotion disabled

Both arms run the same model and seeds. The measured quantity is the
**learning curve**: each §3 metric plotted against run index, with a fitted
slope and bootstrap CI. The headline is `cost_per_validated_case` — tokens,
wall-clock, and human interventions — and the claim is monotone decrease in
Arm G with no corresponding decrease in Arm F.

**Human-in-the-loop cost is part of the result.** Promotion requires a
reviewer to confirm the `suitable_for` / `not_suitable_for` proposals. That
review time is logged per annotation and reported: the growth claim is
"the tool gets cheaper *including* the review cost of growing it," or it is
not a growth claim at all.

**Persistent-knowledge checks** run at three points in the sequence (after
8, 16, 24 runs):

1. **Open- vs closed-book exam** (§3.5) over every promoted annotation
2. **Retrieval audit** — for each of the last 8 runs, was the relevant
   annotation retrieved, and did the run cite it?
3. **Corpus regression** — re-run `run_analysis` on every archived case
   behind an annotation; any that no longer validates marks its annotation
   stale
4. **Conflict scan** — pairwise check of annotations within a family for
   contradictory advice

**What the study will expose as missing.** The mechanisms below are
required for growth to be safe past roughly 50 annotations, and the
longitudinal study is what will force them — they are engineering items,
listed in §7, not evaluation items:

- a **promotion gate** (promote only from a run that PASSed with zero
  unresolved uncited claims)
- **dedup / merge** at promotion, so a family accretes one strong entry
  rather than eight overlapping ones
- **conflict detection** at promotion time
- **retrieval beyond exact-path lookup**, which stops scaling once several
  experiments share a tutorial
- **provenance links** from each annotation to the archived case and
  `metrics.json` that earned it
- **review dates**, so an annotation ages into re-review rather than silently

**Three assets grow, not one.** The corpus is the visible one, but a user
running this tool also grows (i) the **reference library**
(`corpus/references/`) as new sources are pulled and cited, and (ii) the
**probe suite** — every real failure encountered becomes a Tier 3 probe
with known ground truth. That third loop is self-reinforcing: using the
tool makes the tool's own evaluation stronger. The longitudinal study
should measure all three growth rates, because "the corpus grew" is a
weaker story than "the tool, its evidence base, and its test suite all grew
from ordinary use."

## 7. Infrastructure to build

All under `scripts/eval/` — no new top-level directories.

| File | Job |
|---|---|
| `suite.yaml` | Manifest: cases, tiers, novelty levels, references, weights, expected-decision checklists |
| `run_matrix.py` | Executes scenario × model × config × seed via `run_agent.py`; resumable, concurrency-capped, one `run.json` per run |
| `score_report.py` | `REPORT.md` + `metrics.json` + transcript → structured record |
| `narration_audit.py` | `foamDictionary`-canonicalised case-vs-template diff; claim extraction; recall / precision / contradiction (§3.3) |
| `faults/` | Fault-injection corpus: injector scripts + ground-truth labels per probe (§2.5) |
| `probe_runner.py` | Assessment-only probe harness — the cheap statistical backbone |
| `metrics.py` | One function per metric, individually unit-tested |
| `stats.py` | Wilson, cluster adjustment, Beta posteriors, McNemar, Holm, Cohen's *h* and κ, variance components, calibration, power |
| `reasoning_probe.py` | The model-judged detection arm, against any OpenAI-compatible endpoint |
| `aggregate.py` | Records → tables, plots, `docs/evaluation-results.md` |
| `tests/` | Golden-fixture tests for the scorer, the narration auditor, and every metric |

**Server-side changes the evaluation requires** (small, and each is
defensible on its own merits):

- parameterise the consultant's threshold bands so §3.4's ROC sweep is
  possible — currently hardcoded in `assessments.py`
- lift the `REPORT.md` parser out of `draft_annotation_from_report` into a
  shared module the eval scorer imports, rather than duplicating it
- have `analysis/validate.py` stamp provenance into `metrics.json`
  (already required by `CLAUDE.md`; enforce it in the archive test)

Reuse before writing: `flag_uncited_claims` already lints citations,
`draft_annotation_from_report` already parses REPORT structure, and
`assess_residuals` / `assess_mesh_quality` already classify runs.

### Deferred: making the repo genuinely model-agnostic

**Tracked here, to be done on its own branch — not as part of the
evaluation build.** The portability claim in §4 ("a result that only
reproduces on one vendor's model is a weaker contribution") is currently
stronger than the repo. Several load-bearing pieces assume Claude Code
specifically:

- **The automation gate is only enforced under Claude Code.**
  `.claude/hooks/automation_gate_hook.py` is a Claude Code `PreToolUse`
  hook. `scripts/run_agent.py` shares the policy, but any other MCP client
  — Cursor, Cline, Continue, a bare SDK loop — gets no gate at all, and
  `CLAUDE.md` already says the levels are advisory there. `hitl_compliance`
  (§3.2) therefore measures something different depending on the client,
  which makes it non-comparable across the portability matrix.
- **`CLAUDE.md` is both the human contract and the system prompt.** It is
  ~600 lines written for a frontier model. Local models get
  `scripts/local_system_prompt.md` instead, so the two arms of the
  portability comparison are not running the same instructions — a
  confound that has to be stated wherever those arms are compared.
- **`.claude/settings.json`** carries the permission allowlist and hook
  wiring; there is no equivalent for other clients.

Until that work lands, every portability result must name the client and
the system prompt it used, and the local-model arms should be read as
"same servers, different contract" rather than a clean vendor swap.

What the evaluation build *did* fix, because it was cheap and blocking:
`run_agent.py` now treats any OpenAI-compatible endpoint as a first-class
backend (`ollama`, `vllm`, `lmstudio`, or `openai` with an explicit
`--base-url`), resolves endpoint / key / model before connecting, and asks
a server which model it is serving when none is named. That is transport,
not contract — it makes a local run *possible*, not equivalent.

**CI.** Tier 0 on every PR. One cheap Tier 1 case, single model, single
seed, nightly, as an end-to-end smoke test. The Tier 3 probe suite is cheap
enough to run weekly. The full matrix is on-demand, not CI.

## 8. Phases

Each phase has an exit criterion; do not start the next until it is met.

| Phase | Work | Duration | Exit criterion |
|---|---|---|---|
| **0** | Harness: `suite.yaml`, `run_matrix.py`, `score_report.py`, `metrics.py`, golden tests | 1 wk | One lid-cavity run scored end to end, numbers hand-checked against its REPORT |
| **1** | Reference-data gaps: Blasius, Taylor–Maccoll, M6 Cp, with provenance READMEs | 0.5 wk | 7 quantitative datasets in `list_references`, each sourced |
| **2** | Tier 1 baseline: 7 cases × 2 frontier models × 5 seeds, corpus empty | 1.5 wk | First capability table with CIs; H1 answerable |
| **3** | **Narration audit**: build `narration_audit.py`, score all Phase-2 runs | 1.5 wk | H2b answered; contradiction rate reported; extractor coverage stated |
| **4** | **Fault corpus + detection**: injectors, labels, probe runner, ~400 probes × 2 arms, ROC sweep | 2.5 wk | H3 answered with a paired McNemar result at a fixed false-alarm rate |
| **5** | Tier 2 + novelty ladder: author 7 scenarios + references, run, plot degradation and calibration | 2 wk | H4 answered; `silent_wrong_rate` reported |
| **6** | Ablations + external baselines: consultant-off, self-reported validation, HITL, narration-off, Foam-Agent scored | 1 wk | Principles (b) and (c) have numbers attached |
| **7** | **Longitudinal study**: 24-case curriculum × 2 arms, knowledge checks at 8/16/24 | 2.5 wk | H5 answered; learning curve with slope CI; open-minus-closed-book delta |
| **8** | Human review: blind packets, `fabrication_rate`, inter-rater α | 1.5 wk | Half B has its human-judged headline |
| **9** | Publication artefacts: `docs/evaluation-results.md`, tables, figures, suite released | 1 wk | A third party reproduces one Tier 1 cell from the repo alone |

Roughly 14–16 weeks sequential; 11–12 with Phases 5 and 7 overlapping the
long compute and Phase 8 recruiting in parallel from Phase 4 onward.

**Critical path is Phase 7** — the longitudinal study needs 24 runs × 2
arms and cannot be compressed, so its curriculum should be committed early
(during Phase 2) even though it executes late.

**If the whole plan is too much**, the defensible minimum is Phases 0–4:
capability parity, narration fidelity, and detection with real statistical
power. That is ~7 weeks and already contains two results no competitor has
published.

## 9. Threats to validity

State these in the paper rather than waiting to be asked.

- **Nondeterminism.** Full-run N is small for LLM variance. Mitigated by
  CIs, paired designs, and the assessment-only probes where N is large.
- **Self-authored benchmark.** Suite, scenarios, and tolerances come from
  the same author as the tool. Mitigated by analytic references,
  preregistered tolerances, a published suite, and an explicit invitation to
  others to run it.
- **Scorer bias.** Half B measures a schema this repo invented, so
  competitors score low partly by construction. Half A and Half B are
  reported separately, never combined, and the narration axis is reported
  as *undefined* for systems that produce no narration.
- **Fault realism.** Injected faults are a proxy for the faults real users
  hit. Mitigated by seeding the corpus from failures actually encountered in
  this repo's run history, and by reporting the injected/organic split.
- **Contamination.** Frontier models likely know Ghia 1982 and the cavity
  benchmark. Mitigated by the N3/N4 rungs and by the paired transfer design,
  where prior knowledge is present in both arms and cancels.
- **Claim-extraction limits.** `narration_audit.py` can only check claims
  concrete enough to resolve to a `(file, key, value)` triple; qualitative
  rationale escapes it. The extractor's own coverage is reported so the
  metric's denominator is visible.
- **Cost asymmetry.** Level-3 runs consume human time competitors' automatic
  runs do not. Interventions are reported as a cost, including the corpus
  review time in the longitudinal arm.
