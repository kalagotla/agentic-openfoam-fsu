# Running the workshop on the cluster (FSU RCC)

Everything in [`README.md`](README.md) also runs on an RCC compute node: the
same `./setup.sh`, the same agents, the same two-step demo.

**Laptop or cluster?** Both work; pick one.

| | Your laptop (WSL2 / Ubuntu) | FSU cluster (workshop account) |
|---|---|---|
| Setup time | 10–20 min, mostly downloads (~15 GB with the model; fast on FSU Wi-Fi) | about 1 min; the big files are already on the cluster |
| Frontier loop (A) | yes | yes |
| Local-model loops (B, C) | yes, at the speed of your GPU (≥ 14 GB VRAM ideal) | **CPU only**: workshop accounts get no GPU, and a local model on CPU is too slow for a full run. Watch the speaker's GPU demo instead |
| After the workshop | yours to keep | workshop accounts are temporary |

The workshop accounts (`workshop-001` … `workshop-040`) are CPU-only; RCC
does not have enough free GPUs for a class to share. The speaker runs the
local-model loops on one GPU, queued hours ahead (below), with recorded
results as the fallback.

On the cluster `setup.sh` switches to **HPC mode** on its own (Slurm
present, no `apt`):

| | Laptop / WSL2 | Cluster |
|---|---|---|
| OpenFOAM v2412 | apt package | Apptainer image (`.hpc/openfoam-v2412.sif`) |
| sudo | needed | never |
| Node.js | system packages | unpacked under `~/.local` |
| Ollama + model weights | downloaded | symlinked from the class's shared store (no download) |
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
srun -p <partition> -c 8 --mem=32G -t 3:00:00 --pty bash -l
```

Use the partition (and `-A <account>`) your instructor gives you; a
workshop reservation adds `--reservation=<name>`. On a research account,
`-A genacc_q -p genacc_q` is the general CPU queue. If you work through VS Code
Remote-SSH on a node, its terminals are login shells already.

Check the proxy is live: `echo $HTTPS_PROXY` should print
`http://web-proxy.rcc.fsu.edu:3128`.

## 2. Set up

```bash
cd ~
git clone https://github.com/kalagotla/agentic-openfoam-fsu.git agentic-openfoam
cd agentic-openfoam
./setup.sh
```

No GitHub access from the cluster? The same repo is on the cluster as a
tarball; unpack it instead of cloning:

```bash
cd ~ && tar -xzf /gpfs/research/engineering/dk26/agentic-openfoam-shared/agentic-openfoam.tar.gz
cd agentic-openfoam && ./setup.sh
```

The heavy pieces are already on the cluster, in the class's shared store
named in `workshop/hpc-site.env`, so setup downloads only the small ones:

| From the shared store (symlinked, read-only) | Downloaded per person |
|---|---|
| OpenFOAM v2412 image (455 MB) | uv + Python packages, Node.js |
| Ollama (2 GB) | Claude Code, Copilot, Codex, Kilo CLI |
| model weights (`gpt-oss:20b` alone is 14 GB) | |

Your own `~/.ollama/models` then holds only symlinks and the small
`cfd-local` alias, a few kB of your home quota. To use a different image,
`export AOF_OPENFOAM_SIF=/path/to/openfoam-v2412.sif` before `./setup.sh`;
setup records the path in `~/.bashrc` so the agents find it every session.

The shared store has US-developed models only:

| Model | From | Size | Picked for |
|---|---|---|---|
| `gpt-oss:20b` | OpenAI | 14 GB | GPU node (the rehearsed default) |
| `gemma4:12b` | Google | 8 GB | smaller GPU / CPU |
| `nemotron-3-nano:4b` | NVIDIA | 2.8 GB | small machines |
| `muse-glimmer:30b` | Meta | 18 GB | try on a 24 GB GPU |
| `nemotron-3.5-lightning:30b` | NVIDIA | 25 GB | try on a 32 GB+ GPU |

Switch with `./scripts/local-model.sh <model>`; a model in the store links
instantly. Any other model is downloaded into your own store (through
`scripts/ollama-fetch.sh`, because `ollama pull` stalls behind RCC's web
proxy).

## 3. Each new session

The Ollama server lives only as long as your job. On a fresh node:

