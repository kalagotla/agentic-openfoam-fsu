# Dev Container — agentic-openfoam

VS Code Dev Containers wrapper for the [Dockerfile](../Dockerfile) at
the repo root.

## How to use

1. Install the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) in VS Code.
2. Open the repo in VS Code.
3. Command Palette → *Dev Containers: Reopen in Container*.
4. First build takes ~25 min (OpenFOAM-v2412 base image + uv sync).
   Subsequent opens are instant.

You end up inside a terminal where:

- OpenFOAM is sourced (`echo $WM_PROJECT_VERSION` → `v2412`).
- `uv sync` has already run; all four MCP servers are installed.
- Your `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OLLAMA_BASE_URL`
  (if set on the host) are forwarded into the container — no need
  to re-export.

Then run:

```sh
uv run scripts/run_agent.py --backend anthropic \
    --prompt "Set up and run cases/scenarios/lid-cavity.yaml"
```

or the Ollama equivalent. See [`docs/runtime-options.md`](../docs/runtime-options.md)
for the full matrix.
