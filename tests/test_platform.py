"""Tests for the platform upgrade: config, contracts, health, export, request ids, logs, bundle, regression."""
import csv
import io
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from whobrokeprod.config import ROOT, Config
from whobrokeprod.contracts import ReplayParams, ValidationError
from whobrokeprod.evaluation import export as export_mod
from whobrokeprod.evaluation.experiment import run_one
from whobrokeprod.evaluation.investigator import decide
from whobrokeprod.presentation import build_static, cli, replay, server
from whobrokeprod.simulation.scenarios import build_scenario

GROUND_TRUTH = ("culprit", "stance", "root_cause_event", "red_herring_event", "correct", "false_blame",
                "corrective_action", "investigator_named")


def test_config_env_parsing():
    c = Config.from_env({"WBP_HOST": "0.0.0.0", "WBP_PORT": "9000", "WBP_LOG_LEVEL": "debug"})
    assert (c.host, c.port, c.log_level) == ("0.0.0.0", 9000, "DEBUG")
    assert Config.from_env({"PORT": "8123"}).port == 8123
    for bad in ("abc", "70000", "-1"):
        with pytest.raises(ValueError):
            Config.from_env({"WBP_PORT": bad})


def test_replay_params_validation():
    p = ReplayParams.from_query({"scenario": ["flag_flip"], "topology": ["chain"], "seed": ["3"]})
    assert p.to_dict()["seed"] == 3
    for q, field in [({"scenario": ["nope"], "topology": ["hub"]}, "scenario"),
                     ({"scenario": ["flag_flip"], "topology": ["hub"], "seed": ["-1"]}, "seed"),
                     ({"scenario": ["flag_flip"], "topology": ["hub"], "bogus": ["1"]}, "bogus")]:
        with pytest.raises(ValidationError) as e:
            ReplayParams.from_query(q)
        assert e.value.field == field


def test_healthz_and_error_shape():
    st, body, ct = server.handle_api("/healthz", "", "rid1")
    assert st == 200 and body["status"] == "ok" and ct == "application/json"
    st, body, _ = server.handle_api("/api/case", "scenario=bad_deploy&topology=hub&x=1", "rid2")
    assert st == 400 and body["error"]["code"] == "invalid_parameter" and body["error"]["field"] == "x"
    assert body["request_id"] == "rid2"
    st, body, _ = server.handle_api("/api/nope", "", "rid3")
    assert st == 404 and body["error"]["code"] == "not_found"
    st, body, _ = server.handle_api("/api/export", "format=xml", "r")
    assert st == 400 and body["error"]["field"] == "format"


def test_export_json_and_csv_read_only():
    before = {f: os.path.getmtime(os.path.join(ROOT, "results", f)) for f in ("runs.csv", "summary.json")}
    st, data, _ = server.handle_api("/api/export", "format=json", "r")
    assert st == 200 and data["run_count"] == 2400
    assert data["reproducibility"]["summary_matches_runs"] is True
    assert data["execution_timing"] is None
    st, text, ct = server.handle_api("/api/export", "format=csv", "r")
    assert st == 200 and ct.startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 4 * 3 * 2 * 2 and all(int(r["n"]) == 50 for r in rows)
    after = {f: os.path.getmtime(os.path.join(ROOT, "results", f)) for f in before}
    assert before == after


def test_export_missing_results_is_503(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CFG", Config(results_dir=str(tmp_path)))
    st, body, _ = server.handle_api("/api/export", "", "rid")
    assert st == 503 and body["error"]["code"] == "results_unavailable"
    with pytest.raises(export_mod.MissingResults):
        export_mod.build_export(Config(results_dir=str(tmp_path)))


def test_request_id_header_and_json_logs(capsys):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        req = urllib.request.Request(base + "/healthz", headers={"X-Request-ID": "judge-1"})
        with urllib.request.urlopen(req) as r:
            assert r.headers["X-Request-ID"] == "judge-1"
        req = urllib.request.Request(base + "/api/meta", headers={"X-Request-ID": "bad id!"})
        with urllib.request.urlopen(req) as r:
            assert r.headers["X-Request-ID"] != "bad id!" and len(r.headers["X-Request-ID"]) > 0
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/api/case?scenario=zzz&topology=hub")
        assert e.value.code == 400 and json.loads(e.value.read())["error"]["field"] == "scenario"
    finally:
        httpd.shutdown()
        httpd.server_close()
    lines = [json.loads(x) for x in capsys.readouterr().err.splitlines() if x.startswith("{")]
    reqs = [x for x in lines if x.get("event") == "request"]
    assert any(x["request_id"] == "judge-1" and x["status"] == 200 for x in reqs)
    assert any(x["status"] == 400 for x in reqs)


def test_decide_reasons():
    assert decide([], {}) == (None, "abstain_no_claims")


def test_case_and_meta_do_not_leak_ground_truth():
    meta = json.dumps(replay.meta())
    for sc in ("bad_deploy", "flag_flip", "migration_lock", "cache_stampede"):
        for topo in ("flat", "hub", "chain"):
            p = ReplayParams(scenario=sc, topology=topo)
            case = replay.case(p)
            inv = replay.investigation(p)
            culprit = build_scenario(sc).culprit
            for blob in (case, inv):
                text = json.dumps(blob)
                for k in GROUND_TRUTH:
                    assert f'"{k}"' not in text, (sc, topo, k)
            assert "graph" in case and inv["final_reason_text"]
            # the diagram depends on topology only, so it cannot encode the culprit
            assert case["graph"] == replay.topology_graph(topo)
            assert culprit in [a["name"] for a in case["agents"]]
    assert '"culprit"' not in meta


def test_regression_sample_matches_saved_runs():
    """Re-run seeds 0-4 of every cell and compare with the saved 2,400-run results (read-only)."""
    with open(os.path.join(ROOT, "results", "runs.csv")) as fh:
        saved = {(r["scenario"], r["topology"], r["incentive"], r["access"], int(r["seed"])): r
                 for r in csv.DictReader(fh)}
    checked = 0
    for sc in ("bad_deploy", "flag_flip", "migration_lock", "cache_stampede"):
        s = build_scenario(sc)
        for topo in ("flat", "hub", "chain"):
            for inc in ("neutral", "self_protective"):
                for acc in ("full", "claims_only"):
                    for seed in range(5):
                        _, d, _, _, score = run_one(s, topo, inc, acc, seed)
                        row = saved[(sc, topo, inc, acc, seed)]
                        assert int(row["messages"]) == d.messages
                        assert int(row["correct"]) == int(score["correct"])
                        assert int(row["false_blame"]) == int(score["false_blame"])
                        assert (row["final"] or None) == (score["final"] or None)
                        checked += 1
    assert checked == 240


def test_static_bundle_is_fresh():
    assert build_static.check() == []


def test_cli_export(tmp_path, capsys):
    out = tmp_path / "e.csv"
    assert cli.main(["export", "--format", "csv", "--out", str(out)]) == 0
    assert out.read_text().splitlines()[0].startswith("scenario")
    assert cli.main(["export", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["run_count"] == 2400
