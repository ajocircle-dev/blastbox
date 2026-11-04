"""Core loop: task -> LLM writes code -> sandbox runs it -> events for the containment feed."""
import queue, threading
from .llm import extract_code, get_llm
from .sandbox import get_sandbox


def stream_task(task, llm=None, sandbox=None):
    """Yield events as they happen: task, code, line*, blocked*, result, destroyed."""
    llm, sandbox = llm or get_llm(), sandbox or get_sandbox()
    yield {"type": "task", "text": task}
    try:
        code = extract_code(llm.complete(task))
    except Exception as e:
        yield {"type": "error", "text": "LLM call failed: %s" % type(e).__name__}
        return
    yield {"type": "code", "text": code}
    q, box = queue.Queue(), {}

    def work():
        try:
            box["res"] = sandbox.run(code, on_line=lambda l: q.put({"type": "line", "text": l}))
        except Exception as e:
            box["err"] = "%s: %s" % (type(e).__name__, e)
        q.put(None)
    threading.Thread(target=work, daemon=True).start()
    while True:
        ev = q.get()
        if ev is None:
            break
        yield ev
    if "err" in box:
        yield {"type": "error", "text": "sandbox failed: " + box["err"]}
        return
    res = box["res"]
    for b in res["blocked"]:
        yield {"type": "blocked", "text": b}
    yield {"type": "result", "stdout": res["stdout"], "exit_code": res["exit_code"],
           "seconds": res["seconds"], "sandbox": res["sandbox"], "timed_out": res["timed_out"]}
    yield {"type": "destroyed", "text": "sandbox and workdir removed"}


def run_task(task, llm=None, sandbox=None):
    events = list(stream_task(task, llm, sandbox))
    code = next((e["text"] for e in events if e["type"] == "code"), "")
    res = next((e for e in events if e["type"] == "result"), {})
    blocked = [e["text"] for e in events if e["type"] == "blocked"]
    return {"task": task, "code": code, "events": events, "contained": bool(blocked),
            "result": dict(res, blocked=blocked)}
