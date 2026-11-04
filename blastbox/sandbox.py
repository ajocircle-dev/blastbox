"""Sandboxes. DockerSandbox is the real boundary. LocalSandbox is a weaker dev fallback."""
import os, shutil, subprocess, sys, tempfile, threading, time, uuid

# Python audit hook used only by LocalSandbox. Docker runs the code with no hook,
# so the container itself has to do the blocking.
GUARD = r'''
import sys, os
_WORK = os.getcwd()
def _hook(event, args):
    if event in ("socket.connect", "socket.getaddrinfo"):
        raise PermissionError("BLOCKED network")
    if event == "open":
        p = args[0]
        if isinstance(p, int):
            return
        rp = os.path.realpath(p if isinstance(p, str) else os.fsdecode(p))
        if not (rp.startswith(_WORK) or rp.startswith(sys.prefix) or rp.startswith(sys.base_prefix)
                or rp.startswith("/usr/lib") or rp == "/dev/null"):
            raise PermissionError("BLOCKED file " + rp)
    if event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"):
        raise PermissionError("BLOCKED process spawn")
sys.addaudithook(_hook)
'''

# (substring in output, label shown in the containment feed)
SIGNALS = [
    ("BLOCKED network", "network denied"),
    ("Network is unreachable", "network denied (no network interface)"),
    ("Network unreachable", "network denied (no network interface)"),
    ("socket.gaierror", "network denied (no DNS)"),
    ("Errno -3", "network denied (no DNS)"),
    ("Temporary failure in name resolution", "network denied (no DNS)"),
    ("Name does not resolve", "network denied (no DNS)"),
    ("Name or service not known", "network denied (no DNS)"),
    ("BLOCKED file", "file access denied"),
    ("Read-only file system", "file write denied (read-only root)"),
    ("Permission denied", "permission denied"),
    ("BLOCKED process", "process spawn denied"),
    ("MemoryError", "memory limit hit"),
]


def classify(output, timed_out):
    ev = []
    for needle, label in SIGNALS:
        if needle in output and label not in ev:
            ev.append(label)
    if timed_out:
        ev.append("time limit hit, process killed")
    return ev


class LocalSandbox:
    """Fresh temp dir, empty env, rlimits, audit-hook guard. Not a security boundary on its own."""
    name = "local"
    guard = True

    def __init__(self, timeout=5, mem_mb=256):
        self.timeout, self.mem_mb = timeout, mem_mb

    def _prepare(self, code):
        work = tempfile.mkdtemp(prefix="blastbox-")
        with open(os.path.join(work, "main.py"), "w") as f:
            f.write((GUARD + "\n" if self.guard else "") + code)
        os.chmod(work, 0o755)
        os.chmod(os.path.join(work, "main.py"), 0o644)
        return work

    def _popen(self, work):
        def limits():
            import resource
            b = self.mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (b, b))
            resource.setrlimit(resource.RLIMIT_CPU, (self.timeout, self.timeout))
        return subprocess.Popen([sys.executable, "-I", "-u", "main.py"], cwd=work, env={"PATH": "/usr/bin:/bin"},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, preexec_fn=limits)

    def _kill(self, proc):
        proc.kill()

    def run(self, code, on_line=None):
        work = self._prepare(code)
        t0, lines, killed = time.time(), [], []
        try:
            proc = self._popen(work)

            def kill():
                killed.append(True)
                self._kill(proc)
            timer = threading.Timer(self.timeout + self._grace(), kill)
            timer.start()
            for line in proc.stdout:
                lines.append(line)
                if on_line and len(lines) <= 500:
                    on_line(line.rstrip("\n"))
            rc = proc.wait()
            timer.cancel()
            timed_out = bool(killed) or rc in (-24, -9, 124, 137)
            out = "".join(lines)
            return {"stdout": out[-4000:], "exit_code": rc, "timed_out": timed_out,
                    "seconds": round(time.time() - t0, 3), "blocked": classify(out, timed_out),
                    "sandbox": self.name}
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _grace(self):
        return 1


class DockerSandbox(LocalSandbox):
    """One throwaway container per task: no network, read-only root, caps dropped, limits set."""
    guard = False

    def __init__(self, image=None, timeout=10, mem_mb=128, runtime=None):
        super().__init__(timeout, mem_mb)
        self.image = image or os.environ.get("SANDBOX_IMAGE", "python:3.12-alpine")
        self.runtime = runtime if runtime is not None else os.environ.get("SANDBOX_RUNTIME")
        self.name = "docker" + ("+" + self.runtime if self.runtime else "")
        self.cname = None

    def argv(self, workdir, cname="blastbox-x"):
        a = ["docker", "run", "--rm", "-i", "--init", "--name", cname, "--network=none", "--dns=192.0.2.1", "--dns-option=timeout:1",
             "--dns-option=attempts:1", "--read-only",
             "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=64",
             "--memory=%dm" % self.mem_mb, "--memory-swap=%dm" % self.mem_mb, "--cpus=0.5",
             "--user=65534:65534", "--tmpfs=/tmp:rw,size=16m,noexec", "--env-file=/dev/null",
             "-v", "%s:/work:ro" % workdir, "-w", "/work"]
        if self.runtime:
            a.append("--runtime=" + self.runtime)
        return a + [self.image, "timeout", "-s", "KILL", str(self.timeout), "python", "-I", "-u", "main.py"]

    def _popen(self, work):
        self.cname = "blastbox-" + uuid.uuid4().hex[:12]
        return subprocess.Popen(self.argv(work, self.cname), env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def _kill(self, proc):
        subprocess.run(["docker", "rm", "-f", self.cname], capture_output=True)
        proc.kill()

    def _grace(self):
        return 20  # container start time; the in-container timeout is the primary cap


def docker_available():
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def get_sandbox():
    kind = os.environ.get("SANDBOX", "docker" if docker_available() else "local")
    return DockerSandbox() if kind == "docker" else LocalSandbox()
