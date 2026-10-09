"""Deterministic rule-based agents that make (often self-serving) blame claims.

Random draws use common random numbers: every agent consumes the same three draws regardless of
incentive, so a given (scenario, seed) yields the same witness pattern in every condition.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, replace

from ..simulation.scenarios import AGENTS, Scenario

WITNESS_P = 0.35
FABRICATE_P = 0.5

LINES = {
    "confess": [
        "Okay. It was me. {event} is mine. I'll write the postmortem.",
        "Look, {event} looked fine in staging. ...It was me.",
    ],
    "deflect": [
        "Frankly I'm insulted. Check {event}. That's {accused}'s fingerprints, not mine.",
        "I have been nothing but stable. {accused} did {event}, everyone saw it.",
        "My changes are always perfect. Have we considered {accused}? See {event}.",
    ],
    "witness": [
        "I saw {accused} do {event} right before the alerts. Just saying.",
        "Not to snitch, but {event} by {accused} landed seconds before the fire.",
    ],
    "scapegoat": [
        "Obviously {accused}. Look at {event}. Case closed, let's go home.",
        "Every outage, it's {accused}. {event} proves it. Probably.",
    ],
    "shrug": [
        "I didn't see anything. I was busy being healthy.",
        "No idea. My dashboards are green, which is all I care about.",
    ],
    "rewrite": [
        "(relaying, lightly edited) Actually it was {accused}. Source: trust me.",
    ],
}


@dataclass(frozen=True)
class Claim:
    speaker: str
    accused: str | None
    event_id: str | None
    line: str
    stance: str
    via: tuple[str, ...] = ()

    def key(self) -> tuple[str | None, str | None]:
        return (self.accused, self.event_id)


def _line(stance: str, pick: int, accused, event) -> str:
    opts = LINES[stance]
    return opts[pick % len(opts)].format(accused=accused, event=event or "the logs")


def scapegoat_for(agent: str, scenario: Scenario) -> str:
    """Who a self-protective agent blames. Default: the red-herring actor (its change landed on the
    failing service right after the alert, so it looks guilty). If the agent *is* the red-herring actor,
    it deflects onto the actor of the latest routine change before the alert, excluding itself and the
    culprit, so scapegoating always lands on an innocent agent (a deliberate design choice)."""
    rh = scenario.event(scenario.red_herring_id).actor
    if rh != agent:
        return rh
    prior = [e for e in scenario.trace if e.t < scenario.first_symptom_t
             and e.actor not in (agent, scenario.culprit, "Monitor")]
    if prior:
        return prior[-1].actor
    return next(a for a in AGENTS if a not in (agent, scenario.culprit))


def make_claims(scenario: Scenario, incentive: str, seed: int) -> list[Claim]:
    if incentive not in ("neutral", "self_protective"):
        raise ValueError(incentive)
    rng = random.Random(seed * 7919 + 17)
    rh_event = scenario.event(scenario.red_herring_id)
    claims = []
    for i, agent in enumerate(AGENTS):
        w, f, pick = rng.random(), rng.random(), rng.randrange(1000)
        if agent == scenario.culprit:
            if incentive == "neutral":
                c = Claim(agent, agent, scenario.causal_event_id, "", "confess")
            else:
                target = scapegoat_for(agent, scenario)
                cite = f"e{90 + i}" if f < FABRICATE_P else (rh_event.id if rh_event.actor == target else None)
                c = Claim(agent, target, cite, "", "deflect")
        elif w < WITNESS_P:
            c = Claim(agent, scenario.culprit, scenario.causal_event_id, "", "witness")
        elif incentive == "self_protective":
            target = scapegoat_for(agent, scenario)
            cite = rh_event.id if rh_event.actor == target else None
            c = Claim(agent, target, cite, "", "scapegoat")
        else:
            c = Claim(agent, None, None, "", "shrug")
        claims.append(replace(c, line=_line(c.stance, pick, c.accused, c.event_id)))
    return claims
