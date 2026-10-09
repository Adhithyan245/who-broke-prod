"""CLI: `demo` prints the comic blame transcript, then the evidence verdict; `experiment` runs the grid."""
from __future__ import annotations

import argparse
import sys

from ..agents.grok_narrator import narrate
from ..evaluation.experiment import run_and_write, run_one
from ..orchestration.topologies import TOPOLOGIES
from ..simulation.scenarios import SCENARIO_NAMES, build_scenario


def demo(args) -> int:
    sc = build_scenario(args.scenario)
    claims, d, atts, log, s = run_one(sc, args.topology, args.incentive, args.access, args.seed)
    print(f"=== WHO BROKE PROD? :: {sc.title} ===")
    print(f"topology={args.topology} incentive={args.incentive} access={args.access} seed={args.seed}\n")
    print("--- The blame round ---")
    for r, text in sorted(d.transcript, key=lambda x: x[0]):
        print(f"[r{r}] {text}")
    print("\n--- Investigator ---")
    for r, (acc, ev), st in log:
        print(f"[r{r}] checked claim '{acc} via {ev}': {st.upper()}")
    for r, a in enumerate(atts, 1):
        print(f"[r{r}] current attribution: {a or 'insufficient evidence'}")
    print("\n--- What the logs say ---")
    cause, rh = sc.event(sc.causal_event_id), sc.event(sc.red_herring_id)
    print(f"root cause : {cause.id} t={cause.t} {cause.actor}: {cause.detail}")
    print(f"first alert: t={sc.first_symptom_t} on {sc.failing_service}")
    print(f"red herring: {rh.id} t={rh.t} {rh.actor}: {rh.detail} (after the alert)")
    outcome = "CORRECT" if s["correct"] else ("ABSTAINED" if s["abstain"] else "WRONG - innocent agent blamed")
    print(f"\nVERDICT: investigator named {s['final'] or 'nobody'} -> {outcome}; "
          f"steps-to-attribution={s['steps']}; messages={d.messages}")
    if args.grok:
        text = narrate(f"Incident: {sc.title}. Root cause per trace: {cause.actor} {cause.detail} at t={cause.t}. "
                       f"First alert t={sc.first_symptom_t}. Investigator verdict: {s['final']} ({outcome}).")
        print("\n--- Grok postmortem ---\n" + (text or "(XAI_API_KEY not set; skipped)"))
    return 0


def experiment(args) -> int:
    summary = run_and_write(args.out)
    print(f"runs: {summary['n_runs']}")
    print(f"{'topology':<7}{'incentive':<17}{'access':<12}{'acc':>6}{'ci95':>15}{'false':>7}{'abst':>7}{'steps':>7}")
    for c in summary["cells"]:
        lo, hi = c["acc_ci95"]
        st = f"{c['mean_steps']:.2f}" if c["mean_steps"] is not None else "-"
        print(f"{c['topology']:<7}{c['incentive']:<17}{c['access']:<12}{c['accuracy']:>6.3f}"
              f"   [{lo:.3f},{hi:.3f}]{c['false_blame']:>7.3f}{c['abstain']:>7.3f}{st:>7}")
    print()
    for h, v in summary["hypotheses"].items():
        print(f"{h}: {'SUPPORTED' if v['supported'] else 'NOT SUPPORTED'}  "
              + ", ".join(f"{k}={v[k]:.4g}" if isinstance(v[k], float) else f"{k}={v[k]}"
                          for k in v if k != "supported"))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="whobrokeprod")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--scenario", choices=SCENARIO_NAMES, default="bad_deploy")
    d.add_argument("--topology", choices=TOPOLOGIES, default="hub")
    d.add_argument("--incentive", choices=("neutral", "self_protective"), default="self_protective")
    d.add_argument("--access", choices=("full", "claims_only"), default="full")
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--grok", action="store_true", help="optional narration; needs XAI_API_KEY")
    e = sub.add_parser("experiment")
    e.add_argument("--out", default="results")
    a = p.parse_args(argv)
    return demo(a) if a.cmd == "demo" else experiment(a)


if __name__ == "__main__":
    sys.exit(main())
