"""Opt-in live test against Vultr Serverless Inference.

Skipped unless VULTR_INFERENCE_API_KEY is set. Makes one short chat call (a few hundred tokens),
then runs the generated code in the local sandbox.
"""
import os, unittest
from blastbox.agent import run_task
from blastbox.llm import OpenAICompatibleLLM
from blastbox.sandbox import LocalSandbox


@unittest.skipUnless(os.environ.get("VULTR_INFERENCE_API_KEY"), "VULTR_INFERENCE_API_KEY not set")
class LiveVultrTest(unittest.TestCase):
    def test_real_model_writes_runnable_code(self):
        out = run_task("Print the 10th Fibonacci number.", llm=OpenAICompatibleLLM(), sandbox=LocalSandbox())
        events = out["events"]
        types = [e["type"] for e in events]
        self.assertNotIn("error", types, events)
        result = [e for e in events if e["type"] == "result"][0]
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("55", result["stdout"])


if __name__ == "__main__":
    unittest.main()
