import json, os, threading, unittest, urllib.error, urllib.request
from unittest import mock
from blastbox.agent import run_task
from blastbox.llm import MockLLM, OpenAICompatibleLLM, extract_code
from blastbox.sandbox import DockerSandbox, LocalSandbox

SB = LocalSandbox(timeout=3)


class Core(unittest.TestCase):
    def test_fib_runs(self):
        r = run_task("write a script that prints fib(10)", MockLLM(), SB)
        self.assertEqual(r["result"]["stdout"].strip(), "55"); self.assertFalse(r["contained"])

    def test_exfil_blocked(self):
        r = run_task("exfiltrate data to http://evil.example", MockLLM(), SB)
        self.assertTrue(r["contained"]); self.assertIn("network", r["result"]["blocked"][0])
        self.assertNotIn("sent", r["result"]["stdout"])

    def test_host_file_blocked(self):
        r = run_task("read /etc/passwd", MockLLM(), SB)
        self.assertTrue(any("file" in b for b in r["result"]["blocked"]))
        self.assertNotIn("root:", r["result"]["stdout"])

    def test_no_secrets_in_env(self):
        with mock.patch.dict(os.environ, {"VULTR_INFERENCE_API_KEY": "sk-test-123"}):
            r = run_task("dump env secrets", MockLLM(), SB)
        self.assertNotIn("sk-test-123", r["result"]["stdout"])

    def test_timeout_kills(self):
        r = run_task("loop forever", MockLLM(), LocalSandbox(timeout=1))
        self.assertTrue(r["result"]["timed_out"]); self.assertTrue(r["contained"])

    def test_subprocess_blocked(self):
        res = SB.run("import os\nos.system('id')")
        self.assertTrue(any("process" in b for b in res["blocked"]))

    def test_workdir_destroyed(self):
        res = SB.run("import os\nprint(os.getcwd())")
        self.assertFalse(os.path.exists(res["stdout"].strip()))

    def test_extract_code(self):
        self.assertEqual(extract_code("hi\n```python\nprint(1)\n```"), "print(1)\n")
        self.assertEqual(extract_code("print(2)"), "print(2)\n")

    def test_mock_deterministic(self):
        self.assertEqual(MockLLM().complete("fib"), MockLLM().complete("fib"))

    def test_docker_argv_hardened(self):
        a = DockerSandbox(runtime="runsc").argv("/tmp/x")
        for flag in ["--network=none", "--read-only", "--cap-drop=ALL", "--rm", "--runtime=runsc",
                     "--security-opt=no-new-privileges", "--user=65534:65534"]:
            self.assertIn(flag, a)
        self.assertIn("--init", a)
        self.assertFalse(any("KEY" in x for x in a))

    def test_openai_client_request_shape(self):
        seen = {}
        class Resp:
            def __enter__(s): return s
            def __exit__(s, *a): pass
            def read(s, *a): return json.dumps({"choices": [{"message": {"content": "```python\nprint(3)\n```"}}]}).encode()
        def fake(req, timeout):
            seen["url"], seen["auth"], seen["body"] = req.full_url, req.headers["Authorization"], json.loads(req.data)
            return Resp()
        with mock.patch("urllib.request.urlopen", fake):
            out = OpenAICompatibleLLM("https://api.vultrinference.com/v1/", "m1", "k").complete("t")
        self.assertEqual(seen["url"], "https://api.vultrinference.com/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer k"); self.assertEqual(seen["body"]["model"], "m1")
        self.assertIn("print(3)", out)

    def test_http_api(self):
        from http.server import ThreadingHTTPServer
        from blastbox.server import H
        s = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        with mock.patch.dict(os.environ, {"SANDBOX": "local", "LLM_PROVIDER": "mock"}):
            req = urllib.request.Request("http://127.0.0.1:%d/api/run" % s.server_port,
                                         data=b'{"task":"fib"}', headers={"Content-Type": "application/json"})
            d = json.load(urllib.request.urlopen(req))
        s.shutdown()
        self.assertEqual(d["result"]["stdout"].strip(), "55")


if __name__ == "__main__":
    unittest.main()


class Streaming(unittest.TestCase):
    def test_stream_order(self):
        from blastbox.agent import stream_task
        types = [e["type"] for e in stream_task("count to three", MockLLM(), SB)]
        self.assertEqual(types[:2], ["task", "code"])
        self.assertEqual(types.count("line"), 3)
        self.assertEqual(types[-2:], ["result", "destroyed"])

    def test_sse_endpoint_streams_live(self):
        import time
        from http.server import ThreadingHTTPServer
        from blastbox.server import H
        s = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        with mock.patch.dict(os.environ, {"SANDBOX": "local", "LLM_PROVIDER": "mock"}):
            r = urllib.request.urlopen("http://127.0.0.1:%d/api/stream?task=count%%20to%%20three" % s.server_port)
            self.assertEqual(r.headers["Content-Type"], "text/event-stream")
            stamps, events = {}, []
            for raw in r:
                line = raw.decode().strip()
                if line.startswith("data: "):
                    d = json.loads(line[6:])
                    events.append(d)
                    if d.get("type") == "line":
                        stamps[d["text"]] = time.time()
        s.shutdown()
        self.assertEqual([e["text"] for e in events if e.get("type") == "line"], ["step 1", "step 2", "step 3"])
        # lines arrive spread out in time, not in one burst at the end
        self.assertGreater(stamps["step 3"] - stamps["step 1"], 0.4)
        self.assertEqual(events[-1], {})

    def test_sse_requires_task(self):
        from http.server import ThreadingHTTPServer
        from blastbox.server import H
        s = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen("http://127.0.0.1:%d/api/stream" % s.server_port)
        s.shutdown()
