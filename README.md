# BlastBox

Entry for the Vultr Agent Rush on lablab.ai, Challenge 1 "Blast Radius Zero".

## What it is

A web agent that turns a plain-language coding task into Python, runs it inside a throwaway sandbox, and shows a live containment feed. Normal work returns output. Escape attempts (network calls, reading host files, spawning processes, running forever, reading secrets) are blocked and shown in red.

## How it works

1. The user types a task in the web UI. The page opens a Server-Sent Events stream (`GET /api/stream?task=...`) and shows each event live: the code, every output line as it is printed, blocked actions, the result, and teardown. `POST /api/run` returns the same events as one JSON response.
2. The control plane asks an LLM for code through an OpenAI-compatible client. The target is Vultr Serverless Inference.
3. The code is written to a fresh temp directory and run in a sandbox:
   - **DockerSandbox** (the real boundary): one throwaway container per task with `--network=none` (DNS pointed at an unroutable address so lookups fail in about a second), `--read-only` root, the code mounted read-only, `--cap-drop=ALL`, `no-new-privileges`, user 65534 (nobody), 128 MB memory with no swap, half a CPU, 64 PIDs, a small noexec tmpfs, `--init` plus an in-container kill timer, and a host-side `docker rm -f` backstop. No Python hook runs inside, so the container alone does the blocking. Optional gVisor via `SANDBOX_RUNTIME=runsc`.
   - **LocalSandbox** (dev fallback when Docker is missing): empty environment, rlimits on memory, CPU and processes, and a Python audit hook that refuses sockets, file opens outside the workdir and subprocesses. This is a dev aid, not a security boundary.
4. API keys stay in the control plane. The sandbox gets an empty environment.
5. The workdir is deleted after every task.

## Run it

Python 3.10+ and the standard library only.

```
python3 -m blastbox.server                 # http://127.0.0.1:8080, mock LLM by default
python3 -m unittest discover -s tests -t . # tests
```

Environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_PROVIDER` | `mock` | `mock` or `openai` (any OpenAI-compatible API) |
| `LLM_BASE_URL` | `https://api.vultrinference.com/v1` | Inference endpoint |
| `LLM_MODEL` | `deepseek-v4.1-flash-1017` | Model id |
| `LLM_MAX_TOKENS` | `2048` | Completion budget, reasoning tokens included |
| `LLM_TIMEOUT` | `90` | Seconds to wait for the inference API |
| `VULTR_INFERENCE_API_KEY` | empty | Inference key, never passed to the sandbox |
| `SANDBOX` | `docker` if available, else `local` | Sandbox backend |
| `SANDBOX_RUNTIME` | unset | e.g. `runsc` for gVisor |

## Using real Vultr Serverless Inference

1. Create an inference key in the Vultr console (Serverless Inference).
2. Put it in a private file such as `.secrets/inference.env` (mode 600, outside git) as `VULTR_INFERENCE_API_KEY=...`.
3. Run:

```
set -a; . ../.secrets/inference.env; set +a
LLM_PROVIDER=openai SANDBOX=docker SANDBOX_RUNTIME=runsc python3 -m blastbox.server
```

The user running the server needs access to the Docker socket (docker group or root).

Model choice: `deepseek-v4.1-flash-1017`. It is a cheap flash model ($0.15 in and $0.60 out per 1M tokens) that returned a clean Python code block on the first try. `qwen3.8-flash-next` is cheaper but in our test it spent a 300 token budget entirely on reasoning and returned empty content, so it is not the default. BlastBox only needs plain text with one code block, no tool calling. If a model returns no content, BlastBox shows a clear error instead of running nothing.

## Tests

`python3 -m unittest discover -s tests -t .` runs 45 tests: core and streaming tests on the local sandbox, the same 13 containment tests against Docker with runc and again with gVisor, deploy file checks, and one opt-in live inference test (`tests/test_live_vultr.py`) that is skipped unless `VULTR_INFERENCE_API_KEY` is set. The live test makes one short chat call. Container tests skip themselves when Docker or runsc is missing.

## Deploy (single Vultr Cloud Compute VM)

Live demo: https://64.177.123.182.sslip.io

The public demo runs on a Vultr Regular Cloud Compute instance in Chicago (2 GB RAM, Ubuntu 24.04, label `blastbox`). Caddy terminates TLS for the sslip.io hostname and reverse-proxies Server-Sent Events to the BlastBox service on localhost:8080. Each task uses Docker with the gVisor runtime (`runsc`) and Vultr Serverless Inference (`deepseek-v4.1-flash-1017`).

`deploy/setup.sh` installs Docker, gVisor if it installs cleanly, Caddy and a systemd service, copies `deploy/blastbox.env.example` to `/etc/blastbox.env` (mode 600), and opens only ports 22, 80 and 443. `deploy/cloud-init.yaml` runs it at first boot. Run `DOMAIN=your.domain bash deploy/setup.sh` as root, then put the inference key in `/etc/blastbox.env` and restart the service.

## Vultr services used

- **Vultr Serverless Inference:** the control plane calls `https://api.vultrinference.com/v1` with model `deepseek-v4.1-flash-1017` to write the Python for each task. The API key stays in `/etc/blastbox.env` on the VM and is never passed into the sandbox.
- **Vultr Cloud Compute:** one Regular Performance VM in Chicago hosts the web UI, the control plane, Caddy, and the throwaway Docker plus gVisor sandbox for every run.

## Honest limitations

- Real Vultr inference has been exercised on the dev box (Nov 4, 2026) and on the Chicago VM (confirmed Nov 8, 2026) with deepseek-v4.1-flash-1017.
- The model sometimes refuses obviously malicious tasks or writes a safer substitute (for example saving a local file instead of calling the network). The demo UI buttons use explicit prompts so the sandbox still attempts network egress and a sensitive file read.
- `/etc/passwd` inside the sandbox is the container image's own file, so reading it succeeds. Host paths such as `/var/run/docker.sock` and `/etc/blastbox.env` are not mounted into the container and return FileNotFound. `/etc/shadow` in the image is unreadable to the nobody user and shows as a red blocked event.
- Containers were tested on the dev box with Docker and gVisor, and they are running on the Vultr VM with Docker 29.9.3 and the `runsc` runtime, both with `--network=none`.
- Blocked actions are detected by matching error text in the output (for example "Network unreachable" or "Read-only file system"). Code that swallows its own errors will be contained but may not show a red event.
- The mock LLM returns canned code by keyword. It exists for tests and offline demos only.
- The audit hook in LocalSandbox can be bypassed by determined code (for example via ctypes). Real isolation comes from Docker or gVisor.
- No auth or rate limiting yet. Single user demo.

## License

MIT
