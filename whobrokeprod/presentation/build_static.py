"""Write the static fallback bundle into web/data (deterministic; default seed/incentive/access).

  web/data/meta.json, web/data/research.json
  web/data/cases/<scenario>__<topology>.json      {case, investigation}   (no ground truth)
  web/data/verdicts/<scenario>__<topology>.json   verdict, fetched only at verdict time

Limitation: on a static host the verdict files are public URLs, so a curious visitor can open them early.
Run: python -m whobrokeprod.presentation.build_static
"""
from __future__ import annotations

import json
import os

from . import replay
from .server import WEB
from ..orchestration.topologies import TOPOLOGIES
from ..simulation.scenarios import SCENARIO_NAMES

ROOT = os.path.abspath(os.path.join(WEB, ".."))

HYPOTHESES = [  # short labels of HYPOTHESES.md; outcomes come from results/summary.json
    ("H1", "Trace access raises accuracy by >= 0.10 (self-protective agents)",
     "Measured, but partly by design: claims-only investigators cannot verify anything."),
    ("H2", "Trace access at least halves false blame",
     "Measured; magnitude depends on the designer-chosen investigator rule."),
    ("H3", "Blame incentive matters only without trace access",
     "Refuted by a design choice: uncited claims cannot be refuted and still win the fallback vote."),
    ("H4", "Rounds to answer: flat <= hub <= chain",
     "Refuted; chain's mean is selection-biased (averaged over successful runs only)."),
    ("H5", "Chain relaying costs >= 0.10 accuracy vs flat",
     "Measured; driven by designed citation drops (p=0.15) and relay rewrites."),
    ("H6", "A hub mediator gains >= 0.05 accuracy vs flat",
     "Refuted; the mediator's one check duplicates the investigator's first check (design)."),
]
CAVEATS = [
    "Controlled simulator with scripted agents and four hand-built scenarios.",
    "Says nothing about real engineering teams, real incidents, or real organisations.",
    "No Phi (integrated information) was computed; no Phi-accuracy relationship is claimed.",
    "Agent dialogue lines are scripted templates chosen by the simulator, not model-generated text.",
]


def research() -> dict:
    with open(os.path.join(ROOT, "results", "summary.json")) as fh:
        s = json.load(fh)
    return {"n_runs": s["n_runs"], "cells": s["cells"], "caveats": CAVEATS,
            "hypotheses": [{"id": h, "claim": c, "supported": s["hypotheses"][h]["supported"],
                            "numbers": {k: v for k, v in s["hypotheses"][h].items() if k != "supported"},
                            "design_note": n} for h, c, n in HYPOTHESES],
            "source": "results/summary.json (preregistered run, not recomputed by the demo)"}


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True)
        fh.write("\n")


def build(out: str = os.path.join(WEB, "data")) -> list[str]:
    written = []
    def w(rel, obj):
        _dump(os.path.join(out, rel), obj)
        written.append(rel)
    w("meta.json", replay.meta())
    w("research.json", research())
    for sc in SCENARIO_NAMES:
        for t in TOPOLOGIES:
            p = replay.parse_params({"scenario": sc, "topology": t})
            w(f"cases/{sc}__{t}.json", {"case": replay.case(p), "investigation": replay.investigation(p)})
            w(f"verdicts/{sc}__{t}.json", replay.verdict(p))
    return written


if __name__ == "__main__":
    print(f"wrote {len(build())} files to web/data")
