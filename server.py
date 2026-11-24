#!/usr/bin/env python3
"""Small public trigger with a persistent, globally serialized cooldown."""
import json
import logging
import os
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

COOLDOWN = 30 * 60
DB_PATH = Path(os.environ.get("DATA_DIR", "/data")) / "cooldown.sqlite3"
WEBHOOK_FILE = Path(os.environ.get("WEBHOOK_FILE", "/run/secrets/ha_webhook_url"))
WEBHOOK_PREFIX = os.environ.get("HA_WEBHOOK_PREFIX", "")
WEB_ROOT = Path(__file__).parent / "web"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hunter-boy-alert")


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    db.execute("PRAGMA busy_timeout=20000")
    db.execute("CREATE TABLE IF NOT EXISTS activation (id INTEGER PRIMARY KEY CHECK(id=1), last_success REAL NOT NULL)")
    return db


def remaining(now=None):
    now = time.time() if now is None else now
    db = connect()
    try:
        row = db.execute("SELECT last_success FROM activation WHERE id=1").fetchone()
    finally:
        db.close()
    return max(0, int(row[0] + COOLDOWN - now + 0.999)) if row else 0


class Handler(BaseHTTPRequestHandler):
    server_version = "HunterBoyAlert/1.0"

    def log_message(self, fmt, *args):
        log.info("%s %s", self.command, self.path.split("?", 1)[0])

    def reply(self, status, payload, headers=None):
        data = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, {"healthy": True})
        if self.path == "/api/status":
            wait = remaining()
            return self.reply(200, {"available": wait == 0, "remaining_seconds": wait})
        if self.path not in ("/", "/index.html"):
            return self.reply(404, {"error": "Not found"})
        body = (WEB_ROOT / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/activate":
            return self.reply(404, {"error": "Not found"})
        size = int(self.headers.get("Content-Length", "0"))
        if size > 1024:
            return self.reply(413, {"error": "Request too large"})
        if size:
            self.rfile.read(size)
        db = connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT last_success FROM activation WHERE id=1").fetchone()
            now = time.time()
            wait = max(0, int(row[0] + COOLDOWN - now + 0.999)) if row else 0
            if wait:
                db.execute("ROLLBACK")
                return self.reply(429, {"error": "Please wait before waking Leandro again.", "remaining_seconds": wait}, {"Retry-After": str(wait)})
            webhook = WEBHOOK_FILE.read_text().strip()
            if not WEBHOOK_PREFIX.startswith(("http://", "https://")) or not WEBHOOK_PREFIX.endswith("/api/webhook/") or not webhook.startswith(WEBHOOK_PREFIX):
                raise ValueError("Webhook target is not the verified private Home Assistant endpoint")
            request = Request(webhook, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urlopen(request, timeout=12) as response:
                    status = response.status
                    response.read(1024)
            except HTTPError as exc:
                status = exc.code
            if not 200 <= status < 300:
                db.execute("ROLLBACK")
                log.warning("activation delivery failed status=%d", status)
                return self.reply(502, {"error": "Home Assistant did not accept the alert. Please try again."})
            db.execute("INSERT INTO activation(id,last_success) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET last_success=excluded.last_success", (time.time(),))
            db.execute("COMMIT")
            log.info("activation delivered status=%d", status)
            return self.reply(200, {"success": True, "remaining_seconds": COOLDOWN})
        except (OSError, URLError, TimeoutError) as exc:
            try:
                db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            log.warning("activation delivery unavailable (%s)", type(exc).__name__)
            return self.reply(502, {"error": "Home Assistant is temporarily unavailable. Please try again."})
        except Exception as exc:
            try:
                db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            log.error("activation failed (%s)", type(exc).__name__)
            return self.reply(500, {"error": "The alert could not be sent. Please try again."})
        finally:
            db.close()

    def do_HEAD(self):
        if self.path != "/health":
            return self.reply(404, {"error": "Not found"})
        self.send_response(200)
        self.end_headers()

    def do_OPTIONS(self):
        return self.reply(405, {"error": "Method not allowed"})


if __name__ == "__main__":
    connect().close()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
