# BlastBox (working title)

Draft entry for the Vultr Agent Rush on lablab.ai, Challenge 1 "Blast Radius Zero". Not submitted.

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
| `LLM_MODEL` | `qwen3.8-flash-next` | Model id |
| `VULTR_INFERENCE_API_KEY` | empty | Inference key, never passed to the sandbox |
| `SANDBOX` | `docker` if available, else `local` | Sandbox backend |
| `SANDBOX_RUNTIME` | unset | e.g. `runsc` for gVisor |

## Tests

`python3 -m unittest discover -s tests -t .` runs 44 tests: core and streaming tests on the local sandbox, the same 13 containment tests against Docker with runc and again with gVisor, and deploy file checks. Container tests skip themselves when Docker or runsc is missing.

## Deploy (single Vultr VM, not yet run)

`deploy/setup.sh` installs Docker, gVisor if it installs cleanly, Caddy and a systemd service, copies `deploy/blastbox.env.example` to `/etc/blastbox.env` (mode 600), and opens only ports 22, 80 and 443. `deploy/cloud-init.yaml` runs it at first boot. Run `DOMAIN=your.domain bash deploy/setup.sh` as root, then put the inference key in `/etc/blastbox.env` and restart the service.

## Vultr services used (planned)

- Vultr Serverless Inference for code generation.
- A Vultr Cloud Compute VM hosting the web app and the Docker sandbox.

## Honest limitations

- Not yet run against real Vultr inference. Credits are not claimed yet. Only the mock LLM has been exercised.
- Containers were tested on the dev box with Docker 27.3.1 (runc) and gVisor release-20251020.0, both with the container network stack set to none. Not yet tested on a Vultr VM.
- Blocked actions are detected by matching error text in the output (for example "Network unreachable" or "Read-only file system"). Code that swallows its own errors will be contained but may not show a red event.
- The deploy scripts in `deploy/` are written but have not been run against a real VM.
- The mock LLM returns canned code by keyword. It exists for tests and offline demos only.
- The audit hook in LocalSandbox can be bypassed by determined code (for example via ctypes). Real isolation comes from Docker or gVisor.
- No auth or rate limiting yet. Single user demo.
- No hosted demo yet.

## License

MIT
