"""Typed request/response contracts shared by the API, the static bundle and the CLI."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .orchestration.topologies import TOPOLOGIES
from .simulation.scenarios import SCENARIO_NAMES

INCENTIVES = ("neutral", "self_protective")
ACCESS = ("full", "claims_only")
DEFAULT_INCENTIVE, DEFAULT_ACCESS, DEFAULT_SEED = "self_protective", "full", 7
MAX_SEED = 10_000
EXPORT_FORMATS = ("json", "csv")


class ValidationError(ValueError):
    def __init__(self, field_name: str, message: str):
        super().__init__(message)
        self.field = field_name
        self.message = message


def _one(q: dict, key: str, default=None):
    v = q.get(key, default)
    if isinstance(v, list):
        v = v[0] if v else default
    return v


@dataclass(frozen=True)
class ReplayParams:
    scenario: str
    topology: str
    incentive: str = DEFAULT_INCENTIVE
    access: str = DEFAULT_ACCESS
    seed: int = DEFAULT_SEED

    @classmethod
    def from_query(cls, q: dict) -> ReplayParams:
        """Validate query params; values may be lists (as from urllib.parse.parse_qs)."""
        allowed = {"scenario", "topology", "incentive", "access", "seed"}
        unknown = sorted(set(q) - allowed)
        if unknown:
            raise ValidationError(unknown[0], f"unknown parameter {unknown[0]!r}")
        choices = {"scenario": SCENARIO_NAMES, "topology": TOPOLOGIES, "incentive": INCENTIVES, "access": ACCESS}
        defaults = {"incentive": DEFAULT_INCENTIVE, "access": DEFAULT_ACCESS}
        vals = {}
        for k, opts in choices.items():
            v = _one(q, k, defaults.get(k))
            if v not in opts:
                raise ValidationError(k, f"{k} must be one of {list(opts)}")
            vals[k] = v
        raw = _one(q, "seed", DEFAULT_SEED)
        try:
            seed = int(raw)
        except (TypeError, ValueError):
            raise ValidationError("seed", "seed must be an integer") from None
        if not 0 <= seed <= MAX_SEED:
            raise ValidationError("seed", f"seed must be in 0..{MAX_SEED}")
        return cls(seed=seed, **vals)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ApiError:
    code: str
    message: str
    status: int
    field: str | None = None
    request_id: str | None = None

    def body(self) -> dict:
        err = {"code": self.code, "message": self.message}
        if self.field:
            err["field"] = self.field
        return {"error": err, "request_id": self.request_id}


@dataclass
class Health:
    status: str = "ok"
    version: str = "0.2.0"
    checks: dict = field(default_factory=dict)
