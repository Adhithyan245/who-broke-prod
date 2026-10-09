"""Write the static fallback bundle into web/data (deterministic; default seed/incentive/access).

  web/data/meta.json, research.json, export.json
  web/data/raw/runs.csv, raw/summary.json          copies of the saved results (linked from the UI)
  web/data/cases/<scenario>__<topology>.json      {case, investigation}   (no ground truth)
  web/data/verdicts/<scenario>__<topology>.json   verdict, fetched only at verdict time

Limitation: on a static host the verdict files are public URLs, so a curious visitor can open them early.
Run: python -m whobrokeprod.presentation.build_static [--check]
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import sys
import tempfile

from ..config import ROOT, Config
from ..contracts import ReplayParams
from ..evaluation.export import build_export
from ..orchestration.topologies import TOPOLOGIES
from ..simulation.scenarios import SCENARIO_NAMES
from . import replay

WEB = Config().web_dir

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
    "No Phi (integrated information) was computed here; no Phi-accuracy relationship is claimed.",
    "Agent dialogue lines are scripted templates chosen by the simulator, not model-generated text.",
    "No LLM output is used anywhere in the attribution, scoring or results.",
]
METRICS = [  # (name, definition, denominator, status)
    ("Accuracy", "Final attribution (round 5) names the culprit.", "All runs in the cell (n=200 per cell).",
     "computed"),
    ("False-blame rate", "Final attribution names an agent other than the culprit.", "All runs in the cell.",
     "computed"),
    ("Abstain rate", "Final attribution is empty (tie or no usable claims).", "All runs in the cell.", "computed"),
    ("Steps to attribution", "First round from which the attribution stays on the culprit through round 5.",
     "Only runs that reach a stable correct attribution (selection-biased).", "computed"),
    ("Messages", "Claim deliveries counted by the topology, including relays and mediator forwards.",
     "Mean over all runs in the cell.", "computed"),
    ("Wilson 95% interval", "Score interval for the accuracy proportion.", "Cell n.", "computed"),
    ("Sign test p", "Exact two-sided test on paired (scenario, seed) units that differ between conditions.",
     "Discordant pairs only.", "computed"),
    ("Agent confidence", "Not represented in the simulator.", "-", "not modelled"),
    ("SEV-1 label, clock styling, corrective actions", "UI framing for readability.", "-", "illustrative"),
]


def research(export: dict) -> dict:
    s_hyp = export["hypotheses"]
    return {
        "n_runs": export["run_count"], "cells": export["cells"], "per_scenario": export["per_scenario"],
        "caveats": CAVEATS,
        "metrics": [{"name": n, "definition": d, "denominator": den, "status": st} for n, d, den, st in METRICS],
        "hypotheses": [{"id": h, "claim": c, "supported": s_hyp[h]["supported"],
                        "numbers": {k: v for k, v in s_hyp[h].items() if k != "supported"},
                        "design_note": n} for h, c, n in HYPOTHESES],
        "reproducibility": export["reproducibility"],
        "source": "results/summary.json and results/runs.csv (preregistered run, read-only)",
    }


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

    export = build_export(Config())
    w("meta.json", replay.meta())
    w("research.json", research(export))
    w("export.json", export)
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    for name in ("runs.csv", "summary.json"):
        shutil.copyfile(os.path.join(ROOT, "results", name), os.path.join(out, "raw", name))
        written.append(f"raw/{name}")
    for sc in SCENARIO_NAMES:
        for t in TOPOLOGIES:
            p = ReplayParams(scenario=sc, topology=t)
            w(f"cases/{sc}__{t}.json", {"case": replay.case(p), "investigation": replay.investigation(p)})
            w(f"verdicts/{sc}__{t}.json", replay.verdict(p))
    return written


def check(target: str = os.path.join(WEB, "data")) -> list[str]:
    """Return relative paths that are stale or missing compared with a fresh build."""
    with tempfile.TemporaryDirectory() as tmp:
        stale = []
        for rel in build(tmp):
            have = os.path.join(target, rel)
            if not os.path.exists(have) or not filecmp.cmp(have, os.path.join(tmp, rel), shallow=False):
                stale.append(rel)
        return stale


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if web/data is stale")
    a = ap.parse_args(argv)
    if a.check:
        stale = check()
        print("bundle is current" if not stale else "stale: " + ", ".join(stale))
        return 1 if stale else 0
    print(f"wrote {len(build())} files to web/data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
