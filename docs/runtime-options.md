# Runtime options

The four MCP servers are tool-agnostic. Any MCP-speaking client drives them.

## Environment paths

| Path | What you need | Time to first agent run |
|---|---|---|
| **A. Native** | OpenFOAM v2412 + git + uv | ~5 min if OF already installed |
| **B. Docker** | Docker + the [Dockerfile](../Dockerfile) | ~25 min build, ~5 min after |
| **C. VS Code Dev Container** | VS Code + Dev Containers extension | ~25 min first build, instant after |

All three converge on `scripts/run_agent.py` (or any GUI MCP client) once OpenFOAM is on the PATH. Native steps in the README; Docker steps in the [Dockerfile](../Dockerfile) header; Dev Container in [`.devcontainer/README.md`](../.devcontainer/README.md).

## Agent runtime matrix

| Runtime | Cost | Local-only? | Tool-use quality | Setup |
|---|---|---|---|---|
| Claude Code | $20/mo | No | Excellent | 1/5 |
| Claude Code + LiteLLM proxy + Ollama | Free, local | **Yes** | gpt-oss:20b OK, frontier needed for hard cases | 3/5 |
| Claude Desktop | Free with Claude.ai | No | Excellent | 2/5 |
| Cursor | $20/mo | No | Excellent | 2/5 |
| Continue.dev (VS Code) | Free | Either | Good with frontier models | 3/5 |
| Cline (VS Code) | Free | Either | Good | 3/5 |
| `scripts/run_agent.py` | Free + API costs | Either | Model-dependent | 2/5 |
| Ollama via the harness | Free, local | **Yes** | gpt-oss:20b recommended | 3/5 |

### `automation_level` enforcement per runtime

A scenario's `automation_level` (1–5) pauses the run for researcher
approval at phase boundaries. How hard that pause is depends on the
runtime, because it's enforced by two shared mechanisms over one policy
(`scripts/automation_gate.py`):

- **Claude Code** — a PreToolUse hook (`.claude/hooks/automation_gate_hook.py`,
  wired in `.claude/settings.json`) forces an approval prompt before the
  gated tool. Hard gate; works even if you've allowlisted the openfoam
  tools.
- **The harness (`scripts/run_agent.py`, both Anthropic and Ollama)** —
  the dispatch loop prompts on stdin before a gated tool. Hard gate.
- **Other MCP clients (Claude Desktop, Cursor, Continue.dev, Cline)** —
  no hook runs, so the level is **advisory**: the agent honors it via the
  CLAUDE.md behavioral rules, but nothing forces the pause.

## 1. Bare harness + Anthropic API

```sh
git clone https://github.com/kalagotla/agentic-openfoam.git
cd agentic-openfoam
uv sync --all-packages
of2412
export ANTHROPIC_API_KEY=sk-ant-...
uv run scripts/run_agent.py --backend anthropic \
    --prompt "Set up and run cases/scenarios/lid-cavity.yaml"
```

A full lid-cavity run costs cents.

## 2. Bare harness + local Ollama

24+ GB VRAM recommended for 30B-class models; smaller models on CPU work for trivial prompts but not the full lid-cavity arc.

```sh
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
ollama pull gpt-oss:20b            # recommended; emits proper OpenAI-style tool_calls
# alternatives: qwen3:30b, llama3.1:8b — see https://ollama.com/library?c=tools

# Same repo setup as Path 1 above, then:
uv run scripts/run_agent.py --backend ollama --model gpt-oss:20b \
    --prompt "Set up and run cases/scenarios/lid-cavity.yaml"
```

`scripts/run_agent.py` auto-picks a slim system prompt
([`scripts/local_system_prompt.md`](../scripts/local_system_prompt.md))
when `--backend ollama`, inlines any referenced `cases/scenarios/*.yaml`
into the prompt (since the MCP servers don't expose generic file reads),
and recovers inline-JSON tool calls from models that emit them in
`message.content` instead of the OpenAI `tool_calls` field.

## 2b. Claude Code + local Ollama via LiteLLM proxy

For the full Claude Code UX (slash commands, file editing, MCP wiring)
on a local model. Setup in [`local-llm-with-claude-code.md`](./local-llm-with-claude-code.md).
Two terminals:

```sh
# Terminal 1 — proxy that exposes Anthropic /v1/messages on top of Ollama
litellm --config scripts/litellm_proxy.yaml --port 4000

# Terminal 2 — Claude Code pointed at the proxy
export ANTHROPIC_BASE_URL=http://localhost:4000
export ANTHROPIC_API_KEY=sk-anything       # required by the SDK; value ignored
claude
```

## 3. Claude Desktop

1. Download from <https://claude.ai/download> and sign in.
2. *Settings → Developer → Edit Config* opens `claude_desktop_config.json`.
3. Copy the contents of this repo's [`.mcp.json`](../.mcp.json) into the `mcpServers` field. Claude Desktop runs server commands from its own working directory — add absolute paths or `cwd` entries if servers fail to start.
4. Restart Claude Desktop. Confirm the four servers appear in the *MCP servers* panel.
5. Open a chat and prompt the agent the same way the harness is prompted.

MCP support in Claude Desktop evolves quickly; current canonical setup at <https://docs.claude.com/en/docs/claude-code/mcp>.

## 4. Continue.dev / Cline

Install from the VS Code Marketplace. Both register MCP servers from a config file (`.continue/config.yaml` for Continue.dev; see <https://docs.cline.bot/mcp-servers> for Cline). Point them at this repo's `.mcp.json`. Both expose the same tool surface as Claude Code — only the IDE chrome differs.

## Pick a path

- **Smallest setup, see it work tonight:** Path A + harness + Anthropic API.
- **No OpenFOAM yet:** Path B (Docker) + any runtime above.
- **VS Code is home:** Path C (Dev Container) + Claude Code, Continue.dev, or Cline.
- **Air-gapped / ITAR:** Path A or B + Ollama + 30B-class tool-use model.

## Verify the wiring

```sh
of2412
export ANTHROPIC_API_KEY=sk-ant-...    # or use --backend ollama
uv run scripts/run_agent.py --backend anthropic \
    --prompt "List the reference datasets available via the validation server."
```

The agent should call `validation.list_references` and report at least four datasets (`ghia_1982`, `reattachment_length`, `xfoil_polar`, `agard_ar_138_qualitative`). If a tool call errors instead, see the table below.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `*_not_found` / `foam_tutorials_unset` from a tool | OpenFOAM not sourced | `of2412` (or `source /usr/lib/openfoam/openfoam2412/etc/bashrc`) |
| `ANTHROPIC_API_KEY is not set` | Missing env var | `export ANTHROPIC_API_KEY=sk-ant-...` |
| Ollama connection refused | Daemon not running | `ollama serve &` |
| Model emits invalid JSON tool args | Not tool-use-trained | Swap to a model on the Ollama "tools" tag — `gpt-oss:20b` is the workshop default |
| Local model thrashes, never finishes lid-cavity | Model too small for long agentic workload | Move to `claude-opus-4-7` via Anthropic API for hard scenarios; keep local for smoke tests |
| LiteLLM proxy: 401 / model not found | `ANTHROPIC_API_KEY` unset or model name not in `scripts/litellm_proxy.yaml` | `export ANTHROPIC_API_KEY=sk-anything`; add the model alias in the YAML |
| `mcp` package import error | Top-level deps not synced | `uv sync` from the repo root |
| Docker build fails on `apt-get` | Container network | Check Docker daemon network config, retry |