```bash
cd agentic-openfoam
./scripts/local-model.sh     # starts Ollama, re-uses the pulled model
./scripts/doctor.sh          # optional: everything green?
```

Then continue exactly as in [`README.md`](README.md) §2 (`claude`, `kilo`,
`tail -f cases/work/<name>/REPORT.md`).

## 4. The local model on a GPU, without waiting for one (speaker)

GPU queues can take hours to start, so the GPU runs in its **own** job,
queued early, while you work on a CPU node as usual. Kilo's `cfd-local`
moves to the GPU when it starts:

```bash
scripts/hpc-gpu.sh submit        # queue it (defaults: gpu_q, 1 GPU, 4 h; add sbatch options, e.g. -t 8:00:00)
scripts/hpc-gpu.sh status        # PENDING / RUNNING; prints when Ollama is up
scripts/hpc-gpu.sh use           # point cfd-local at the GPU (restart kilo afterwards)
scripts/hpc-gpu.sh cpu           # back to this node's CPU
scripts/hpc-gpu.sh cancel        # release the GPU when done
```

Until the job starts, the CPU node handles everything that does not need
a local model (Loop A with any frontier agent). `use` opens an SSH tunnel
from the CPU node (`localhost:11435`) to Ollama in the GPU job, because
RCC's web proxy intercepts plain HTTP between nodes. The GPU job reads the
same model store in your home directory, so it downloads nothing. If the
CPU job ends, the tunnel goes with it; run `use` again from the new node.
The default job comes from `AOF_GPU_SBATCH` in `workshop/hpc-site.env`.

Checked Oct 2026: `gpu_q` job on an RTX 4500 Ada (24 GB), Kilo `cfd-local`
on an `ame_q` CPU node calling OpenFOAM tools through the tunnel, model
100% on the GPU.

If the GPU job has not started by the time you need it, show the recorded
GPU runs in [`recorded/`](recorded/) instead.

## Cluster notes

- **No `of2412` on the cluster.** Where a doc says `of2412`, prefix the
  command instead: `scripts/with-openfoam.sh blockMesh -help`, or open a
  shell with OpenFOAM loaded: `scripts/with-openfoam.sh bash`.

- **Local models need a GPU.** On CPU the ~18k-token agent prompt alone
  takes many minutes to read (measured: 20+ min on an `ame_q` node), so on
  a CPU node use the frontier loop (A), or `scripts/hpc-gpu.sh` (§4). A
  20–24 GB card (the `gpu_q` A4500 / RTX 4500 Ada nodes) holds
  `gpt-oss:20b`.
- **Threads.** `scripts/local-model.sh` limits Ollama to your job's CPU
  count. Without that it spreads across the whole shared node.
- **Signing in** on a node: Claude Code prints a URL (open it on your
  laptop, paste the code back); Copilot's `/login` and
  `codex login --device-auth` show a code to enter at a URL on your laptop.
- **Solver runs** happen inside your interactive job, on its cores.
- **Where it was checked** (Sept 2026, `ame_q` node): `setup.sh` in HPC
  mode end to end, the shared image running OpenFOAM v2412 including
  `mpirun`, and Kilo connecting all four MCP servers through the image.

## For instructors: the shared store

The OpenFOAM image, Ollama and the model weights ship to the class as one
read-only directory. Stage it once, on a compute node:

```bash
srun -A ame_q -p ame_q -c 16 --mem=64G -t 2:00:00 --pty bash -l
scripts/stage-hpc-shared.sh /gpfs/research/<group>/agentic-openfoam-shared
```

It builds `openfoam-v2412.sif` (455 MB, ~10 min, via
`scripts/build-openfoam-sif.sh`), unpacks Ollama, fetches the five models
above (~70 GB, ~15 min through the proxy), checks every blob's sha256, and
makes it all world-readable. Re-running adds only what is missing; pass
model names to add others
(`scripts/stage-hpc-shared.sh <dir> gemma4:26b`). Point
`workshop/hpc-site.env` at the directory. Attendees' `setup.sh` then
links to it instead of downloading.

The image can also be attached to a GitHub release (set
`AOF_OPENFOAM_SIF_URL`) for clusters that cannot see your storage.
