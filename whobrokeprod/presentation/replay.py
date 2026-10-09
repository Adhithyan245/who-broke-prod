"""JSON views of one deterministic simulator replay, split into three reveal stages.

  case          what the incident room sees before investigating: incident, agents, the event log and the
                agents' claims (stances hidden, because a stance encodes the truth).
  investigation the investigator's actual checks, per-round attributions with the rule that produced each,
                relayed deliveries, and per-claim evidence status.
  verdict       ground truth: culprit, causal event, red herring, correctness and score.

Every value comes from the simulator (`run_one`/`investigate`). Fields ending in `_is_presentation_copy`
mark UI flavour. No ground truth appears in `case` or `investigation`.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from ..agents.rule_agents import make_claims
from ..contracts import ACCESS, DEFAULT_ACCESS, DEFAULT_INCENTIVE, DEFAULT_SEED, INCENTIVES, ReplayParams
from ..evaluation.investigator import BUDGET, DEADLINE, investigate, score
from ..orchestration.topologies import TOPOLOGIES, deliver
from ..simulation.scenarios import AGENT_KIND, AGENTS, SCENARIO_NAMES, build_scenario

ROLE_TEXT = {
    "deploy": "Ships application releases",
    "config_change": "Flips feature flags and settings",
    "scale": "Adds and removes capacity",
    "migration": "Runs database schema migrations",
    "cache_flush": "Purges and expires caches",
}
TOPOLOGY_NOTES = {
    "flat": "Every agent reports straight to the investigator in round 1.",
    "hub": "Agents report to an IncidentCommander, which spends one trace check on the most-repeated cited "
           "claim, drops it if refuted, and forwards the rest in round 2.",
    "chain": "Claims pass agent to agent, one hop per round. Hops can drop citations; an accused "
             "self-protective relay rewrites the accusation.",
}
REASON_TEXT = {
    "supported_evidence": "A cited log entry was checked against the trace and supports the accusation.",
    "plurality_unrefuted": "No accusation was verified, so the investigator took the most frequent accusation "
                           "among claims not refuted.",
    "abstain_tie": "Accusations among unrefuted claims were tied, so the investigator abstained.",
    "abstain_no_claims": "No usable accusation reached the investigator, so it abstained.",
}
CORRECTIVE = {  # presentation copy keyed by the culprit's change kind
    "deploy": "Gate deploys on canary error budget; auto-rollback on 5xx spike.",
    "config_change": "Require staged rollout and a kill switch for risky flags.",
    "migration": "Run schema migrations online (no table locks) in a maintenance window.",
    "cache_flush": "Replace full purges with staged key expiry to avoid stampedes.",
    "scale": "Rate-limit scaling actions and alert on scaling during incidents.",
}


def topology_graph(topology: str) -> dict:
    """Message-flow diagram (presentation of the routing implemented in orchestration/topologies.py)."""
    nodes = [{"id": a, "kind": "agent"} for a in AGENTS] + [{"id": "Investigator", "kind": "investigator"}]
    if topology == "flat":
        edges = [[a, "Investigator"] for a in AGENTS]
    elif topology == "hub":
        nodes.append({"id": "IncidentCommander", "kind": "mediator"})
        edges = [[a, "IncidentCommander"] for a in AGENTS] + [["IncidentCommander", "Investigator"]]
    else:
        edges = [[AGENTS[i], AGENTS[i + 1]] for i in range(len(AGENTS) - 1)] + [[AGENTS[-1], "Investigator"]]
    return {"nodes": nodes, "edges": edges}


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


def _run(p: ReplayParams):
    sc = build_scenario(p.scenario)
    claims = make_claims(sc, p.incentive, p.seed)
    d = deliver(claims, p.topology, sc, p.incentive, p.access == "full", p.seed)
    atts, log, reasons = investigate(d.inbox, sc, p.access == "full", explain=True)
    return sc, claims, d, atts, log, reasons, score(atts, sc.culprit)


def meta() -> dict:
    return {
        "scenarios": [{"id": n, "title": build_scenario(n).title, "service": build_scenario(n).failing_service}
                      for n in SCENARIO_NAMES],
        "topologies": [{"id": t, "note": TOPOLOGY_NOTES[t], "graph": topology_graph(t)} for t in TOPOLOGIES],
        "incentives": list(INCENTIVES), "access": list(ACCESS),
        "defaults": {"incentive": DEFAULT_INCENTIVE, "access": DEFAULT_ACCESS, "seed": DEFAULT_SEED},
        "deadline_rounds": DEADLINE, "verification_budget": BUDGET,
        "reasons": REASON_TEXT,
    }


def case(p: ReplayParams) -> dict:
    sc, claims, d, *_ = _run(p)
    body = {
        "params": p.to_dict(),
        "incident": {"title": sc.title, "service": sc.failing_service, "first_alert_t": sc.first_symptom_t,
                     "severity": "SEV-1", "severity_is_presentation_copy": True},
        "agents": [{"name": a, "role": AGENT_KIND[a], "role_text": ROLE_TEXT[AGENT_KIND[a]]} for a in AGENTS],
        "relays": ["IncidentCommander"] if p.topology == "hub" else [],
        "graph": topology_graph(p.topology),
        "log": [{"id": e.id, "t": e.t, "actor": e.actor, "kind": e.kind, "service": e.service,
                 "detail": e.detail} for e in sc.trace],
        "claims": [{"i": i, "speaker": c.speaker, "accused": c.accused, "cites": c.event_id, "line": c.line}
                   for i, c in enumerate(claims)],
        "lines_are_scripted_templates": True,
        "transcript": [{"round": r, "text": t} for r, t in sorted(d.transcript, key=lambda x: x[0])],
        "messages": d.messages,
        "confidence": None,
        "confidence_note": "The simulator does not model agent confidence.",
    }
    body["replay_hash"] = _hash(body)
    return body


def investigation(p: ReplayParams) -> dict:
    sc, claims, d, atts, log, reasons, _ = _run(p)
    status = {(a, e): st for _, (a, e), st in log}
    delivered = {c.key() for r in d.inbox.values() for c in r}
    per_claim = [{
        "i": i, "speaker": c.speaker, "accused": c.accused, "cites": c.event_id,
        "cited_event_found": None if c.event_id is None else sc.event(c.event_id) is not None,
        "check": status.get(c.key(), "unverifiable" if c.event_id is None else "unchecked"),
        "reached_investigator_as_sent": c.key() in delivered,
    } for i, c in enumerate(claims)]
    accused = Counter(c.accused for c in claims if c.accused)
    body = {
        "params": p.to_dict(),
        "checks": [{"round": r, "accused": a, "cites": e, "result": st} for r, (a, e), st in log],
        "attributions": [{"round": i + 1, "attribution": a, "reason": why}
                         for i, (a, why) in enumerate(zip(atts, reasons, strict=True))],
        "final_attribution": atts[-1],
        "final_reason": reasons[-1],
        "final_reason_text": REASON_TEXT[reasons[-1]],
        "claims": per_claim,
        "delivered": [{"round": r, "speaker": c.speaker, "accused": c.accused, "cites": c.event_id,
                       "via": list(c.via)} for r in sorted(d.inbox) for c in d.inbox[r]],
        "contradictions": len(accused) > 1,
        "accused_counts": dict(accused),
    }
    body["replay_hash"] = _hash(body)
    return body


def verdict(p: ReplayParams) -> dict:
    sc, _, d, _, _, _, s = _run(p)
    cause, rh = sc.event(sc.causal_event_id), sc.event(sc.red_herring_id)

    def ev(e):
        return {"id": e.id, "t": e.t, "actor": e.actor, "detail": e.detail}

    return {
        "params": p.to_dict(),
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
