# Running the workshop on the cluster (FSU RCC)

Everything in [`README.md`](README.md) also runs on an RCC compute node: the
same `./setup.sh`, the same agents, the same two-step demo. On the cluster
`setup.sh` switches to **HPC mode** on its own (Slurm present, no `apt`):

| | Laptop / WSL2 | Cluster |
|---|---|---|
| OpenFOAM v2412 | apt package | Apptainer image (`.hpc/openfoam-v2412.sif`) |
| sudo | needed | never |
| Node.js, Ollama | system packages | unpacked under `~/.local` |
| Field renders (ParaView) | yes | skipped |
| Local model | your GPU/CPU | the node's GPU/CPU |

Why an image: after the 2026 AlmaLinux 9 upgrade the cluster's own
OpenFOAM modules stop at `openfoam/7.0`, and the older shared v2412 build no
longer runs (it links an OpenMPI that was removed). The official v2412
image runs the same OpenFOAM the laptops use, whatever the cluster ships.
`scripts/with-openfoam.sh` picks the apt install or the image transparently,
so `.mcp.json` and `kilo.jsonc` are the same on both.

## 1. Get a compute node, in a login shell

Compute nodes reach the internet only through RCC's web proxy, which is set
up by **login** shells (`bash -l`). The agents need it (frontier models,
`ollama pull`), so always start an interactive job with `bash -l`:

```bash
# CPU node (frontier-only, or a local model on CPU):
srun -A genacc_q -p genacc_q -c 8 --mem=32G -t 3:00:00 --pty bash -l

# GPU node (local model on GPU):
srun -A gpu_q -p gpu_q --gres=gpu:1 -c 8 --mem=32G -t 3:00:00 --pty bash -l
```

Use the partition and account your instructor gives you (a workshop
reservation adds `--reservation=<name>`). If you work through VS Code
Remote-SSH on a node, its terminals are login shells already.

Check the proxy is live: `echo $HTTPS_PROXY` should print
`http://web-proxy.rcc.fsu.edu:3128`.

## 2. Set up

```bash
cd /gpfs/research/<group>/$USER        # or your home
git clone https://github.com/kalagotla/agentic-openfoam-fsu.git agentic-openfoam
cd agentic-openfoam
./setup.sh
```

The first run builds the OpenFOAM image (~1 GB, 5–15 min) unless your
instructor has already built one. Then point at it and skip the build:

```bash
export AOF_OPENFOAM_SIF=/gpfs/research/<shared>/openfoam-v2412.sif
./setup.sh
```

(add the `export` to `~/.bashrc` so the agents find it in every session).

Model weights are large (`gpt-oss:20b` is 13 GB). To keep them out of your
home quota, point Ollama at research storage before `setup.sh`:

```bash
export OLLAMA_MODELS=/gpfs/research/<group>/$USER/ollama-models
```

(and add that to `~/.bashrc` too).

## 3. Each new session

The Ollama server lives only as long as your job. On a fresh node:

```bash
cd agentic-openfoam
./scripts/local-model.sh     # starts Ollama, re-uses the pulled model
./scripts/doctor.sh          # optional: everything green?
```

Then continue exactly as in [`README.md`](README.md) §2 (`claude`, `kilo`,
`tail -f cases/work/<name>/REPORT.md`).

## Cluster notes

- **GPUs.** The GTX 1080 Ti nodes (11 GB each) run `gpt-oss:20b` split across
  two cards; request `--gres=gpu:2`. On one card, `setup.sh` picks a smaller
  model (or pass `--model qwen3:8b`).
- **Signing in to Claude Code** on a node prints a URL; open it on your
  laptop and paste the code back.
- **Solver runs** happen inside your interactive job, on its cores. Keep
  `-c` at 8 or more for the snappyHexMesh scenarios.
- **Parallel runs** (`decompose_par` + `n_procs > 1`) use the image's MPI
  within the node.
