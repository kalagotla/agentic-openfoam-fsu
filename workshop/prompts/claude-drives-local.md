# Prompt: a frontier agent drives the local model

The middle of the ladder: the frontier model does what a local model cannot
(read the scenario and the corpus, check tutorial files, plan, judge) and
the local model does the hands-on work from a precise plan. Use it for
Step 2 after Step 1's entry is promoted. In Claude Code:

```
claude
```

and paste the text below the line. The same prompt works in Copilot or
Codex.

---

Set up and run cases/scenarios/lid-cavity-re1000.yaml in the case folder
cases/work/lid-cavity-re1000--hybrid, but do not change the case yourself:
a local model does all the hands-on work from a plan you write.

1. Read the scenario and look up the corpus entry for the template tutorial
   with `consultant` `get_tutorial_annotation`.
2. Write a step-by-step plan for the local model, following
   docs/local-plan-format.md exactly. Check every replacement key against
   the tutorial file with `read_tutorial_file` before you use it. Save the
   plan to cases/work/plan-lid-cavity-re1000--hybrid.md. Tell the plan to run
   straight through without pausing.
3. Run it in the foreground and wait for it to finish (about two minutes):
   `scripts/local-worker.sh cases/work/plan-lid-cavity-re1000--hybrid.md`
4. Read the verdict and the narrated steps it prints, and check the case's
   REPORT.md. If a step failed, fix the plan and run it once more.
5. Tell me the verdict, how many tool calls failed, and what you had to fix.
