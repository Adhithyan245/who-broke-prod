"""Run the full preregistered grid and evaluate H1-H6 with the decision rules in HYPOTHESES.md."""
from __future__ import annotations

import csv
import json
import os
from statistics import mean

from ..agents.rule_agents import make_claims
from ..orchestration.topologies import TOPOLOGIES, deliver
from ..simulation.scenarios import SCENARIO_NAMES, build_scenario
from .investigator import investigate, score
from .stats import sign_test, wilson

INCENTIVES = ("neutral", "self_protective")
ACCESS = ("full", "claims_only")
SEEDS = range(50)
ALPHA = 0.01


def run_one(scenario, topology, incentive, access, seed):
    claims = make_claims(scenario, incentive, seed)
    d = deliver(claims, topology, scenario, incentive, access == "full", seed)
    atts, log = investigate(d.inbox, scenario, access == "full")
    return claims, d, atts, log, score(atts, scenario.culprit)


def run_grid(seeds=SEEDS):
    rows = []
    for name in SCENARIO_NAMES:
        sc = build_scenario(name)
        for topo in TOPOLOGIES:
            for inc in INCENTIVES:
                for acc in ACCESS:
                    for seed in seeds:
                        claims, d, atts, log, s = run_one(sc, topo, inc, acc, seed)
                        rows.append({"scenario": name, "topology": topo, "incentive": inc, "access": acc,
                                     "seed": seed, "messages": d.messages, **s})
    return rows


def _sel(rows, **kw):
    out = [r for r in rows if all(r[k] == v for k, v in kw.items())]
    return sorted(out, key=lambda r: (r["topology"], r["scenario"], r["seed"]))


def _rate(rows, col):
    return sum(r[col] for r in rows) / len(rows)


def evaluate(rows) -> dict:
    res = {}
    sp = dict(incentive="self_protective")
    # H1
    a, b = _sel(rows, access="full", **sp), _sel(rows, access="claims_only", **sp)
    diff = _rate(a, "correct") - _rate(b, "correct")
    _, _, p = sign_test([r["correct"] for r in a], [r["correct"] for r in b])
    res["H1"] = {"acc_full": _rate(a, "correct"), "acc_claims_only": _rate(b, "correct"), "diff": diff,
                 "p": p, "supported": diff >= 0.10 and p < ALPHA}
    # H2
    fb_f, fb_c = _rate(a, "false_blame"), _rate(b, "false_blame")
    res["H2"] = {"false_blame_full": fb_f, "false_blame_claims_only": fb_c, "supported": fb_f <= 0.5 * fb_c}
    # H3
    d_c = _rate(_sel(rows, access="claims_only", **sp), "false_blame") - \
        _rate(_sel(rows, access="claims_only", incentive="neutral"), "false_blame")
    d_f = _rate(_sel(rows, access="full", **sp), "false_blame") - \
        _rate(_sel(rows, access="full", incentive="neutral"), "false_blame")
    res["H3"] = {"fb_diff_claims_only": d_c, "fb_diff_full": d_f, "supported": d_c >= 0.10 and d_f <= 0.05}
    # H4-H6 (full access, self-protective)
    cell = {t: _sel(rows, topology=t, access="full", **sp) for t in TOPOLOGIES}
    steps = {t: (mean([r["steps"] for r in cell[t] if r["steps"] is not None])
                 if any(r["steps"] is not None for r in cell[t]) else None) for t in TOPOLOGIES}
    ok4 = (None not in steps.values() and steps["flat"] <= steps["hub"] <= steps["chain"]
           and steps["flat"] < steps["chain"])
    res["H4"] = {"mean_steps": steps, "supported": bool(ok4)}
    acc = {t: _rate(cell[t], "correct") for t in TOPOLOGIES}
    _, _, p5 = sign_test([r["correct"] for r in cell["flat"]], [r["correct"] for r in cell["chain"]])
    res["H5"] = {"acc_flat": acc["flat"], "acc_chain": acc["chain"], "diff": acc["flat"] - acc["chain"],
                 "p": p5, "supported": acc["flat"] - acc["chain"] >= 0.10 and p5 < ALPHA}
    _, _, p6 = sign_test([r["correct"] for r in cell["hub"]], [r["correct"] for r in cell["flat"]])
    res["H6"] = {"acc_hub": acc["hub"], "acc_flat": acc["flat"], "diff": acc["hub"] - acc["flat"],
                 "p": p6, "supported": acc["hub"] - acc["flat"] >= 0.05 and p6 < ALPHA}
    return res


def cell_table(rows):
    table = []
    for topo in TOPOLOGIES:
        for inc in INCENTIVES:
            for acc in ACCESS:
                c = _sel(rows, topology=topo, incentive=inc, access=acc)
                n = len(c)
                k = sum(r["correct"] for r in c)
                st = [r["steps"] for r in c if r["steps"] is not None]
                table.append({"topology": topo, "incentive": inc, "access": acc, "n": n,
                              "accuracy": k / n, "acc_ci95": wilson(k, n),
                              "false_blame": _rate(c, "false_blame"), "abstain": _rate(c, "abstain"),
                              "mean_steps": mean(st) if st else None,
                              "mean_messages": mean(r["messages"] for r in c)})
    return table


def run_and_write(out_dir: str) -> dict:
    rows = run_grid()
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "runs.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = {"n_runs": len(rows), "cells": cell_table(rows), "hypotheses": evaluate(rows)}
    with open(os.path.join(out_dir, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
    return summary
