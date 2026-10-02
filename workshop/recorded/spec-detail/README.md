# Usage levels, measured (Oct 2)

The same Re = 400 cavity at three input levels
([`lid-cavity-expert.yaml`](../../../cases/scenarios/lid-cavity-expert.yaml),
[`-guided`](../../../cases/scenarios/lid-cavity-guided.yaml),
[`-prompt`](../../../cases/scenarios/lid-cavity-prompt.yaml)), each run twice
with Claude Code headless (`claude -p`, copies at `automation_level: 5`,
empty corpus). All six runs PASS. Unedited reports and plots in the folders;
raw counts in [`metrics.json`](metrics.json) (`expert` = run 1, `expert-r2` =
run 2, and so on).

| run 1 / run 2 | Expert | Guided | Prompt |
|---|---|---|---|
| YAML lines the user wrote | 52 | 33 | 4 |
| Setup choices made by the agent | 0 / 1 | 5 / 4 | 6 / 6 |
| Steps narrated in REPORT.md | 8 / 10 | 12 / 11 | 9 / 11 |
| REPORT.md length (words) | 1.9k / 2.4k | 2.7k / 2.5k | 2.3k / 2.9k |
| Consultant tool calls | 5 / 4 | 4 / 7 | 4 / 5 |
| Fixes driven by evidence | 0 / 1 (missing scheme entry) | 2 / 1 (20×20 misses v → 40×40) | 1 / 1 (not steady → run longer) |
| Reynolds number · v error as share of the 5 % band | 400 · 97 % | 400 · 83 % | 100 (its pick) · 32 % |
| Time · cost per run | 3.4–5.9 min · $1.4–1.8 | 3.8–3.9 min · $1.7–1.8 | 2.7–3.2 min · $1.3–1.5 |

"Setup choices made by the agent" counts the choices the YAML left open
(template, operating point, flow model, mesh, boundary conditions, schemes,
run controls), classified by hand from each `record_step`; the agent's own
"(agent's call)" tags were not used consistently enough to count.

What it shows:

- **The division of labour shifts.** The less the YAML fixes, the more setup
  choices the agent makes and justifies.
- **Consultant tool calls do not grow.** The same mesh, residual and
  citation checks run at every level; the added reasoning lands in the
  decision fields (why / alternatives / when it breaks).
- **Less input let the agent pick an easier problem.** Asked for "the
  standard published benchmark", it chose Ghia's Re = 100 both times, where
  the tutorial mesh passes. Pin the operating point when it matters.
- **The expert spec was closest to failing** (v at 97 % of the band on a
  128×128 graded mesh), while the guided runs' 40×40 uniform mesh passed with
  more margin.

Two runs per level: trends, not statistics.
