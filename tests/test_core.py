import json

import pytest

from whobrokeprod.agents import grok_narrator
from whobrokeprod.agents.rule_agents import make_claims
from whobrokeprod.evaluation.experiment import run_grid, run_one
from whobrokeprod.evaluation.investigator import investigate, score
from whobrokeprod.evaluation.stats import sign_test, wilson
from whobrokeprod.orchestration.topologies import TOPOLOGIES, deliver
from whobrokeprod.presentation.cli import main
from whobrokeprod.simulation.scenarios import AGENTS, SCENARIO_NAMES, build_scenario


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_scenario_has_exactly_one_supported_root_cause(name):
    sc = build_scenario(name)
    hits = [(a, e.id) for a in AGENTS for e in sc.trace if sc.supports(a, e.id)]
    assert hits == [(sc.culprit, sc.causal_event_id)]
    rh = sc.event(sc.red_herring_id)
    assert rh.service == sc.failing_service and rh.t > sc.first_symptom_t
    assert rh.actor != sc.culprit


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_scenarios_are_deterministic(name):
    assert build_scenario(name) == build_scenario(name)


def test_supports_rejects_fabricated_and_wrong_actor():
    sc = build_scenario("bad_deploy")
    assert not sc.supports(sc.culprit, "e99")
    assert not sc.supports("ConfigBot", sc.causal_event_id)


def test_claims_deterministic_and_common_random_numbers():
    sc = build_scenario("flag_flip")
    for seed in range(20):
        a = make_claims(sc, "neutral", seed)
        b = make_claims(sc, "self_protective", seed)
        assert a == make_claims(sc, "neutral", seed)
        wa = {c.speaker for c in a if c.stance == "witness"}
        wb = {c.speaker for c in b if c.stance == "witness"}
        assert wa == wb  # same witnesses across incentive conditions


def test_neutral_culprit_confesses_self_protective_deflects_to_innocent():
    for name in SCENARIO_NAMES:
        sc = build_scenario(name)
        for seed in range(10):
            n = {c.speaker: c for c in make_claims(sc, "neutral", seed)}
            s = make_claims(sc, "self_protective", seed)
            assert n[sc.culprit].accused == sc.culprit
            assert all(c.accused != c.speaker for c in s)
            assert all(c.accused != sc.culprit for c in s if c.stance in ("deflect", "scapegoat"))


def test_flat_full_access_neutral_is_correct():
    # culprit confesses with a valid citation -> verified on round 1 or soon after
    for name in SCENARIO_NAMES:
        sc = build_scenario(name)
        for seed in range(10):
            *_, s = run_one(sc, "flat", "neutral", "full", seed)
            assert s["correct"] == 1


def test_chain_arrival_rounds():
    sc = build_scenario("bad_deploy")
    d = deliver(make_claims(sc, "neutral", 0), "chain", sc, "neutral", True, 0)
    assert sorted(d.inbox) == [1, 2, 3, 4, 5]
    assert all(len(v) == 1 for v in d.inbox.values())


def test_hub_mediator_drops_refuted_top_claim():
    sc = build_scenario("bad_deploy")
    for seed in range(30):
        claims = make_claims(sc, "self_protective", seed)
        d = deliver(claims, "hub", sc, "self_protective", True, seed)
        assert list(d.inbox) == [2]
        assert len(d.inbox[2]) <= len(claims)


def test_investigator_abstains_on_tie_and_scores():
    sc = build_scenario("bad_deploy")
    atts, _ = investigate({}, sc, access=False)
    assert atts == [None] * 5
    assert score(atts, sc.culprit) == {"final": None, "correct": 0, "false_blame": 0, "abstain": 1, "steps": None}
    assert score(["X", sc.culprit, sc.culprit], sc.culprit)["steps"] == 2
    assert score([sc.culprit, "X"], sc.culprit)["false_blame"] == 1


def test_stats():
    assert sign_test([1, 1, 0], [0, 1, 0]) == (1, 0, 1.0)
    assert sign_test([1] * 10, [0] * 10)[2] == pytest.approx(2 / 1024)
    lo, hi = wilson(50, 100)
    assert lo < 0.5 < hi


def test_grid_is_reproducible_small():
    a = run_grid(seeds=range(3))
    assert a == run_grid(seeds=range(3))
    assert len(a) == len(SCENARIO_NAMES) * len(TOPOLOGIES) * 2 * 2 * 3


def test_grok_off_without_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    def boom(*a, **k):
        raise AssertionError("network must not be touched")
    monkeypatch.setattr(grok_narrator.urllib.request, "urlopen", boom)
    assert grok_narrator.narrate("x") is None


def test_demo_runs(capsys, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert main(["demo", "--scenario", "migration_lock", "--topology", "flat"]) == 0
    out = capsys.readouterr().out
    assert "VERDICT" in out and "What the logs say" in out
