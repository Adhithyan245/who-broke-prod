# WHO BROKE PROD?

A deterministic multi-agent incident-investigation simulation. Five rule-based agents (DeployBot,
ConfigBot, AutoScaler, DBMigrator, CacheBot) are asked who caused a simulated outage. Most of them blame
someone else. An investigator reconstructs the root cause from their claims and, when allowed, from the
ground-truth event trace. The comedy is in the transcript; the measurement is in the scoring.

Simulation only. No real systems, customer data, network calls (by default) or destructive actions.

## Research question

In a fixed, seeded incident simulation, how do coordination topology (flat, hub-mediator, chain), the
agents' blame incentive (neutral, self-protective) and the investigator's trace access (full trace
verification, claims only) affect root-cause attribution accuracy, false-blame rate and rounds to a
stable correct attribution?

Hypotheses H1-H6 with decision rules are in [`HYPOTHESES.md`](HYPOTHESES.md), committed before any run
(see `git log`). In brief:

- **H1** trace access raises accuracy by >= 0.10 under self-protective incentive.
- **H2** trace access at least halves false blame (converting it to abstention).
- **H3** self-protective incentive raises false blame by >= 0.10 under claims-only, but <= 0.05 with access.
- **H4** latency ordering flat <= hub <= chain in mean steps-to-attribution.
- **H5** chain relay distortion costs >= 0.10 accuracy versus flat (competes with H6).
- **H6** a verifying hub mediator gains >= 0.05 accuracy over flat.

## Design

| | |
|---|---|
| Independent variables | topology {flat, hub, chain}; incentive {neutral, self_protective}; access {full, claims_only} |
| Dependent variables | accuracy (final attribution = culprit); false-blame rate (final = an innocent agent); abstain rate; steps-to-attribution (first round from which attribution stays correct to the deadline); messages |
| Controls | 4 fixed scenarios with fixed traces; fixed agent roster; fixed parameters (witness p 0.35, fabricate p 0.5, chain drop p 0.15, budget 1 check/round, deadline 5); common random numbers across cells |
| Repetitions | seeds 0..49 x 4 scenarios = 200 paired units per cell, 12 cells, 2400 runs |
| Analysis | Wilson 95% intervals; paired exact two-sided sign test on discordant pairs; alpha 0.01; decision rules fixed in HYPOTHESES.md |

## Layout

```
whobrokeprod/
  simulation/scenarios.py      fixed seeded incidents + ground-truth trace; trace-only support check
  agents/rule_agents.py        deterministic agents: confess / deflect / witness / scapegoat / shrug
  agents/grok_narrator.py      optional Grok postmortem narration (off unless --grok and XAI_API_KEY)
  orchestration/topologies.py  flat, hub (IncidentCommander), chain (relay with distortion)
  evaluation/investigator.py   verification-budgeted investigator + scoring
  evaluation/stats.py          Wilson interval, exact sign test (stdlib)
  evaluation/experiment.py     the preregistered grid and H1-H6 decision rules
  presentation/cli.py          `demo` and `experiment` commands
tests/                         deterministic pytest suites (no network)
web/                           static frontend + offline bundle (web/data)
HYPOTHESES.md                  preregistration
results/                       runs.csv, summary.json (written by `experiment`)
```

## Run

```bash
uv venv -p 3.11 .venv && uv pip install -p .venv/bin/python pytest   # stdlib-only otherwise
.venv/bin/python -m pytest -q
.venv/bin/python -m whobrokeprod demo --scenario bad_deploy --topology chain --seed 3
.venv/bin/python -m whobrokeprod experiment --out results
# optional, costs an API call, never used for attribution or experiments:
XAI_API_KEY=... .venv/bin/python -m whobrokeprod demo --grok
```

## Web demo

A visualisation layer over the same simulator. JavaScript only renders; all claims, checks,
attributions and verdicts come from `whobrokeprod` (`presentation/replay.py`).

```bash
.venv/bin/python -m whobrokeprod.presentation.server --port 8000   # live mode: http://127.0.0.1:8000
.venv/bin/python -m whobrokeprod.presentation.build_static          # rebuild web/data (offline bundle)
python3 -m http.server -d web 8001                                  # offline/static mode, no Python API
```

- Endpoints: `/api/meta`, `/api/case`, `/api/investigate`, `/api/verdict` with
  `scenario`, `topology` and optional `seed` (0..10000), `incentive`, `access`. Bad input returns HTTP 400
  JSON. The UI uses the defaults (self-protective, full access, seed 7). `?autoplay=1` runs the whole sequence.
