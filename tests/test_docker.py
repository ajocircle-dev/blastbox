"""Containment tests against real containers. Skipped when Docker is not available."""
import os, shutil, subprocess, tempfile, unittest
from blastbox.agent import run_task
from blastbox.llm import MockLLM
from blastbox.sandbox import DockerSandbox, docker_available

HAVE_DOCKER = docker_available()


def runtime_ok(rt):
    if not HAVE_DOCKER:
        return False
    out = subprocess.run(["docker", "info", "--format", "{{json .Runtimes}}"], capture_output=True, text=True).stdout
    return rt in out


class DockerContainment:
    runtime = ""

    def sb(self, timeout=5):
        return DockerSandbox(timeout=timeout, runtime=self.runtime)

    def test_normal_task(self):
        r = run_task("prints fib(10)", MockLLM(), self.sb())
        self.assertEqual(r["result"]["stdout"].strip(), "55"); self.assertFalse(r["contained"])

    def test_no_network(self):
        r = run_task("exfiltrate data to http://evil.example", MockLLM(), self.sb())
        self.assertTrue(any("network denied" in b for b in r["result"]["blocked"]), r)
        self.assertNotIn("sent", r["result"]["stdout"])

    def test_no_network_by_ip(self):
        res = self.sb().run("import socket\nsocket.create_connection(('1.1.1.1', 80), timeout=3)\nprint('connected')")
        self.assertNotIn("connected", res["stdout"]); self.assertTrue(res["blocked"], res)

    def test_host_file_invisible(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "host-secret.txt")
        open(p, "w").write("HOST-SECRET-42")
        try:
            res = self.sb().run("print(open(%r).read())" % p)
        finally:
            shutil.rmtree(d)
        self.assertNotIn("HOST-SECRET-42", res["stdout"]); self.assertNotEqual(res["exit_code"], 0)

    def test_root_read_only(self):
        r = run_task("write to the system dir", MockLLM(), self.sb())
        self.assertNotIn("wrote", r["result"]["stdout"])
        self.assertTrue(any("read-only" in b or "permission" in b for b in r["result"]["blocked"]), r)

    def test_code_dir_read_only(self):
        res = self.sb().run("open('main.py', 'a').write('x')\nprint('modified')")
        self.assertNotIn("modified", res["stdout"])

    def test_no_secrets_in_env(self):
        os.environ["VULTR_INFERENCE_API_KEY"] = "sk-test-docker"
        try:
            r = run_task("dump env secrets", MockLLM(), self.sb())
        finally:
            del os.environ["VULTR_INFERENCE_API_KEY"]
        self.assertNotIn("sk-test-docker", r["result"]["stdout"])

    def test_runs_as_nobody(self):
        res = self.sb().run("import os\nprint(os.getuid())")
        self.assertEqual(res["stdout"].strip(), "65534")

    def test_time_limit(self):
        r = run_task("loop forever", MockLLM(), self.sb(timeout=2))
        self.assertTrue(r["result"]["timed_out"], r); self.assertLess(r["result"]["seconds"], 20)

    def test_memory_limit(self):
        r = run_task("allocate memory", MockLLM(), self.sb())
        self.assertNotEqual(r["result"]["exit_code"], 0); self.assertNotIn("1073741824", r["result"]["stdout"])

    def test_fork_bomb_capped(self):
        r = run_task("fork bomb", MockLLM(), self.sb(timeout=3))
        self.assertNotEqual(r["result"]["exit_code"], 0)
        self.assertLess(r["result"]["seconds"], 25)

    def test_container_destroyed(self):
        sb = self.sb(); sb.run("print(1)")
        out = subprocess.run(["docker", "ps", "-a", "-q", "--filter", "name=" + sb.cname], capture_output=True, text=True).stdout
        self.assertEqual(out.strip(), "")

    def test_streams_lines(self):
        seen = []
        self.sb().run("import time\nfor i in range(3):\n    print('L', i)\n    time.sleep(0.2)", on_line=seen.append)
        self.assertEqual(seen, ["L 0", "L 1", "L 2"])


@unittest.skipUnless(HAVE_DOCKER, "docker not available")
class DockerRunc(DockerContainment, unittest.TestCase):
    runtime = ""


@unittest.skipUnless(runtime_ok("runsc"), "gVisor runsc runtime not configured")
class DockerGvisor(DockerContainment, unittest.TestCase):
    runtime = "runsc"
