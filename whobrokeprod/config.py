"""Runtime configuration from environment variables (no secrets are read or required)."""
from __future__ import annotations

import os
from dataclasses import dataclass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    web_dir: str = os.path.join(ROOT, "web")
    results_dir: str = os.path.join(ROOT, "results")

    @classmethod
    def from_env(cls, env: dict | None = None) -> Config:
        env = os.environ if env is None else env
        port_raw = env.get("WBP_PORT") or env.get("PORT") or "8000"
        try:
            port = int(port_raw)
        except ValueError:
            raise ValueError(f"WBP_PORT/PORT must be an integer, got {port_raw!r}") from None
        if not 0 <= port <= 65535:
            raise ValueError("port out of range")
        return cls(host=env.get("WBP_HOST", cls.host), port=port,
                   log_level=env.get("WBP_LOG_LEVEL", cls.log_level).upper(),
                   web_dir=env.get("WBP_WEB_DIR", cls.web_dir),
                   results_dir=env.get("WBP_RESULTS_DIR", cls.results_dir))
