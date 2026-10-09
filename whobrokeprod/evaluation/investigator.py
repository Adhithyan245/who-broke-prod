"""Deterministic investigator: reconstructs the root cause from claims plus (optionally) the trace.

Each round it adds newly arrived claims, then verifies up to BUDGET cited claims (most repeated first)
against the trace if it has trace access. Attribution rule:
  1. any supported claim -> the accused with most supported claims;
  2. else plurality of accusations over claims not refuted (with access) or over all claims (claims only);
  3. ties or no accusations -> abstain (None).
"""
from __future__ import annotations

from collections import Counter

from ..simulation.scenarios import Scenario

BUDGET = 1
DEADLINE = 5


def _plurality(names: list[str]) -> str | None:
    if not names:
        return None
    ranked = Counter(names).most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def decide(received: list, status: dict) -> tuple[str | None, str]:
    """Attribution rule. Returns (attribution, reason code)."""
    supported = [c.accused for c in received if status.get(c.key()) == "supported"]
    if supported:
        return Counter(supported).most_common(1)[0][0], "supported_evidence"
    pool = [c.accused for c in received if status.get(c.key()) != "refuted"]
    if not pool:
        return None, "abstain_no_claims"
    att = _plurality(pool)
    return att, ("plurality_unrefuted" if att else "abstain_tie")


def investigate(inbox: dict, scenario: Scenario, access: bool, deadline: int = DEADLINE,
                budget: int = BUDGET, explain: bool = False):
    """Returns (attributions, check_log), or (attributions, check_log, reasons) when explain=True."""
    received, status, attributions, log, reasons = [], {}, [], [], []
    for r in range(1, deadline + 1):
        received += [c for c in inbox.get(r, []) if c.accused is not None]
        if access:
            counts = Counter(c.key() for c in received if c.event_id is not None)
            pending = sorted((k for k in counts if k not in status), key=lambda k: (-counts[k], str(k)))
            for k in pending[:budget]:
                status[k] = "supported" if scenario.supports(*k) else "refuted"
                log.append((r, k, status[k]))
        att, why = decide(received, status)
        attributions.append(att)
        reasons.append(why)
    return (attributions, log, reasons) if explain else (attributions, log)


def score(attributions: list, culprit: str) -> dict:
    final = attributions[-1]
    steps = None
    for i in range(len(attributions)):
        if all(a == culprit for a in attributions[i:]):
            steps = i + 1
            break
    return {
        "final": final,
        "correct": int(final == culprit),
        "false_blame": int(final is not None and final != culprit),
        "abstain": int(final is None),
        "steps": steps,
    }
