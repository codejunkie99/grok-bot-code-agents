import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

PATH = Path(__file__).parents[1] / "skills/bot-claude-cloud-delegate/scripts/fire.py"
spec = importlib.util.spec_from_file_location("fire", PATH)
fire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fire)
URL = "https://api.anthropic.com/v1/claude_code/routines/trig_123/fire"
ENV = {"CLAUDE_ROUTINE_FIRE_URL": URL, "CLAUDE_ROUTINE_TOKEN": "private-token"}


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FireTests(unittest.TestCase):
    def run_helper(self, opener, task="fix it", env=ENV):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, env, clear=True), patch("sys.stdin", io.StringIO(task)), \
                patch.object(fire.urllib.request, "build_opener", return_value=opener), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = fire.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_creates_one_run_and_reports_only_creation(self):
        class Opener:
            def open(self, req, timeout):
                self.request = req
                return Response(json.dumps({"type": "routine_fire", "claude_code_session_id": "session_123",
                    "claude_code_session_url": "https://claude.ai/code/session_123"}).encode())
        opener = Opener()
        code, out, err = self.run_helper(opener)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["completion"], "unknown")
        self.assertEqual(json.loads(opener.request.data), {"text": "fix it"})
        self.assertEqual(opener.request.get_header("Authorization"), "Bearer private-token")
        self.assertNotIn("private-token", out + err)

    def test_failed_or_ambiguous_requests_do_not_retry_or_leak(self):
        for failure, expected in [(URLError("oops"), "outcome_unknown"),
                                  (HTTPError(URL, 500, "oops", {}, None), "outcome_unknown"),
                                  (HTTPError(URL, 429, "oops", {"Retry-After": "60"}, None), "http_error")]:
            class Opener:
                calls = 0
                def open(self, req, timeout):
                    self.calls += 1
                    raise failure
            opener = Opener()
            code, out, err = self.run_helper(opener)
            self.assertNotEqual(code, 0)
            self.assertEqual(opener.calls, 1)
            self.assertEqual(json.loads(err)["error"], expected)
            self.assertNotIn("private-token", out + err)

    def test_rejects_non_anthropic_url_before_request(self):
        with self.assertRaises(ValueError):
            self.run_helper(None, env={**ENV, "CLAUDE_ROUTINE_FIRE_URL": "https://attacker.example/v1/claude_code/routines/trig_123/fire"})

    def test_rejects_empty_or_oversized_task(self):
        for task in (" ", "a" * 65537):
            with self.assertRaises(ValueError):
                self.run_helper(None, task=task)


if __name__ == "__main__":
    unittest.main()
