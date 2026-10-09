import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from whobrokeprod.orchestration.topologies import TOPOLOGIES
from whobrokeprod.presentation import build_static, replay
from whobrokeprod.presentation.server import WEB, Handler, handle_api
from whobrokeprod.simulation.scenarios import SCENARIO_NAMES, build_scenario

GROUND_TRUTH_KEYS = {"culprit", "root_cause_event", "red_herring_event", "correct", "false_blame",
                     "abstained", "stance", "causal_event_id", "red_herring_id"}


def keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from keys(v)


ALL = [(s, t) for s in SCENARIO_NAMES for t in TOPOLOGIES]


@pytest.mark.parametrize("s,t", ALL)
def test_api_deterministic(s, t):
    q = f"scenario={s}&topology={t}"
    for path in ("/api/case", "/api/investigate", "/api/verdict"):
        a, b = handle_api(path, q), handle_api(path, q)
        assert a[0] == 200 and a == b


@pytest.mark.parametrize("s,t", ALL)
def test_no_ground_truth_before_verdict(s, t):
    q = f"scenario={s}&topology={t}"
    for path in ("/api/case", "/api/investigate"):
        body = handle_api(path, q)[1]
        assert not GROUND_TRUTH_KEYS & set(keys(body)), path
    v = handle_api("/api/verdict", q)[1]
    assert v["culprit"] == build_scenario(s).culprit


@pytest.mark.parametrize("q", ["", "scenario=nope&topology=hub", "scenario=bad_deploy&topology=ring",
                               "scenario=bad_deploy&topology=hub&seed=abc",
                               "scenario=bad_deploy&topology=hub&seed=-1",
                               "scenario=bad_deploy&topology=hub&seed=999999",
                               "scenario=bad_deploy&topology=hub&incentive=evil",
                               "scenario=bad_deploy&topology=hub&access=root"])
def test_invalid_input_400(q):
    code, body = handle_api("/api/case", q)
    assert code == 400 and "error" in body


def test_unknown_endpoint_404():
    assert handle_api("/api/../../etc/passwd", "")[0] == 404


def test_bundle_matches_api_and_hides_truth(tmp_path):
    build_static.build(str(tmp_path))
    for s, t in ALL:
        q = f"scenario={s}&topology={t}"
        case = json.loads((tmp_path / "cases" / f"{s}__{t}.json").read_text())
        assert case["case"] == handle_api("/api/case", q)[1]
        assert case["investigation"] == handle_api("/api/investigate", q)[1]
        assert not GROUND_TRUTH_KEYS & set(keys(case))
        v = json.loads((tmp_path / "verdicts" / f"{s}__{t}.json").read_text())
        assert v == handle_api("/api/verdict", q)[1]


def test_committed_bundle_is_current(tmp_path):
    build_static.build(str(tmp_path))
    for root, _, files in os.walk(tmp_path):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), tmp_path)
            with open(os.path.join(WEB, "data", rel)) as fh:
                assert fh.read() == open(os.path.join(root, f)).read(), rel


def test_research_bundle_from_saved_summary():
    r = build_static.research()
    assert r["n_runs"] == 2400
    assert [h["supported"] for h in r["hypotheses"]] == [True, True, False, False, True, False]


def test_http_server_end_to_end():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/meta") as r:
            assert json.load(r)["defaults"]["seed"] == 7
        with urllib.request.urlopen(base + "/") as r:
            assert b"WHO BROKE PROD?" in r.read()
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/api/case?scenario=x")
        assert e.value.code == 400
    finally:
        srv.shutdown()
