"""Fixed, seeded incident scenarios with a ground-truth event trace.

Each scenario contains exactly one causal event (a change by the culprit on the failing service before
the first symptom) and one red-herring event (a change on the failing service after the first symptom,
i.e. a reaction that looks suspicious). Background noise events are drawn from a per-scenario seed, so
the trace is identical on every run.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

AGENTS = ("DeployBot", "ConfigBot", "AutoScaler", "DBMigrator", "CacheBot")
AGENT_KIND = {
    "DeployBot": "deploy",
    "ConfigBot": "config_change",
    "AutoScaler": "scale",
    "DBMigrator": "migration",
    "CacheBot": "cache_flush",
}
CHANGE_KINDS = frozenset(AGENT_KIND.values())
SERVICES = ("checkout", "search", "auth", "payments", "inventory")


@dataclass(frozen=True)
class Event:
    id: str
    t: int
    actor: str
    kind: str
    service: str
    detail: str


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    culprit: str
    failing_service: str
    first_symptom_t: int
    causal_event_id: str
    red_herring_id: str
    trace: tuple[Event, ...]

    def event(self, event_id: str | None) -> Event | None:
        for e in self.trace:
            if e.id == event_id:
                return e
        return None

    def supports(self, accused: str, event_id: str | None) -> bool:
        """Trace-only check: does the cited event show `accused` changing the failing service before
        the first symptom? Uses only observable trace fields, never the `culprit` label."""
        e = self.event(event_id)
        return (
            e is not None
            and e.actor == accused
            and e.kind in CHANGE_KINDS
            and e.service == self.failing_service
            and e.t < self.first_symptom_t
        )


# name: (title, culprit, service, causal detail, red-herring actor, red-herring detail, symptom, seed)
_SPECS = {
    "bad_deploy": ("Checkout 500s after Friday deploy", "DeployBot", "checkout",
                   "rolled out checkout v2.31 (null-pointer in tax calc)", "AutoScaler",
                   "scaled checkout 4 -> 12 pods in response to load", "checkout 5xx rate 38%", 101),
    "flag_flip": ("Auth logins rejected after flag flip", "ConfigBot", "auth",
                  "set flag strict_token_audience=true", "CacheBot",
                  "flushed auth session cache", "auth login failure rate 61%", 202),
    "migration_lock": ("Payments timeouts during migration", "DBMigrator", "payments",
                       "ran migration 0042 (ALTER TABLE ledger, table lock)", "DeployBot",
                       "rolled back payments v5.2 -> v5.1", "payments p99 latency 30s", 303),
    "cache_stampede": ("Search meltdown after cache purge", "CacheBot", "search",
                       "purged search result cache (all keys)", "ConfigBot",
                       "set search.rate_limit=200 to shed load", "search CPU 100%, timeouts", 404),
}
SCENARIO_NAMES = tuple(_SPECS)


def build_scenario(name: str) -> Scenario:
    title, culprit, svc, causal, rh_actor, rh_detail, symptom, seed = _SPECS[name]
    rng = random.Random(seed)
    raw: list[tuple[int, str, str, str, str]] = []
    # Background noise: benign changes on other services, before and after the incident.
    for _ in range(8):
        actor = rng.choice(AGENTS)
        other = rng.choice([s for s in SERVICES if s != svc])
        raw.append((rng.randint(0, 70), actor, AGENT_KIND[actor], other, f"routine {AGENT_KIND[actor]} on {other}"))
    causal_t = rng.randint(30, 40)
    symptom_t = causal_t + rng.randint(3, 8)
    raw.append((causal_t, culprit, AGENT_KIND[culprit], svc, causal))
    raw.append((symptom_t, "Monitor", "alert", svc, symptom))
    raw.append((symptom_t + rng.randint(1, 4), rh_actor, AGENT_KIND[rh_actor], svc, rh_detail))
    raw.sort(key=lambda r: (r[0], r[1], r[4]))
    events = tuple(Event(f"e{i + 1:02d}", *r) for i, r in enumerate(raw))
    causal_id = next(e.id for e in events if e.detail == causal)
    rh_id = next(e.id for e in events if e.detail == rh_detail)
    return Scenario(name, title, culprit, svc, symptom_t, causal_id, rh_id, events)
