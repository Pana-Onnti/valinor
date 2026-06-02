#!/usr/bin/env python3
"""
Claude CLI Proxy — runs on the HOST and exposes a simple HTTP API
so Docker containers can use the local `claude` CLI session (Plan Max).

Usage:
    python3 scripts/claude_proxy.py          # default port 8099
    python3 scripts/claude_proxy.py 8099

Environment overrides (all optional — defaults preserve prior behavior):
    CLAUDE_PROXY_HOST     bind interface (default 0.0.0.0 for Docker->host reach;
                          set to 127.0.0.1 to restrict to loopback)
    CLAUDE_PROXY_TOKEN    if set, /query requires `Authorization: Bearer <token>`
    CLAUDE_PROXY_TIMEOUT  subprocess timeout in seconds (default 960; tuned by VAL-162)
"""

import os
import sys
import json
import asyncio
import shutil
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

CLAUDE_BIN = shutil.which("claude") or "claude"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
HOST = os.getenv("CLAUDE_PROXY_HOST", "0.0.0.0")
AUTH_TOKEN = os.getenv("CLAUDE_PROXY_TOKEN")  # None → auth disabled (unchanged default)
TIMEOUT = int(os.getenv("CLAUDE_PROXY_TIMEOUT", "960"))


class ClaudeProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[proxy] {self.address_string()} {format % args}")

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok", "claude": CLAUDE_BIN})
        else:
            self._json(404, {"error": "not found"})

    def _authorized(self) -> bool:
        """If CLAUDE_PROXY_TOKEN is set, require a matching Bearer token. When it
        is unset (the default), auth is disabled and every request is allowed."""
        if not AUTH_TOKEN:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {AUTH_TOKEN}"

    def do_POST(self):
        if self.path != "/query":
            self._json(404, {"error": "not found"})
            return

        if not self._authorized():
            self._json(403, {"error": "forbidden"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            payload = json.loads(body)
        except Exception:
            self._json(400, {"error": "invalid JSON"})
            return

        prompt = payload.get("prompt", "")
        model = payload.get("model", "claude-sonnet-4-5")

        if not prompt:
            self._json(400, {"error": "prompt required"})
            return

        try:
            import subprocess
            result = subprocess.run(
                [CLAUDE_BIN, "--print", "--model", model],
                input=prompt.encode(),
                capture_output=True,
                timeout=TIMEOUT,
            )
            if result.returncode != 0:
                err = result.stderr.decode().strip()
                self._json(500, {"error": f"claude error: {err}"})
                return
            self._json(200, {"content": result.stdout.decode().strip()})
        except subprocess.TimeoutExpired:
            self._json(504, {"error": "claude CLI timed out"})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _json(self, status: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), ClaudeProxyHandler)
    print(f"Claude CLI Proxy listening on http://{HOST}:{PORT}")
    print(f"Using CLI: {CLAUDE_BIN}")
    print(f"Auth: {'token required' if AUTH_TOKEN else 'disabled (set CLAUDE_PROXY_TOKEN to enable)'}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
