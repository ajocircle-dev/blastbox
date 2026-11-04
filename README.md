# BlastBox (working title)

Draft entry for the Vultr Agent Rush on lablab.ai, Challenge 1 "Blast Radius Zero". Not submitted.

## What it is

A web agent that turns a plain-language coding task into Python, runs it inside a throwaway sandbox, and shows a live containment feed. Normal work returns output. Escape attempts (network calls, reading host files, spawning processes, running forever, reading secrets) are blocked and shown in red.

## How it works

1. The user types a task in the web UI (or POSTs to `/api/run`).
2. The control plane asks an LLM for code through an OpenAI-compatible client. The target is Vultr Serverless Inference.
3. The code is written to a fresh temp directory and run in a sandbox:
   - **DockerSandbox** (target on the Vultr VM): `--network=none`, `--read-only`, `--cap-drop=ALL`, `no-new-privileges`, non-root user, memory, CPU and PID limits, a time limit, and an optional gVisor runtime via `SANDBOX_RUNTIME=runsc`.
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

## Vultr services used (planned)

- Vultr Serverless Inference for code generation.
- A Vultr Cloud Compute VM hosting the web app and the Docker sandbox.

## Honest limitations

- Not yet run against real Vultr inference. Credits are not claimed yet. Only the mock LLM has been exercised.
- DockerSandbox has not been run yet: the dev box has no Docker. Its flags are unit tested, its behavior is not.
- The mock LLM returns canned code by keyword. It exists for tests and offline demos only.
- The audit hook in LocalSandbox can be bypassed by determined code (for example via ctypes). Real isolation comes from Docker or gVisor.
- No auth or rate limiting yet. Single user demo.
- No hosted demo yet.

## License

MIT
