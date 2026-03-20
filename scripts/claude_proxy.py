#!/usr/bin/env python3
"""
Claude CLI Proxy — runs on the HOST and exposes a simple HTTP API
so Docker containers can use the local `claude` CLI session (Plan Max).

Usage:
    python3 scripts/claude_proxy.py          # default port 8099
    python3 scripts/claude_proxy.py 8099
"""

import sys
import json
import asyncio
import shutil
from http.server import HTTPServer, BaseHTTPRequestHandler

CLAUDE_BIN = shutil.which("claude") or "claude"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099


class ClaudeProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[proxy] {self.address_string()} {format % args}")

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok", "claude": CLAUDE_BIN})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/query":
            self._json(404, {"error": "not found"})
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
                timeout=300,
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
    server = HTTPServer(("0.0.0.0", PORT), ClaudeProxyHandler)
    print(f"Claude CLI Proxy listening on http://0.0.0.0:{PORT}")
    print(f"Using CLI: {CLAUDE_BIN}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
