"""Read-only evaluation export derived from the saved preregistered run (results/).

Nothing here reruns the experiment. It reads results/runs.csv and results/summary.json, fingerprints them,
validates the saved rows against the experiment's grid definition (row count, coverage, duplicates,
missing/unexpected runs, row-level value invariants, summary structure, per-cell sample counts and aggregate
metrics), and adds a per-scenario breakdown computed from the same saved rows.

`reproducibility.summary_matches_runs` is true only when every integrity check passes; the individual
failures are listed in `integrity.errors`. Structurally unusable inputs (unreadable JSON, missing CSV columns)
raise InvalidResults instead of producing an export.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from statistics import mean

from ..agents import rule_agents
from ..config import ROOT, Config
from ..orchestration.topologies import DROP_P, TOPOLOGIES
from ..simulation.scenarios import AGENTS, SCENARIO_NAMES, build_scenario
from . import investigator
from .experiment import ACCESS, INCENTIVES, SEEDS

PREREG = [
    {"step": "hypotheses", "commit": "97dc432d9e238fe63622b1ab5393f975780e8ce3"},
    {"step": "code", "commit": "b08a2c34e74d0b956f70d5735ab0bf2983824be2"},
    {"step": "results", "commit": "61ad8b0a43528bb79a2085b042400784e19577a8"},
]
REPO_URL = "https://github.com/Adhithyan245/who-broke-prod"


RUN_KEY = ("scenario", "topology", "incentive", "access", "seed")
RUN_COLUMNS = RUN_KEY + ("messages", "final", "correct", "false_blame", "abstain", "steps")
CELL_KEY = ("topology", "incentive", "access")
CELL_METRICS = ("accuracy", "false_blame", "abstain", "mean_steps", "mean_messages")
MAX_LISTED_ERRORS = 50


def expected_grid() -> dict:
    """Grid dimensions taken from the experiment definition (single source of truth)."""
    return {"scenarios": tuple(SCENARIO_NAMES), "topologies": tuple(TOPOLOGIES), "incentives": tuple(INCENTIVES),
            "access": tuple(ACCESS), "seeds": tuple(SEEDS)}


def expected_run_count(grid: dict | None = None) -> int:
    g = grid or expected_grid()
    return math.prod(len(v) for v in g.values())


class MissingResults(FileNotFoundError):
    pass


class InvalidResults(ValueError):
    """Saved results exist but are structurally unusable (e.g. unreadable JSON, missing CSV columns)."""


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_runs_csv(results_dir: str) -> tuple[list[dict], list[str]]:
    """Raw rows (all strings) and the header. Raises MissingResults / InvalidResults."""
    path = os.path.join(results_dir, "runs.csv")
    if not os.path.exists(path):
        raise MissingResults(path)
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        missing = [c for c in RUN_COLUMNS if c not in header]
        if missing:
            raise InvalidResults(f"runs.csv is missing required columns: {missing}")
        rows = list(reader)
    return rows, header


def _parse_row(raw: dict, line: int, grid: dict, culprits: dict) -> tuple[dict | None, list[dict]]:
    """Validate one raw row. Returns (parsed row or None if malformed/unexpected, errors)."""
    def err(check, detail):
        return {"check": check, "line": line, "detail": detail}
    if None in raw or any(raw.get(c) is None for c in RUN_COLUMNS):
        return None, [err("malformed_row", "wrong number of fields")]
    r = dict(raw)
    try:
        for k in ("seed", "messages", "correct", "false_blame", "abstain"):
            r[k] = int(r[k])
        r["steps"] = int(r["steps"]) if r["steps"] != "" else None
    except ValueError as e:
        return None, [err("malformed_row", f"non-integer value: {e}")]
    errors = []
    for field, allowed in (("scenario", grid["scenarios"]), ("topology", grid["topologies"]),
                           ("incentive", grid["incentives"]), ("access", grid["access"]), ("seed", grid["seeds"])):
        if r[field] not in allowed:
            errors.append(err("unexpected_run", f"{field}={r[field]!r} is not in the experiment grid"))
    if errors:
        return None, errors
    if any(r[k] not in (0, 1) for k in ("correct", "false_blame", "abstain")):
        errors.append(err("invalid_value", "correct/false_blame/abstain must be 0 or 1"))
    elif r["correct"] + r["false_blame"] + r["abstain"] != 1:
        errors.append(err("invalid_value", "exactly one of correct/false_blame/abstain must be 1"))
    if r["messages"] < 0:
        errors.append(err("invalid_value", "messages must be >= 0"))
    if r["final"] not in ("", *AGENTS):
        errors.append(err("invalid_value", f"final={r['final']!r} is not an agent"))
    if (r["final"] == "") != (r["abstain"] == 1):
        errors.append(err("invalid_value", "abstain must be 1 exactly when final is empty"))
    if r["correct"] in (0, 1) and (r["final"] == culprits[r["scenario"]]) != (r["correct"] == 1):
        errors.append(err("invalid_value", "correct disagrees with the scenario's culprit"))
    if r["steps"] is not None and not 1 <= r["steps"] <= investigator.DEADLINE:
        errors.append(err("invalid_value", f"steps must be in 1..{investigator.DEADLINE} or empty"))
    if (r["steps"] is None) == (r["correct"] == 1):
        errors.append(err("invalid_value", "steps must be present exactly when correct is 1"))
    return (None if errors else r), errors


def load_runs(results_dir: str) -> list[dict]:
    """Parsed, valid rows only (backward-compatible helper)."""
    return validate_runs(*read_runs_csv(results_dir))[0]


def validate_runs(raw_rows: list[dict], header: list[str], grid: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Row-level, coverage and duplicate checks. Returns (valid rows, errors)."""
    grid = grid or expected_grid()
    culprits = {sc: build_scenario(sc).culprit for sc in grid["scenarios"]}
    errors = [{"check": "unexpected_column", "detail": c} for c in header if c not in RUN_COLUMNS]
    expected_n = expected_run_count(grid)
    if len(raw_rows) != expected_n:
        errors.append(_e("row_count", f"runs.csv has {len(raw_rows)} rows, expected {expected_n}"))
    valid, seen = [], {}
    for i, raw in enumerate(raw_rows):
        line = i + 2  # header is line 1
        r, errs = _parse_row(raw, line, grid, culprits)
        errors += errs
        if r is None:
            continue
        key = tuple(r[k] for k in RUN_KEY)
        if key in seen:
            errors.append({"check": "duplicate_run", "line": line, "detail": f"{key} first seen on line {seen[key]}"})
            continue
        seen[key] = line
        valid.append(r)
    expected_keys = {(sc, t, inc, acc, seed) for sc in grid["scenarios"] for t in grid["topologies"]
                     for inc in grid["incentives"] for acc in grid["access"] for seed in grid["seeds"]}
    for key in sorted(expected_keys - seen.keys(), key=str):
        errors.append({"check": "missing_run", "detail": str(key)})
    return valid, errors


