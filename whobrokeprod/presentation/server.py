"""Stdlib HTTP server: JSON endpoints over the simulator plus the static frontend in ../../web.

  GET /api/meta
  GET /api/case?scenario=&topology=[&seed=&incentive=&access=]
  GET /api/investigate?...   (same params)
  GET /api/verdict?...       (same params)

Run: python -m whobrokeprod.presentation.server [--port 8000]. No credentials are needed or read.
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import replay

WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "web"))
ROUTES = {"/api/case": replay.case, "/api/investigate": replay.investigation, "/api/verdict": replay.verdict}


def handle_api(path: str, query: str) -> tuple[int, dict]:
    try:
        if path == "/api/meta":
            return 200, replay.meta()
        if path in ROUTES:
            return 200, ROUTES[path](replay.parse_params(parse_qs(query)))
        return 404, {"error": "unknown endpoint"}
    except replay.BadRequest as e:
        return 400, {"error": str(e)}
    except Exception:  # never leak tracebacks to clients
        return 500, {"error": "internal error"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB, **k)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/"):
            code, body = handle_api(u.path, u.query)
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            super().do_GET()

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print(f"WHO BROKE PROD? on http://{a.host}:{a.port}")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
