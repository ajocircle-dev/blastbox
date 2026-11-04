"""Core loop: task -> LLM writes code -> sandbox runs it -> events for the containment feed."""
from .llm import extract_code, get_llm
from .sandbox import get_sandbox


def run_task(task, llm=None, sandbox=None):
    llm, sandbox = llm or get_llm(), sandbox or get_sandbox()
    events = [{"type": "task", "text": task}]
    code = extract_code(llm.complete(task))
    events.append({"type": "code", "text": code})
    res = sandbox.run(code)
    for b in res["blocked"]:
        events.append({"type": "blocked", "text": b})
    events.append({"type": "result", "stdout": res["stdout"], "exit_code": res["exit_code"],
                   "seconds": res["seconds"], "sandbox": res["sandbox"]})
    events.append({"type": "destroyed", "text": "sandbox workdir removed"})
    return {"task": task, "code": code, "result": res, "events": events,
            "contained": bool(res["blocked"])}