- Reveal stages: `case` (incident, agents, log, claims, stances hidden) -> `investigate` (the
  investigator's checks and per-claim evidence status) -> `verdict` (culprit, root cause, correctness).
  Tests check that no ground-truth field appears before the verdict.
- Offline mode: if `/api/meta` is unreachable the page loads `web/data/` (4 scenarios x 3 topologies).
  **Limitation:** on a static host, `data/verdicts/*.json` are public URLs, so anyone can open a verdict early.
  The claim lines are the simulator's scripted templates. SEV-1 framing, clock styling and corrective actions
  are presentation copy and are labelled as such. The research lab reads `results/summary.json` (via
  `web/data/research.json`) and does not rerun the experiment.
- Deploy: `web/` is a self-contained static site (GitHub Pages, Netlify, etc.). `Dockerfile` runs live
  mode on a container host (`PORT` env). No credentials are needed; the Grok narrator is not wired to the web.

## Where Grok fits

Attribution, agents and scoring are deterministic so that results reproduce. Grok is used only to turn
a computed verdict into a readable postmortem paragraph in the demo. A natural follow-up is a separate,
preregistered arm where LLM agents replace the rule-based agents, run at temperature 0 with logged
outputs; the lab's own `org_frontier/llm_variance/` warns that N model responses are not N independent
observations, which that arm would need to account for.

## Limitations

- Evidence about this simulator only. Nothing here measures real incident response, real engineers, or
  real organisations, and no result should be read as generalising to production environments.
- Several effects are partly built in (for example, claims-only investigators cannot verify anything).
  The experiment checks whether the specified mechanisms produce effects of the stated size.
- The investigator's decision rule (support > plurality of non-refuted claims > abstain on ties) and all
  parameters were chosen by the designer; other reasonable choices may change results.
- Agent behaviour is scripted; there is no learning, persuasion or LLM variance.
- Association across designed conditions only, on 4 hand-built scenarios.

## Relation to algorithmacy-lab, and follow-up for integration

This prototype lives outside the lab and does not modify its exact-Φ instrument. It does **not** compute
Φ, and its accuracy numbers are not Φ results. The lab's closest existing work is the AI/multi-agent arc
(`org_frontier/AI_MULTIAGENT_ARC.md`, probe #88 `org_frontier/probes/probe_mas.py`, studies
`agent_protocol_triad/` and `hitl_rubber_stamp/`), which shows on small Boolean models that a protocol or
mediator joins the irreducible core only when it both *commits* a determination and is *read* by the
parties (COMMIT_READ); relay and broadcast protocols read dyadic.

Smallest defensible integration (a separate PR into `contrib`, not done here):

1. Add `org_frontier/studies/incident_topology_phi/` (README.md, hypotheses.md committed first,
   analyze_*.py, FINDINGS.md, results/), following the existing study layout.
2. Encode each topology's *coordination step* as a 3-6 node Boolean form, for example flat =
   independent reporters, hub-convey = mediator copies reports, hub-commit = mediator's next state is a
   joint function of reports that agents then read, chain = relay. Compute the verdict and major complex
   with `org_frontier.probes.lib.verdict` / `major_complex` after the instrument control
   (`python -m org_frontier.classifier.validate`).
3. Pre-register whether Φ-triadic topologies coincide with higher simulated attribution accuracy, and
   report a null if they do not. Register printed numbers in `ci/reproduce.json`, run
   `python ci/reproduce.py`, and the three `--check` index generators.
4. State the validation gap: evidence about models, not organisations.

The lab's CI uses Python 3.12 and PyPhi needs 3.10+; this prototype targets 3.11 and is stdlib-only, so
it runs under either.

## Results of the preregistered run (2400 runs, `results/summary.json`)

Self-protective cells (neutral cells are all accuracy 1.000, since the culprit confesses):

| topology | access | accuracy [95% CI] | false blame | abstain | mean steps |
|---|---|---|---:|---:|---:|
| flat | full | 0.775 [0.712, 0.827] | 0.225 | 0.000 | 1.48 |
| flat | claims_only | 0.130 [0.090, 0.184] | 0.760 | 0.110 | 1.00 |
| hub | full | 0.775 [0.712, 0.827] | 0.225 | 0.000 | 2.07 |
| hub | claims_only | 0.130 [0.090, 0.184] | 0.760 | 0.110 | 2.00 |
| chain | full | 0.390 [0.325, 0.459] | 0.580 | 0.030 | 1.50 |
| chain | claims_only | 0.030 [0.014, 0.064] | 0.970 | 0.000 | 1.33 |

- H1 supported (accuracy 0.647 vs 0.097, diff 0.55, sign test p ~ 9e-100).
- H2 supported (false blame 0.343 vs 0.830).
- H3 refuted: the incentive raises false blame under full access too (+0.343, threshold 0.05). Cause in
  this design: claims citing no event cannot be refuted, and the investigator falls back to a plurality
  over them once cited scapegoat claims are refuted.
- H4 refuted: chain (1.50) beat hub (2.07) on mean steps. Steps are averaged over successful runs only,
  so chain's mean is selection-biased toward runs where a nearby witness reported early.
- H5 supported (flat 0.775 vs chain 0.390, p ~ 1e-23).
- H6 refuted: hub accuracy equals flat (diff 0, p = 1). The mediator's single check duplicates the check
  the investigator makes first anyway, so it adds a round and no accuracy.
