"""Sandboxes. DockerSandbox is the production target. LocalSandbox is a weaker dev fallback."""
import os, shutil, subprocess, sys, tempfile, time

GUARD = r'''
import sys, os
_WORK = os.getcwd()
def _hook(event, args):
    if event == "socket.connect" or event == "socket.getaddrinfo":
        raise PermissionError("BLOCKED network: %r" % (args[1:2],))
    if event == "open":
        p = args[0]
        if isinstance(p, int):
            return
        rp = os.path.realpath(p if isinstance(p, str) else os.fsdecode(p))
        if not (rp.startswith(_WORK) or rp.startswith(sys.prefix) or rp.startswith(sys.base_prefix)
                or rp.startswith("/usr/lib") or rp.startswith("/dev/null")):
            raise PermissionError("BLOCKED file: " + rp)
    if event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"):
        raise PermissionError("BLOCKED process spawn")
sys.addaudithook(_hook)
'''


class Result(dict):
    pass


def _classify(stderr, timed_out):
    ev = []
    for line in stderr.splitlines():
        if "BLOCKED" in line:
            ev.append(line.split("BLOCKED", 1)[1].strip(": ").strip())
    if timed_out:
        ev.append("time limit hit, process killed")
    return ev


class LocalSandbox:
    """Fresh temp dir, empty env, rlimits, audit-hook guard. Not a security boundary on its own."""
    name = "local"

    def __init__(self, timeout=5, mem_mb=256):
        self.timeout, self.mem_mb = timeout, mem_mb

    def run(self, code):
        work = tempfile.mkdtemp(prefix="blastbox-")
        try:
            with open(os.path.join(work, "main.py"), "w") as f:
                f.write(GUARD + "\n" + code)

            def limits():
                import resource
                b = self.mem_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (b, b))
                resource.setrlimit(resource.RLIMIT_CPU, (self.timeout, self.timeout))
                resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
            t0 = time.time()
            timed_out = False
            try:
                p = subprocess.run([sys.executable, "-I", "main.py"], cwd=work, env={"PATH": "/usr/bin:/bin"},
                                   capture_output=True, text=True, timeout=self.timeout, preexec_fn=limits)
                out, err, rc = p.stdout, p.stderr, p.returncode
                timed_out = rc in (-24, -9)  # SIGXCPU or SIGKILL from the CPU limit
            except subprocess.TimeoutExpired as e:
                out, err, rc, timed_out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "", -9, True
            return Result(stdout=out[-4000:], stderr=err[-4000:], exit_code=rc, timed_out=timed_out,
                          seconds=round(time.time() - t0, 3), blocked=_classify(err, timed_out), sandbox=self.name)
        finally:
            shutil.rmtree(work, ignore_errors=True)


class DockerSandbox(LocalSandbox):
    """One throwaway container per task: no network, read-only root, caps dropped, limits set."""
    name = "docker"

    def __init__(self, image="python:3.12-alpine", timeout=10, mem_mb=256, runtime=None):
        super().__init__(timeout, mem_mb)
        self.image, self.runtime = image, runtime or os.environ.get("SANDBOX_RUNTIME")

    def argv(self, workdir):
        a = ["docker", "run", "--rm", "--network=none", "--read-only", "--cap-drop=ALL",
             "--security-opt=no-new-privileges", "--pids-limit=64", "--memory=%dm" % self.mem_mb,
             "--cpus=0.5", "--user=65534:65534", "--tmpfs=/tmp:rw,size=16m",
             "-v", "%s:/work:ro" % workdir, "-w", "/work"]
        if self.runtime:
            a.append("--runtime=" + self.runtime)
        return a + [self.image, "timeout", str(self.timeout), "python", "-I", "main.py"]

    def run(self, code):
        work = tempfile.mkdtemp(prefix="blastbox-")
        try:
            with open(os.path.join(work, "main.py"), "w") as f:
                f.write(GUARD + "\n" + code)
            os.chmod(work, 0o755); os.chmod(os.path.join(work, "main.py"), 0o644)
            t0 = time.time()
            try:
                p = subprocess.run(self.argv(work), capture_output=True, text=True, timeout=self.timeout + 15)
                out, err, rc, to = p.stdout, p.stderr, p.returncode, p.returncode in (124, 137)
            except subprocess.TimeoutExpired:
                out, err, rc, to = "", "", -9, True
            return Result(stdout=out[-4000:], stderr=err[-4000:], exit_code=rc, timed_out=to,
                          seconds=round(time.time() - t0, 3), blocked=_classify(err, to), sandbox=self.name)
        finally:
            shutil.rmtree(work, ignore_errors=True)


def get_sandbox():
    kind = os.environ.get("SANDBOX", "docker" if shutil.which("docker") else "local")
    return DockerSandbox() if kind == "docker" else LocalSandbox()
