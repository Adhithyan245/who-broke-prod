"""Export integrity: every check must flip summary_matches_runs to false. Works on tmp copies only."""
import csv
import hashlib
import json
import os
import shutil

import pytest

from whobrokeprod.config import ROOT, Config
from whobrokeprod.evaluation import export as export_mod
from whobrokeprod.evaluation.experiment import ACCESS, INCENTIVES, SEEDS
from whobrokeprod.orchestration.topologies import TOPOLOGIES
from whobrokeprod.presentation import cli, server
from whobrokeprod.simulation.scenarios import SCENARIO_NAMES

RESULTS = os.path.join(ROOT, "results")


def _digest():
    return {f: hashlib.sha256(open(os.path.join(RESULTS, f), "rb").read()).hexdigest()
            for f in ("runs.csv", "summary.json")}


@pytest.fixture(autouse=True)
def committed_results_untouched():
    before = _digest()
    yield
    assert _digest() == before


@pytest.fixture
def copy(tmp_path):
    for f in ("runs.csv", "summary.json"):
        shutil.copy(os.path.join(RESULTS, f), tmp_path / f)
    return tmp_path


def read_rows(d):
    with open(d / "runs.csv", newline="") as fh:
        r = csv.DictReader(fh)
        return list(r.fieldnames), list(r)


