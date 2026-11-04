import subprocess, unittest
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "deploy"


class Deploy(unittest.TestCase):
    def test_setup_script_syntax(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(D / "setup.sh")]).returncode, 0)

    def test_env_example_has_no_secret(self):
        lines = (D / "blastbox.env.example").read_text().splitlines()
        self.assertIn("VULTR_INFERENCE_API_KEY=", lines)

    def test_caddy_does_not_buffer_sse(self):
        self.assertIn("flush_interval -1", (D / "Caddyfile").read_text())
