# Driving Claude Code with a local LLM

You can run a local Ollama-hosted model behind Claude Code's full UX —
slash commands, file editing, MCP tools, the lot — by sitting a
[LiteLLM](https://github.com/BerriAI/litellm) proxy between Claude Code
and Ollama. LiteLLM accepts the Anthropic Messages API on its public
side and forwards to Ollama on its backend side, translating in both
directions.

This is the path to pick when you want the Claude Code experience
without an Anthropic API key, and your machine can host a tool-use-trained
30B-class model (≥24 GB VRAM, or a beefy CPU with patience).

## One-time setup

```bash
# 1. Ollama + a tool-use-trained local model
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
ollama pull gpt-oss:20b           # recommended; emits real OpenAI-style tool_calls
# alternatives: qwen3:30b, llama3.1:8b — see https://ollama.com/library?c=tools

# 2. LiteLLM proxy
uv tool install 'litellm[proxy]'

# 3. OpenFOAM environment (so the openfoam MCP server works)
of2412                            # or: source /usr/lib/openfoam/openfoam2412/etc/bashrc
```

## Per-session

Run the proxy in one terminal:

```bash
cd agentic-openfoam
litellm --config scripts/litellm_proxy.yaml --port 4000
```

In another terminal, launch Claude Code pointing at the proxy:

```bash
cd agentic-openfoam
export ANTHROPIC_BASE_URL=http://localhost:4000
export ANTHROPIC_API_KEY=sk-anything      # required by the SDK; value is ignored
claude
```

Inside Claude Code, the model selector (`/model`) lists the aliases
defined in [`scripts/litellm_proxy.yaml`](../scripts/litellm_proxy.yaml).
All of them route to the same local model by default; change the
``litellm_params.model`` lines in the YAML if you want each alias to map
to a different Ollama model.

Prompt the agent the same way you would with the Anthropic API:

```
Set up and run cases/scenarios/lid-cavity.yaml
```

## What the proxy does for you

- Inbound: receives Anthropic ``POST /v1/messages`` (Claude Code's wire
  format) with ``tools`` and ``messages``.
- Outbound: translates to Ollama's ``/api/chat`` with ``tools``.
- On the way back: maps Ollama ``tool_calls`` (and inline-content tool
  calls from quirky models) into Anthropic ``content`` blocks of type
  ``tool_use``, including the ``thinking`` block for reasoning models
  like gpt-oss.

If the round-trip ever loses a tool call, the cleanest debug step is
`curl http://localhost:4000/v1/messages` with the request Claude Code
made and inspect the response — the proxy's stdout shows every call.

## Permissions

Claude Code's permission gates work as usual. The first time the agent
calls each MCP tool you'll get an approval prompt. To skip prompts for
trusted tools, add an ``allowedTools`` entry in
``.claude/settings.local.json`` (e.g. ``"mcp__openfoam__list_tutorials"``).

## Honest expectations

What a 20-30B local model (gpt-oss:20b, qwen3:30b-a3b) on an RTX 5090
+ 32 GB RAM machine actually produces end-to-end on lid-cavity, with
the `copy_tutorial_dict` MCP tool engaged:

- ✅ All four `system/` dicts + `constant/transportProperties` + `0/{U,p}`
  authored with **valid OpenFOAM syntax** (headers, banners, separators
  preserved by `copy_tutorial_dict`).
- ✅ `blockMesh` generates the expected 5000-cell cavity with correct
  patch names.
- ✅ `checkMesh` returns `Mesh OK` (max non-orthogonality 0, skewness
  2.6e-14).
- ✅ Solver gets launched. When it fails (e.g. missing `pRefCell`), the
  model often reads the error and patches the dict — sometimes putting
  the fix in the right block, sometimes not.
- ⚠️ Solver doesn't always *converge*. Choice of solver (icoFoam vs.
  simpleFoam vs. pimpleFoam) is often wrong; the laminar lid-cavity
  needs `icoFoam`, and a 20B model will sometimes pick `simpleFoam`
  instead because that's a more common-looking name.
- ⚠️ Validation against the Ghia 1982 reference is hit-or-miss — the
  case may converge but the model can fumble the `compare_profiles`
  call.

For deterministic end-to-end completion of the harder shipped scenarios
(naca-0012, onera-m6), use the Anthropic-API path or a 100B+ local
model. Note `gpt-oss:120b` requires ~36 GB **system RAM** alone for
Ollama to load it — on a 31 GB RAM machine it refuses to start regardless
of how much VRAM you have. The local-model paths shine for
*smoke-testing the wiring*, *cheap exploration*, *teaching the loop*,
and *air-gapped environments* — not for unattended overnight sweeps.

## Why a custom MCP tool changed the outcome

Earlier runs with `gpt-oss:20b` got through the *read* phase fine but
then wrote corrupted dict content (truncated FoamFile headers,
`<content not yet>` placeholders) when asked to *generate* the case
files with `write_dict`. Small models lose OpenFOAM syntax fidelity
under generation pressure.

The fix was to introduce a `copy_tutorial_dict` MCP tool that reads a
tutorial file verbatim and writes it into the case, optionally
applying a few exact-string patches. The agent only needs to (a) pick
the right tutorial path and (b) supply the replacements — the bytes
on disk are copied, not regenerated. This shifts the model's job from
"generate valid OpenFOAM syntax" (where small models hallucinate) to
"select + patch" (which they handle reliably).

`copy_tutorial_dict` is available to every MCP client — Claude Code
will use it too when prompted, with the same byte-perfect outcome.

## Bare harness instead

If you don't want to install Claude Code, [`scripts/run_agent.py`](../scripts/run_agent.py)
is a minimal MCP-driven agent loop that talks directly to Ollama (no
proxy in between). Less UX, fewer moving parts:

```bash
uv run scripts/run_agent.py --backend ollama --model gpt-oss:20b \
    --prompt "Set up and run cases/scenarios/lid-cavity.yaml"
```

The harness uses [`scripts/local_system_prompt.md`](../scripts/local_system_prompt.md)
by default for the Ollama backend — a slim version of CLAUDE.md tuned for
the smaller context budget of local models.