def write_rows(d, header, rows):
    with open(d / "runs.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def export(d):
    return export_mod.build_export(Config(results_dir=str(d)))


def checks(e):
    return {x["check"] for x in e["integrity"]["errors"]}


def assert_fails(e, *expected):
    assert e["reproducibility"]["summary_matches_runs"] is False
    assert e["integrity"]["ok"] is False and e["integrity"]["error_count"] > 0
    assert set(expected) <= checks(e), checks(e)


def test_expected_count_comes_from_experiment_definition():
    n = len(SCENARIO_NAMES) * len(TOPOLOGIES) * len(INCENTIVES) * len(ACCESS) * len(SEEDS)
    assert export_mod.expected_run_count() == n == 2400


def test_valid_dataset_passes(copy):
    e = export(copy)
    assert e["integrity"] == {**e["integrity"], "ok": True, "error_count": 0, "errors": [],
                              "expected_runs": 2400, "rows_read": 2400, "valid_unique_runs": 2400}
    assert e["reproducibility"]["summary_matches_runs"] is True and e["reproducibility"]["mismatches"] == []
    assert e["run_count"] == 2400


def test_missing_row(copy):
    h, rows = read_rows(copy)
    write_rows(copy, h, rows[:-1])
    e = export(copy)
    assert_fails(e, "row_count", "missing_run", "sample_count")
    assert e["integrity"]["rows_read"] == 2399


def test_duplicate_run_replacing_another(copy):
    """Count stays 2400 but one run is duplicated and another is absent."""
    h, rows = read_rows(copy)
    rows[1] = dict(rows[0])
    write_rows(copy, h, rows)
    e = export(copy)
    assert_fails(e, "duplicate_run", "missing_run")
    assert "row_count" not in checks(e)


@pytest.mark.parametrize("field,value", [("scenario", "dns_outage"), ("topology", "mesh"),
                                         ("incentive", "greedy"), ("access", "partial"), ("seed", "50")])
def test_unexpected_combination(copy, field, value):
    h, rows = read_rows(copy)
    rows[5][field] = value
    write_rows(copy, h, rows)
    assert_fails(export(copy), "unexpected_run", "missing_run")


@pytest.mark.parametrize("field,value,check", [("correct", "x", "malformed_row"), ("seed", "", "malformed_row"),
                                               ("correct", "2", "invalid_value"), ("abstain", "1", "invalid_value"),
                                               ("steps", "9", "invalid_value"), ("final", "Nobody", "invalid_value"),
                                               ("messages", "-1", "invalid_value")])
def test_invalid_values(copy, field, value, check):
    h, rows = read_rows(copy)
    rows[0][field] = value
    write_rows(copy, h, rows)
    assert_fails(export(copy), check)


def test_correct_flag_inconsistent_with_culprit(copy):
    h, rows = read_rows(copy)
    i = next(i for i, r in enumerate(rows) if r["false_blame"] == "1")
    rows[i].update(correct="1", false_blame="0", steps="1")  # final still names an innocent agent
    write_rows(copy, h, rows)
    assert_fails(export(copy), "invalid_value")


def test_short_row_is_malformed(copy):
    with open(copy / "runs.csv") as fh:
        lines = fh.readlines()
    lines[3] = ",".join(lines[3].split(",")[:5]) + "\n"
    with open(copy / "runs.csv", "w") as fh:
        fh.writelines(lines)
    assert_fails(export(copy), "malformed_row", "missing_run")


def test_missing_column_is_invalid_results(copy):
    h, rows = read_rows(copy)
    write_rows(copy, [c for c in h if c != "steps"], rows)
    with pytest.raises(export_mod.InvalidResults, match="steps"):
        export(copy)


def test_unexpected_column_flagged(copy):
    h, rows = read_rows(copy)
    for r in rows:
        r["extra"] = "1"
    write_rows(copy, h + ["extra"], rows)
    assert_fails(export(copy), "unexpected_column")


def test_aggregate_metric_mismatch(copy):
    s = json.loads((copy / "summary.json").read_text())
    s["cells"][3]["accuracy"] += 0.01
    (copy / "summary.json").write_text(json.dumps(s))
    e = export(copy)
    assert_fails(e, "metric_mismatch")
    cell = [s["cells"][3][k] for k in ("topology", "incentive", "access")]
    assert e["reproducibility"]["mismatches"] == [{"cell": cell, "metric": "accuracy"}]


def test_sample_count_mismatch(copy):
    s = json.loads((copy / "summary.json").read_text())
    s["cells"][0]["n"] = 199
    (copy / "summary.json").write_text(json.dumps(s))
    assert_fails(export(copy), "sample_count")


@pytest.mark.parametrize("mutate", [
    lambda s: s.update(n_runs=2399),
    lambda s: s["cells"].pop(),
    lambda s: s["cells"].append(dict(s["cells"][0])),
    lambda s: s["cells"][0].pop("mean_messages"),
    lambda s: s["cells"][0].update(topology="mesh"),
    lambda s: s.update(hypotheses=[]),
])
def test_inconsistent_summary_structure(copy, mutate):
    s = json.loads((copy / "summary.json").read_text())
    mutate(s)
    (copy / "summary.json").write_text(json.dumps(s))
    assert_fails(export(copy), "summary_structure")


def test_summary_not_an_object(copy):
    (copy / "summary.json").write_text("[]")
    assert_fails(export(copy), "summary_structure")


def test_unreadable_summary_is_invalid_results_503_and_cli_2(copy, monkeypatch, capsys):
    (copy / "summary.json").write_text("{not json")
    with pytest.raises(export_mod.InvalidResults):
        export(copy)
    monkeypatch.setattr(server, "CFG", Config(results_dir=str(copy)))
    st, body, _ = server.handle_api("/api/export", "format=json", "rid")
    assert st == 503 and body["error"]["code"] == "results_invalid" and body["request_id"] == "rid"
    monkeypatch.setenv("WBP_RESULTS_DIR", str(copy))
    assert cli.main(["export", "--format", "json"]) == 2
    assert "saved results invalid" in capsys.readouterr().err


def test_integrity_failure_is_reported_by_api_and_cli(copy, monkeypatch, capsys):
    h, rows = read_rows(copy)
    write_rows(copy, h, rows[:-1])
    monkeypatch.setattr(server, "CFG", Config(results_dir=str(copy)))
    st, body, _ = server.handle_api("/api/export", "format=json", "r")
    assert st == 200 and body["integrity"]["ok"] is False and body["reproducibility"]["summary_matches_runs"] is False
    st, text, _ = server.handle_api("/api/export", "format=csv", "r")
    assert st == 200 and text.startswith("scenario,")
    monkeypatch.setenv("WBP_RESULTS_DIR", str(copy))
    assert cli.main(["export", "--format", "csv", "--out", str(copy / "out.csv")]) == 1
    assert "integrity check FAILED" in capsys.readouterr().err


def test_export_json_schema_keys():
    e = export_mod.build_export()
    for k in ("source", "run_count", "config", "integrity", "reproducibility", "execution_timing", "raw_results",
              "cells", "per_scenario", "hypotheses"):
        assert k in e
    for k in ("fingerprints_sha256", "summary_matches_runs", "mismatches", "preregistration"):
        assert k in e["reproducibility"]
    assert set(e["integrity"]) >= {"ok", "errors", "error_count", "expected_runs", "rows_read", "valid_unique_runs"}


@pytest.mark.parametrize("field", ["topology", "incentive", "access"])
@pytest.mark.parametrize("value", [["flat"], {"x": 1}], ids=["list", "dict"])
def test_unhashable_cell_identity_is_integrity_error(copy, monkeypatch, capsys, field, value):
    s = json.loads((copy / "summary.json").read_text())
    s["cells"][2][field] = value
    (copy / "summary.json").write_text(json.dumps(s))
    e = export(copy)
    assert_fails(e, "summary_structure")
    msg = " ".join(x["detail"] for x in e["integrity"]["errors"])
    assert f"cells[2] has non-string identity field(s): {field}={type(value).__name__}" in msg
    monkeypatch.setattr(server, "CFG", Config(results_dir=str(copy)))
    for fmt in ("json", "csv"):
        st, body, _ = server.handle_api("/api/export", f"format={fmt}", "rid")
        assert st == 200
    st, body, _ = server.handle_api("/api/export", "format=json", "rid")
    assert body["reproducibility"]["summary_matches_runs"] is False
    monkeypatch.setenv("WBP_RESULTS_DIR", str(copy))
    assert cli.main(["export", "--format", "json", "--out", str(copy / "o.json")]) == 1
    err = capsys.readouterr().err
    assert "integrity check FAILED" in err and "Traceback" not in err
