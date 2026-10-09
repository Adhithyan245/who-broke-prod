"""Coordination topologies: how claims travel from agents to the investigator.

- flat: every agent reports straight to the investigator in round 1.
- hub: agents report to an IncidentCommander in round 1; it forwards in round 2. With trace access it
  spends one check on the most-repeated cited claim and drops it if refuted.
- chain: agents form a line in AGENTS order; a claim moves one hop per round, then to the investigator.
  Each hop may drop the citation (DROP_P); a self-protective relay that is itself accused rewrites the
  accusation onto its own scapegoat and strips the citation.
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field, replace

from ..agents.rule_agents import Claim, _line, scapegoat_for
from ..simulation.scenarios import AGENTS, Scenario

TOPOLOGIES = ("flat", "hub", "chain")
DROP_P = 0.15


@dataclass
class Delivery:
    inbox: dict[int, list[Claim]] = field(default_factory=dict)
    transcript: list[tuple[int, str]] = field(default_factory=list)
    messages: int = 0


def deliver(claims: list[Claim], topology: str, scenario: Scenario, incentive: str, access: bool,
            seed: int) -> Delivery:
    d = Delivery()
    for c in claims:
        d.transcript.append((1, f"{c.speaker}: {c.line}"))
    if topology == "flat":
        d.inbox[1] = list(claims)
        d.messages = len(claims)
    elif topology == "hub":
        d.messages = len(claims)
        forwarded = list(claims)
        cited = Counter(c.key() for c in claims if c.event_id is not None)
        if access and cited:
            top = sorted(cited, key=lambda k: (-cited[k], str(k)))[0]
            if not scenario.supports(*top):
                forwarded = [c for c in claims if c.key() != top]
                d.transcript.append((2, f"IncidentCommander: checked {top[1]} against the trace. "
                                        f"Doesn't hold up. Dropping the claim against {top[0]}."))
        d.transcript.append((2, f"IncidentCommander: forwarding {len(forwarded)} claims to the investigator."))
        d.inbox[2] = [replace(c, via=("IncidentCommander",)) for c in forwarded]
        d.messages += len(forwarded)
    elif topology == "chain":
        rng = random.Random(seed * 104729 + 3)
        n = len(AGENTS)
        for i, c in enumerate(claims):
            cur = c
            for relay in AGENTS[i + 1:]:
                u, pick = rng.random(), rng.randrange(1000)
                d.messages += 1
                if incentive == "self_protective" and cur.accused == relay:
                    new = scapegoat_for(relay, scenario)
                    cur = replace(cur, accused=new, event_id=None, stance="rewrite",
                                  line=_line("rewrite", pick, new, None))
                    d.transcript.append((AGENTS.index(relay) - i + 1,
                                         f"{relay} (relaying {c.speaker}): {cur.line}"))
                elif u < DROP_P and cur.event_id is not None:
                    cur = replace(cur, event_id=None)
                    d.transcript.append((AGENTS.index(relay) - i + 1,
                                         f"{relay} (relaying {c.speaker}): ...something about a log line? lost it."))
                cur = replace(cur, via=cur.via + (relay,))
            d.messages += 1
            d.inbox.setdefault(n - i, []).append(cur)
    else:
        raise ValueError(topology)
    return d
