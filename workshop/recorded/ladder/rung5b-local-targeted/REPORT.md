# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — Ghia Re=1000 centerlines vs the 5% band

3 steps · 2 decisions · 0 retries · 2 gaps
<!-- END SUMMARY -->

## [22:02:48] geometry / ok — Setup from the corpus entry: icoFoam/cavity geometry, pitzDaily SIMPLE controls, 80x80, nu 0.001

- **Decision:** Apply the promoted corpus entry for incompressible/icoFoam/cavity/cavity at Re = 1000
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** _uncited choice — no annotation, reference, or paper cited._ _(cites: corpus/incompressible/icoFoam/cavity/cavity.md)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

## [22:02:57] convergence / ok — 80x80 mesh, simpleFoam converged

## [22:03:09] validation / ok — Ghia Re=1000 centerlines vs the 5% band

<details><summary>why · alternatives · when it breaks</summary>

- **Why:** _uncited choice — no annotation, reference, or paper cited._ _(cites: ghia_1982, corpus/incompressible/icoFoam/cavity/cavity.md)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | Apply the promoted corpus entry for incompressible/icoFoam/cavity/cavity at Re = 1000 | corpus/incompressible/icoFoam/cavity/cavity.md | alts, breaks |
| validation |  | ghia_1982, corpus/incompressible/icoFoam/cavity/cavity.md | alts, breaks |

<!-- END DECISIONS TABLE -->