def _e(check: str, detail: str) -> dict:
    return {"check": check, "detail": detail}


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, int | float) or not isinstance(b, int | float):
        return False
    return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)


def validate_summary(summary, rows: list[dict], grid: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Summary structure, n_runs, per-cell sample counts and aggregate metrics. Returns (errors, mismatches)."""
    grid = grid or expected_grid()
    errors, mismatches = [], []
    if not isinstance(summary, dict) or not isinstance(summary.get("cells"), list):
        return [{"check": "summary_structure", "detail": "summary.json must be an object with a 'cells' list"}], []
    expected_n = expected_run_count(grid)
    if summary.get("n_runs") != expected_n:
        errors.append(_e("summary_structure", f"n_runs={summary.get('n_runs')!r}, expected {expected_n}"))
    if not isinstance(summary.get("hypotheses"), dict):
        errors.append({"check": "summary_structure", "detail": "'hypotheses' must be an object"})
    expected_cells = {(t, inc, acc) for t in grid["topologies"] for inc in grid["incentives"] for acc in grid["access"]}
    per_cell_expected = expected_n // len(expected_cells)
    seen = set()
    for idx, c in enumerate(summary["cells"]):
        if not isinstance(c, dict) or any(k not in c for k in CELL_KEY + CELL_METRICS + ("n",)):
            errors.append(_e("summary_structure", f"cells[{idx}] is missing required keys"))
            continue
        bad = [k for k in CELL_KEY if not isinstance(c[k], str)]
        if bad:
            types = ", ".join(f"{k}={type(c[k]).__name__}" for k in bad)
            errors.append(_e("summary_structure", f"cells[{idx}] has non-string identity field(s): {types}"))
            continue
        key = tuple(c[k] for k in CELL_KEY)
        if key not in expected_cells:
            errors.append(_e("summary_structure", f"cells[{idx}] {key} is not in the grid"))
            continue
        if key in seen:
            errors.append(_e("summary_structure", f"cells[{idx}] {key} is duplicated"))
            continue
        seen.add(key)
        sel = [r for r in rows if tuple(r[k] for k in CELL_KEY) == key]
        if c["n"] != per_cell_expected:
            errors.append(_e("sample_count", f"{list(key)} summary n={c['n']!r}, expected {per_cell_expected}"))
        if c["n"] != len(sel):
            errors.append(_e("sample_count", f"{list(key)} summary n={c['n']!r}, runs.csv has {len(sel)}"))
        got = _cell_stats(sel)
        for k in CELL_METRICS:
            if not _close(got[k], c[k]):
                mismatches.append({"cell": list(key), "metric": k})
                errors.append(_e("metric_mismatch", f"{list(key)} {k}: summary={c[k]!r}, runs={got[k]!r}"))
    for key in sorted(expected_cells - seen):
        errors.append(_e("summary_structure", f"cell {list(key)} is missing"))
    return errors, mismatches


def _cell_stats(rows: list[dict]) -> dict:
    st = [r["steps"] for r in rows if r["steps"] is not None]
    n = len(rows)
    if n == 0:
        return {"n": 0, "accuracy": None, "false_blame": None, "abstain": None, "mean_steps": None,
                "n_steps": 0, "mean_messages": None}
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
    try:
        with open(summary_path) as fh:
            summary = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise InvalidResults(f"summary.json is not valid JSON: {e}") from None
    grid = expected_grid()
    raw_rows, header = read_runs_csv(rd)
    rows, errors = validate_runs(raw_rows, header, grid)
    s_errors, mismatches = validate_summary(summary, rows, grid)
    errors += s_errors
    summary_ok = isinstance(summary, dict)
    per_scenario = []
    for sc in grid["scenarios"]:
        for t in grid["topologies"]:
            for inc in grid["incentives"]:
                for acc in grid["access"]:
                    sel = [r for r in rows if (r["scenario"], r["topology"], r["incentive"], r["access"])
                           == (sc, t, inc, acc)]
                    per_scenario.append({"scenario": sc, "topology": t, "incentive": inc, "access": acc,
                                         **_cell_stats(sel)})
    hyp_path = os.path.join(ROOT, "HYPOTHESES.md")
    files = {"results/runs.csv": os.path.join(rd, "runs.csv"), "results/summary.json": summary_path}
    if os.path.exists(hyp_path):
        files["HYPOTHESES.md"] = hyp_path
    seeds = [r["seed"] for r in rows]
    return {
        "source": "saved preregistered run (read-only; not rerun by this export)",
        "run_count": len(raw_rows),
        "config": {"scenarios": list(grid["scenarios"]), "topologies": list(grid["topologies"]),
                   "incentives": list(grid["incentives"]), "access": list(grid["access"]),
                   "seeds": {"min": min(seeds, default=None), "max": max(seeds, default=None),
                             "count": len(set(seeds))},
                   "witness_p": rule_agents.WITNESS_P, "fabricate_p": rule_agents.FABRICATE_P,
                   "chain_drop_p": DROP_P, "verification_budget": investigator.BUDGET,
                   "deadline_rounds": investigator.DEADLINE},
        "integrity": {
            "ok": not errors,
            "expected_runs": expected_run_count(grid),
            "rows_read": len(raw_rows),
            "valid_unique_runs": len(rows),
            "checks": ["columns", "row_count", "row_values", "grid_membership", "duplicates", "coverage",
                       "summary_structure", "sample_count", "aggregate_metrics"],
            "error_count": len(errors),
            "errors": errors[:MAX_LISTED_ERRORS],
            "errors_truncated": len(errors) > MAX_LISTED_ERRORS,
        },
        "reproducibility": {
            "fingerprints_sha256": {k: _sha256(v) for k, v in files.items()},
            "summary_matches_runs": not errors,
            "mismatches": mismatches,
            "preregistration": [{**p, "url": f"{REPO_URL}/commit/{p['commit']}"} for p in PREREG],
        },
        "execution_timing": None,
        "execution_timing_note": "Not measured for the saved run; no timing or failure data was recorded.",
        "raw_results": {"runs_csv": "results/runs.csv", "summary_json": "results/summary.json",
                        "repo": f"{REPO_URL}/tree/master/results"},
        "cells": summary.get("cells", []) if summary_ok else [],
        "per_scenario": per_scenario,
        "hypotheses": summary.get("hypotheses", {}) if summary_ok else {},
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
