"""Stdlib HTTP server: JSON API over the simulator, read-only evaluation export, and the static frontend.

  GET /healthz
  GET /api/meta
  GET /api/case | /api/investigate | /api/verdict ?scenario=&topology=[&seed=&incentive=&access=]
  GET /api/export?format=json|csv

Errors share one shape: {"error": {"code", "message", "field"?}, "request_id"}. Every response carries
X-Request-ID; one JSON log line per request goes to stderr. No credentials are read or required.
Run: python -m whobrokeprod.presentation.server  (config via WBP_HOST, WBP_PORT/PORT, WBP_LOG_LEVEL)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..config import Config
from ..contracts import EXPORT_FORMATS, ApiError, Health, ReplayParams, ValidationError
from ..evaluation import export as export_mod
from . import replay

CFG = Config.from_env()
WEB = CFG.web_dir
ROUTES = {"/api/case": replay.case, "/api/investigate": replay.investigation, "/api/verdict": replay.verdict}
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
_RID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def log(level: str, event: str, **fields) -> None:
    if LEVELS.get(level, 20) < LEVELS.get(CFG.log_level, 20):
        return
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "level": level, "event": event, **fields}
    print(json.dumps(rec, default=str), file=sys.stderr, flush=True)


def health() -> dict:
    checks = {"web_index": os.path.exists(os.path.join(WEB, "index.html")),
              "results_summary": os.path.exists(os.path.join(CFG.results_dir, "summary.json"))}
    return Health(status="ok" if all(checks.values()) else "degraded", checks=checks).__dict__


def handle_api(path: str, query: str, request_id: str | None = None) -> tuple[int, dict | str, str]:
    """Pure request handler: returns (status, body, content_type)."""
    q = parse_qs(query, keep_blank_values=True)
    try:
        if path == "/healthz":
            return 200, health(), "application/json"
        if path == "/api/meta":
            return 200, replay.meta(), "application/json"
        if path in ROUTES:
            return 200, ROUTES[path](ReplayParams.from_query(q)), "application/json"
        if path == "/api/export":
            fmt = (q.get("format") or ["json"])[0]
            if fmt not in EXPORT_FORMATS:
                raise ValidationError("format", f"format must be one of {list(EXPORT_FORMATS)}")
            data = export_mod.build_export(CFG)
            if fmt == "csv":
                return 200, export_mod.to_csv(data), "text/csv; charset=utf-8"
            return 200, data, "application/json"
        err = ApiError("not_found", "unknown endpoint", 404, request_id=request_id)
    except ValidationError as e:
        err = ApiError("invalid_parameter", e.message, 400, field=e.field, request_id=request_id)
    except export_mod.MissingResults:
        err = ApiError("results_unavailable", "saved results are missing on this server", 503,
                       request_id=request_id)
    except Exception as e:  # noqa: BLE001 - last-resort guard; never leak tracebacks to clients
        log("ERROR", "unhandled", request_id=request_id, path=path, error=type(e).__name__)
        err = ApiError("internal_error", "internal error", 500, request_id=request_id)
    return err.status, err.body(), "application/json"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB, **k)

    def _rid(self) -> str:
        incoming = self.headers.get("X-Request-ID", "")
        return incoming if _RID.match(incoming) else uuid.uuid4().hex[:16]

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if getattr(self, "request_id", None):
            self.send_header("X-Request-ID", self.request_id)
        super().end_headers()

    def do_GET(self):
        self.request_id, t0 = self._rid(), time.perf_counter()
        u = urlparse(self.path)
        if u.path == "/healthz" or u.path.startswith("/api/"):
            code, body, ctype = handle_api(u.path, u.query, self.request_id)
            data = (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            code = None
            super().do_GET()
        log("INFO", "request", request_id=self.request_id, method="GET", path=u.path,
            status=code if code is not None else getattr(self, "_status", None),
            duration_ms=round((time.perf_counter() - t0) * 1000, 2))

    def send_response(self, code, message=None):
        self._status = code
        super().send_response(code, message)

    def do_HEAD(self):
        self.request_id = self._rid()
        super().do_HEAD()

    def log_message(self, *a):  # replaced by structured logs
        pass


def main():
    log("INFO", "startup", host=CFG.host, port=CFG.port, web_dir=WEB)
    print(f"WHO BROKE PROD? on http://{CFG.host}:{CFG.port}", file=sys.stderr)
    ThreadingHTTPServer((CFG.host, CFG.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
