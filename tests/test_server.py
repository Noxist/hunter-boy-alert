import json
import importlib.util
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
reset_spec = importlib.util.spec_from_file_location("reset_cooldown", Path(__file__).resolve().parents[1] / "reset-cooldown.py")
reset_cooldown = importlib.util.module_from_spec(reset_spec)
reset_spec.loader.exec_module(reset_cooldown)


class Response:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self, *_): return b""


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        server.DB_PATH = root / "state.sqlite3"
        server.WEBHOOK_FILE = root / "url"
        server.WEBHOOK_PREFIX = "http://192.0.2.1:8123/api/webhook/"
        server.WEBHOOK_FILE.write_text("http://192.0.2.1:8123/api/webhook/test-secret\n")
        server.connect().close()
        self.webhook_calls = 0
        self.call_lock = threading.Lock()
        def opener(*_args, **_kwargs):
            with self.call_lock:
                self.webhook_calls += 1
            return Response()
        self.patcher = patch.object(server, "urlopen", opener)
        self.patcher.start()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.patcher.stop()
        self.temp.cleanup()

    def post(self):
        req = Request(self.base + "/api/activate", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read())
        except Exception as exc:
            return exc.code, json.loads(exc.read())

    def test_missing_or_mismatched_origin_fails_closed(self):
        for prefix in ('', 'http://192.0.2.2:8123/api/webhook/'):
            with patch.object(server, 'WEBHOOK_PREFIX', prefix):
                self.assertEqual(self.post()[0], 500)
                self.assertEqual(self.webhook_calls, 0)
                self.assertEqual(server.remaining(), 0)

    def test_get_never_triggers(self):
        with urlopen(self.base + "/") as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"Wake Leandro Up", response.read())
        with urlopen(self.base + "/api/status") as response:
            self.assertEqual(json.loads(response.read())["remaining_seconds"], 0)
        self.assertEqual(self.webhook_calls, 0)

    def test_concurrent_requests_are_serialized_and_cooldown_persists(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.post())) for _ in range(12)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sum(status == 200 for status, _ in results), 1)
        self.assertEqual(sum(status == 429 for status, _ in results), 11)
        self.assertEqual(self.webhook_calls, 1)
        self.assertTrue(all(body.get("remaining_seconds", 0) > 0 for status, body in results if status == 429))
        # Reopening the same SQLite file represents a process/container restart.
        server.connect().close()
        self.assertGreater(server.remaining(), 0)

    def test_failed_delivery_does_not_start_cooldown(self):
        failed = Response()
        failed.status = 503
        with patch.object(server, "urlopen", lambda *_a, **_k: failed):
            status, body = self.post()
        self.assertEqual(status, 502)
        self.assertIn("error", body)
        self.assertEqual(server.remaining(), 0)

    def test_operator_reset_allows_next_activation_without_triggering(self):
        self.assertEqual(self.post()[0], 200)
        self.assertGreater(server.remaining(), 0)
        self.assertEqual(reset_cooldown.reset(server.DB_PATH), 1)
        self.assertEqual(server.remaining(), 0)
        self.assertEqual(self.webhook_calls, 1)
        self.assertEqual(self.post()[0], 200)
        self.assertEqual(self.webhook_calls, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
