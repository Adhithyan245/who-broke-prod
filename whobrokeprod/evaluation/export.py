"""Read-only evaluation export derived from the saved preregistered run (results/).

Nothing here reruns the experiment. It reads results/runs.csv and results/summary.json, fingerprints them,
re-derives the per-cell table from runs.csv to confirm it matches summary.json, and adds a per-scenario
breakdown computed from the same saved rows.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from statistics import mean

from ..agents import rule_agents
from ..config import ROOT, Config
from ..orchestration.topologies import DROP_P, TOPOLOGIES
from ..simulation.scenarios import SCENARIO_NAMES
from . import investigator

PREREG = [
    {"step": "hypotheses", "commit": "97dc432d9e238fe63622b1ab5393f975780e8ce3"},
    {"step": "code", "commit": "b08a2c34e74d0b956f70d5735ab0bf2983824be2"},
    {"step": "results", "commit": "61ad8b0a43528bb79a2085b042400784e19577a8"},
]
REPO_URL = "https://github.com/Adhithyan245/who-broke-prod"


class MissingResults(FileNotFoundError):
    pass


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_runs(results_dir: str) -> list[dict]:
    path = os.path.join(results_dir, "runs.csv")
    if not os.path.exists(path):
        raise MissingResults(path)
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("seed", "messages", "correct", "false_blame", "abstain"):
            r[k] = int(r[k])
        r["steps"] = int(r["steps"]) if r["steps"] else None
    return rows


def _cell_stats(rows: list[dict]) -> dict:
    st = [r["steps"] for r in rows if r["steps"] is not None]
    n = len(rows)
    return {"n": n, "accuracy": sum(r["correct"] for r in rows) / n,
            "false_blame": sum(r["false_blame"] for r in rows) / n,
            "abstain": sum(r["abstain"] for r in rows) / n,
            "mean_steps": mean(st) if st else None, "n_steps": len(st),
            "mean_messages": mean(r["messages"] for r in rows)}


def build_export(cfg: Config | None = None) -> dict:
    cfg = cfg or Config.from_env()
    rd = cfg.results_dir
    summary_path = os.path.join(rd, "summary.json")
    if not os.path.exists(summary_path):
        raise MissingResults(summary_path)
    with open(summary_path) as fh:
        summary = json.load(fh)
    rows = load_runs(rd)
    mismatches = []
    for c in summary["cells"]:
        sel = [r for r in rows if r["topology"] == c["topology"] and r["incentive"] == c["incentive"]
               and r["access"] == c["access"]]
        got = _cell_stats(sel)
        for k in ("accuracy", "false_blame", "abstain", "mean_steps", "mean_messages"):
            if got[k] != c[k]:
                mismatches.append({"cell": [c["topology"], c["incentive"], c["access"]], "metric": k})
    per_scenario = []
    for sc in SCENARIO_NAMES:
        for t in TOPOLOGIES:
            for inc in ("neutral", "self_protective"):
                for acc in ("full", "claims_only"):
                    sel = [r for r in rows if (r["scenario"], r["topology"], r["incentive"], r["access"])
                           == (sc, t, inc, acc)]
                    per_scenario.append({"scenario": sc, "topology": t, "incentive": inc, "access": acc,
                                         **_cell_stats(sel)})
    hyp_path = os.path.join(ROOT, "HYPOTHESES.md")
    files = {"results/runs.csv": os.path.join(rd, "runs.csv"), "results/summary.json": summary_path}
    if os.path.exists(hyp_path):
        files["HYPOTHESES.md"] = hyp_path
    return {
        "source": "saved preregistered run (read-only; not rerun by this export)",
        "run_count": len(rows),
        "config": {"scenarios": list(SCENARIO_NAMES), "topologies": list(TOPOLOGIES),
                   "incentives": ["neutral", "self_protective"], "access": ["full", "claims_only"],
                   "seeds": {"min": min(r["seed"] for r in rows), "max": max(r["seed"] for r in rows),
                             "count": len({r["seed"] for r in rows})},
                   "witness_p": rule_agents.WITNESS_P, "fabricate_p": rule_agents.FABRICATE_P,
                   "chain_drop_p": DROP_P, "verification_budget": investigator.BUDGET,
                   "deadline_rounds": investigator.DEADLINE},
        "reproducibility": {
            "fingerprints_sha256": {k: _sha256(v) for k, v in files.items()},
            "summary_matches_runs": not mismatches,
            "mismatches": mismatches,
            "preregistration": [{**p, "url": f"{REPO_URL}/commit/{p['commit']}"} for p in PREREG],
        },
        "execution_timing": None,
        "execution_timing_note": "Not measured for the saved run; no timing or failure data was recorded.",
        "raw_results": {"runs_csv": "results/runs.csv", "summary_json": "results/summary.json",
                        "repo": f"{REPO_URL}/tree/master/results"},
        "cells": summary["cells"],
        "per_scenario": per_scenario,
        "hypotheses": summary["hypotheses"],
    }


def to_csv(export: dict) -> str:
    buf = io.StringIO()
    cols = ["scenario", "topology", "incentive", "access", "n", "accuracy", "false_blame", "abstain",
            "mean_steps", "n_steps", "mean_messages"]
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for r in export["per_scenario"]:
        w.writerow({k: r[k] for k in cols})
    return buf.getvalue()
