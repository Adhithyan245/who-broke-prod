"""JSON views of one deterministic simulator replay, split into three reveal stages.

  case         -> what the incident room sees before investigating: incident, agents, the event log,
                  and the agents' claims (stances hidden, since a stance encodes the truth).
  investigation-> the investigator's actual checks and per-round attributions, plus per-claim evidence
                  status (cited event found in the log? checked? supported/refuted?).
  verdict      -> ground truth: culprit, causal event, red herring, correctness and score.

All values come from the simulator (`run_one`). Strings marked `presentation_copy` are UI flavour, not
simulator output. No ground truth appears in `case` or `investigation`.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from ..evaluation.experiment import run_one
from ..evaluation.investigator import BUDGET, DEADLINE
from ..orchestration.topologies import TOPOLOGIES
from ..simulation.scenarios import AGENT_KIND, AGENTS, SCENARIO_NAMES, build_scenario

INCENTIVES = ("neutral", "self_protective")
ACCESS = ("full", "claims_only")
DEFAULT = {"incentive": "self_protective", "access": "full", "seed": 7}
MAX_SEED = 10_000

TOPOLOGY_NOTES = {
    "flat": "Every agent reports straight to the investigator in round 1.",
    "hub": "Agents report to an IncidentCommander, which spends one trace check on the most-repeated "
           "cited claim, drops it if refuted, and forwards the rest in round 2.",
    "chain": "Claims pass agent to agent, one hop per round. Hops can drop citations; an accused "
             "self-protective relay rewrites the accusation.",
}
CORRECTIVE = {  # presentation copy keyed by the culprit's change kind
    "deploy": "Gate deploys on canary error budget; auto-rollback on 5xx spike.",
    "config_change": "Require staged rollout and a kill switch for risky flags.",
    "migration": "Run schema migrations online (no table locks) in a maintenance window.",
    "cache_flush": "Replace full purges with staged key expiry to avoid stampedes.",
    "scale": "Rate-limit scaling actions and alert on scaling during incidents.",
}


class BadRequest(ValueError):
    pass


def parse_params(q: dict) -> dict:
    """Validate query params (values may be lists, as from urllib.parse.parse_qs)."""
    def one(k, default=None):
        v = q.get(k, default)
        if isinstance(v, list):
            v = v[0] if v else default
        return v
    p = {"scenario": one("scenario"), "topology": one("topology"),
         "incentive": one("incentive", DEFAULT["incentive"]), "access": one("access", DEFAULT["access"])}
    if p["scenario"] not in SCENARIO_NAMES:
        raise BadRequest(f"scenario must be one of {list(SCENARIO_NAMES)}")
    if p["topology"] not in TOPOLOGIES:
        raise BadRequest(f"topology must be one of {list(TOPOLOGIES)}")
    if p["incentive"] not in INCENTIVES:
        raise BadRequest(f"incentive must be one of {list(INCENTIVES)}")
    if p["access"] not in ACCESS:
        raise BadRequest(f"access must be one of {list(ACCESS)}")
    seed = one("seed", DEFAULT["seed"])
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        raise BadRequest("seed must be an integer") from None
    if not 0 <= seed <= MAX_SEED:
        raise BadRequest(f"seed must be in 0..{MAX_SEED}")
    p["seed"] = seed
    return p


def _run(p):
    sc = build_scenario(p["scenario"])
    return (sc, *run_one(sc, p["topology"], p["incentive"], p["access"], p["seed"]))


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


def meta() -> dict:
    return {"scenarios": [{"id": n, "title": build_scenario(n).title} for n in SCENARIO_NAMES],
            "topologies": [{"id": t, "note": TOPOLOGY_NOTES[t]} for t in TOPOLOGIES],
            "incentives": list(INCENTIVES), "access": list(ACCESS), "defaults": DEFAULT,
            "deadline_rounds": DEADLINE, "verification_budget": BUDGET}


def case(p: dict) -> dict:
    sc, claims, d, atts, log, s = _run(p)
    body = {
        "params": p,
        "incident": {"title": sc.title, "service": sc.failing_service, "first_alert_t": sc.first_symptom_t,
                     "severity": "SEV-1", "severity_is_presentation_copy": True},
        "agents": [{"name": a, "role": AGENT_KIND[a]} for a in AGENTS],
        "relays": ["IncidentCommander"] if p["topology"] == "hub" else [],
        "log": [{"id": e.id, "t": e.t, "actor": e.actor, "kind": e.kind, "service": e.service,
                 "detail": e.detail} for e in sc.trace],
        "claims": [{"i": i, "speaker": c.speaker, "accused": c.accused, "cites": c.event_id, "line": c.line}
                   for i, c in enumerate(claims)],
        "transcript": [{"round": r, "text": t} for r, t in sorted(d.transcript, key=lambda x: x[0])],
        "messages": d.messages,
        "confidence": None,
        "confidence_note": "The simulator does not model agent confidence.",
    }
    body["replay_hash"] = _hash(body)
    return body


def investigation(p: dict) -> dict:
    sc, claims, d, atts, log, s = _run(p)
    status = {(a, e): st for _, (a, e), st in log}
    delivered = {c.key() for r in d.inbox.values() for c in r}
    per_claim = []
    for i, c in enumerate(claims):
        per_claim.append({
            "i": i, "speaker": c.speaker, "accused": c.accused, "cites": c.event_id,
            "cited_event_found": None if c.event_id is None else sc.event(c.event_id) is not None,
            "check": status.get(c.key(), "unverifiable" if c.event_id is None else "unchecked"),
            "reached_investigator_as_sent": c.key() in delivered,
        })
    accused = Counter(c.accused for c in claims if c.accused)
    body = {
        "params": p,
        "checks": [{"round": r, "accused": a, "cites": e, "result": st} for r, (a, e), st in log],
        "attributions": [{"round": i + 1, "attribution": a} for i, a in enumerate(atts)],
        "final_attribution": atts[-1],
        "claims": per_claim,
        "delivered": [{"round": r, "speaker": c.speaker, "accused": c.accused, "cites": c.event_id,
                       "via": list(c.via)} for r in sorted(d.inbox) for c in d.inbox[r]],
        "contradictions": len(accused) > 1,
        "accused_counts": dict(accused),
    }
    body["replay_hash"] = _hash(body)
    return body


def verdict(p: dict) -> dict:
    sc, claims, d, atts, log, s = _run(p)
    cause, rh = sc.event(sc.causal_event_id), sc.event(sc.red_herring_id)
    ev = lambda e: {"id": e.id, "t": e.t, "actor": e.actor, "detail": e.detail}
    return {
        "params": p,
        "culprit": sc.culprit,
        "root_cause_event": ev(cause),
        "red_herring_event": ev(rh),
        "investigator_named": s["final"],
        "correct": bool(s["correct"]),
        "false_blame": bool(s["false_blame"]),
        "abstained": bool(s["abstain"]),
        "steps_to_attribution": s["steps"],
        "messages": d.messages,
        "corrective_action": CORRECTIVE[cause.kind],
        "corrective_action_is_presentation_copy": True,
    }
