# WHO BROKE PROD?

**Live demo (static, offline mode):** https://adhithyan245.github.io/who-broke-prod-demo/

## 1. Project purpose and key capabilities

A deterministic multi-agent incident-investigation simulator. Five rule-based agents (DeployBot, ConfigBot,
AutoScaler, DBMigrator, CacheBot) are asked who caused a simulated outage; most blame someone else. An
investigator reconstructs the root cause from their claims and, when allowed, by checking cited entries
against the event trace. The comedy is in the transcript; the measurement is in the scoring.

It is a simulation only: no real systems, customer data or destructive actions, and no network calls by
default.

Capabilities (all exercised by the test suite or the commands below):

- 4 fixed scenarios (`bad_deploy`, `flag_flip`, `migration_lock`, `cache_stampede`) × 3 topologies
  (`flat`, `hub` with an IncidentCommander, `chain` relay) × 2 incentives × 2 evidence-access levels, all
  seeded and reproducible.
- A preregistered 2,400-run experiment (`HYPOTHESES.md`, `results/`) with Wilson intervals and paired sign tests.
- A stdlib HTTP API with a staged reveal (case → investigate → verdict), `/healthz`, one JSON error shape,
  request ids and structured JSON logs.
- A vanilla HTML/CSS/JS web app: incident workspace, SVG topology, agent profiles, evidence timeline,
  investigation trace (including EVIDENCE NOT FOUND), verdict with the investigator's actual decision
  reason, evaluation lab and methodology. It runs live against the API or offline from a static bundle.
- A read-only evaluation export (JSON/CSV) with SHA-256 fingerprints of the saved results.
- A terminal demo CLI. Optional Grok narration is off by default, never used in tests or scoring, and its
  output is never authoritative.

## 2. Screenshot / visual preview

![Incident workspace, topology, trace and verdict (headless Chrome, live mode, bad_deploy/hub autoplay)](docs/screenshot.png)

## 3. Architecture and component responsibilities

The layers are separated as `simulation` → `agents` → `orchestration` → `evaluation` → `presentation`. The
browser only renders: every claim, check, attribution, reason and verdict is computed in Python. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the mermaid diagram.

| Component | Responsibility |
|---|---|
| `simulation/scenarios.py` | fixed incidents and ground-truth event trace; trace-only support check |
| `agents/rule_agents.py` | deterministic claims: confess / deflect / witness / scapegoat / shrug |
| `agents/grok_narrator.py` | optional postmortem narration (CLI `--grok` + `XAI_API_KEY` only) |
| `orchestration/topologies.py` | message delivery: flat, hub (verifying mediator), chain (relay with distortion) |
| `evaluation/investigator.py` | budgeted verification, decision reasons, scoring |
| `evaluation/experiment.py`, `stats.py` | preregistered grid, H1–H6 decision rules, Wilson CI, sign test |
| `evaluation/export.py` | read-only export of `results/` with fingerprints |
| `contracts.py`, `config.py` | typed request/response dataclasses; environment configuration |
| `presentation/replay.py` | staged reveal payloads and presentation copy |
| `presentation/server.py` | HTTP API, static files, JSON logs, request ids |
| `presentation/build_static.py` | offline bundle `web/data` (`--check` detects staleness) |
| `presentation/cli.py` | `demo`, `experiment`, `export` |
| `web/` | frontend + offline bundle |

## 4. Quick start

Requires Python 3.11+. The runtime is stdlib-only; pytest and ruff are dev tools.

```bash
uv venv -p 3.11 .venv
uv pip install -p .venv/bin/python -e ".[dev]"      # or: python3.11 -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q                       # 67 passed
.venv/bin/ruff check .                              # All checks passed!
.venv/bin/python -m whobrokeprod demo --scenario bad_deploy --topology chain --seed 3
WBP_PORT=8000 .venv/bin/python -m whobrokeprod.presentation.server   # http://127.0.0.1:8000 (live mode)
python3 -m http.server -d web 8001                  # http://127.0.0.1:8001 (offline mode, no API)
```

Container (live API mode): a `Dockerfile` is provided (stdlib-only, runs as `nobody`, `HEALTHCHECK` on
`/healthz`, honours `PORT`). **Docker is untested:** no Docker engine was available, so the image has not
been built. The intended usage is `docker build -t who-broke-prod . && docker run --rm -p 8000:8000 who-broke-prod`.

## 5. Deterministic demo walkthrough (judge sequence)

With the live server running on port 8000:

1. `curl -s localhost:8000/healthz` → `{"status": "ok", "version": "0.2.0", ...}`
2. Open `http://127.0.0.1:8000/?scenario=bad_deploy&topology=flat`, press **INVESTIGATE INCIDENT**, then
   **REVEAL VERDICT**. The verdict's *Why* line is the investigator's real decision reason.
3. Open `http://127.0.0.1:8000/?scenario=bad_deploy&topology=chain&autoplay=1`. Relayed claims are altered
   in transit, citations to non-existent log entries are marked **EVIDENCE NOT FOUND**, and the
   investigator blames an innocent agent. In the terminal,
   `.venv/bin/python -m whobrokeprod demo --scenario bad_deploy --topology chain --seed 3` ends with
   `VERDICT: investigator named AutoScaler -> WRONG - innocent agent blamed`.
4. In **Evaluation lab**, toggle *full trace access* ↔ *claims only* to compare the scenario × topology
   matrix. These figures come from the saved results; nothing is rerun.
5. `curl -s "localhost:8000/api/case?scenario=nope&topology=hub"` → HTTP 400,
   `{"error": {"code": "invalid_parameter", ..., "field": "scenario"}, "request_id": "..."}`
6. `curl -s "localhost:8000/api/export?format=csv" | head -3` and
   `.venv/bin/python -m whobrokeprod export --format json | grep -E 'run_count|summary_matches_runs'`
   → `"run_count": 2400`, `"summary_matches_runs": true`.
7. Offline: `python3 -m http.server -d web 8001`; the badge reads *OFFLINE · static bundle*.

The same parameters always give the same `replay_hash` shown in the workspace header. No credentials are needed.

## 6. API usage and configuration

The full reference is in [docs/API.md](docs/API.md).

| Endpoint | Returns |
|---|---|
| `GET /healthz` | status and checks for `web/index.html` and `results/summary.json` |
| `GET /api/meta` | scenarios, topologies (note + graph), defaults, decision-reason texts |
| `GET /api/case` · `/api/investigate` · `/api/verdict` | staged replay; `scenario`, `topology` required; `incentive`, `access`, `seed` (0–10000) optional; unknown parameters → 400 |
| `GET /api/export?format=json\|csv` | read-only evaluation export (503 `results_unavailable` if results are missing) |

Errors use the shape `{"error": {"code", "message", "field"?}, "request_id"}`. Send `X-Request-ID`
(`[A-Za-z0-9._-]{1,64}`) to have it echoed in the response; otherwise the server generates one. Each request
writes one JSON log line to stderr.

| Environment variable | Default | Purpose |
|---|---|---|
| `WBP_HOST` | `127.0.0.1` | bind address (`0.0.0.0` in containers) |
| `WBP_PORT` / `PORT` | `8000` | port; `WBP_PORT` wins; integer 0–65535 |
| `WBP_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `WBP_WEB_DIR` | `<repo>/web` | static files |
| `WBP_RESULTS_DIR` | `<repo>/results` | saved results for the export |
| `XAI_API_KEY` | unset | only for CLI `demo --grok`; never read by the server, tests or experiment |

## 7. Testing and reproducibility

- `.venv/bin/python -m pytest -q` runs 67 deterministic tests with no network access and no Grok calls. They
  cover simulator invariants, the H1–H6 decision rules, the staged reveal and no-ground-truth-leak checks,
  API validation and error shape, `/healthz`, the export (JSON, CSV, 503 when results are missing),
  request-id echo and JSON logs, config parsing, CLI export, and bundle freshness.
- **Regression check:** seeds 0–4 of all 48 cells (240 runs) are rerun and compared with the saved `results/runs.csv`.
- `.venv/bin/python -m whobrokeprod.presentation.build_static --check` exits 1 if `web/data` is stale.
- The export re-derives `summary.json` cells from `runs.csv` and fingerprints both files and `HYPOTHESES.md`
  (SHA-256), with links to the preregistration commits. Execution time was not measured for the saved run
  and is reported as `null`.
- The full grid regenerates with `.venv/bin/python -m whobrokeprod experiment --out <dir>`. It was not
  rerun during the platform upgrade (only the 240-run sample), so write to a separate directory to compare.
- **CI:** `.github/workflows/ci.yml` runs ruff, pytest and the bundle check on Python 3.11. Run
  [37957574809](https://github.com/Adhithyan245/who-broke-prod/actions/runs/37957574809) passed on push of
  this branch: ruff clean, pytest 67 passed, bundle fresh.

## 8. Evaluation metrics and limitations

The preregistered design (`HYPOTHESES.md`, committed before any run):

- **Variables:** topology × incentive × access.
- **Controls:** 4 fixed scenarios and fixed parameters (witness p 0.35, fabricate p 0.5, chain drop p 0.15,
  1 check per round, 5-round deadline), with common random numbers across cells.
- **Sample:** 50 seeds × 4 scenarios = 200 paired units per cell; 12 cells; 2,400 runs.
- **Analysis:** Wilson 95% intervals and an exact paired sign test, α = 0.01.

| Metric | Definition | Denominator |
|---|---|---|
| Accuracy | the round-5 attribution names the culprit | all runs in the cell |
| False blame | the round-5 attribution names an innocent agent | all runs in the cell |
| Abstain | no attribution at round 5 | all runs in the cell |
| Steps to attribution | first round from which attribution stays correct | successful runs only (selection-biased) |
| Messages | messages delivered to the investigator | all runs in the cell |

Self-protective cells from `results/summary.json`. Every neutral cell has accuracy 1.000 because the culprit confesses:

| topology | access | accuracy [95% CI] | false blame | abstain | mean steps |
|---|---|---|---:|---:|---:|
| flat | full | 0.775 [0.712, 0.827] | 0.225 | 0.000 | 1.48 |
| flat | claims_only | 0.130 [0.090, 0.184] | 0.760 | 0.110 | 1.00 |
| hub | full | 0.775 [0.712, 0.827] | 0.225 | 0.000 | 2.07 |
| hub | claims_only | 0.130 [0.090, 0.184] | 0.760 | 0.110 | 2.00 |
| chain | full | 0.390 [0.325, 0.459] | 0.580 | 0.030 | 1.50 |
| chain | claims_only | 0.030 [0.014, 0.064] | 0.970 | 0.000 | 1.33 |

Hypothesis outcomes:

- **H1 supported:** trace access raises accuracy (0.647 vs 0.097).
- **H2 supported:** trace access lowers false blame (0.343 vs 0.830).
- **H3 refuted:** the self-protective incentive also raises false blame under full access, because
  uncited claims cannot be refuted.
- **H4 refuted:** chain was faster than hub on mean steps, a selection-biased mean.
- **H5 supported:** chain relay costs accuracy (flat 0.775 vs chain 0.390).
- **H6 refuted:** hub accuracy equals flat, because the mediator's check duplicates the investigator's.

Limitations:

- This is evidence about this simulator only. It says nothing about real incident response, engineers or
  organisations.
- Several effects are partly built in; for example, a claims-only investigator cannot verify anything.
- The parameters and the decision rule (support > plurality of unrefuted claims > abstain on ties) were
  chosen by the designer.
- Agent lines are scripted templates. There is no learning, persuasion or LLM variance.
- The results cover 4 hand-built scenarios and show association across designed conditions only.
- In the web app, SEV framing and corrective actions are labelled presentation copy, and dialogue is
  labelled simulated.

## 9. Security considerations

- **No credentials anywhere in the repository.** The only secret the code knows about is `XAI_API_KEY`,
  read from the environment by the optional CLI narrator. It is off by default and never used by the
  server, tests or experiment.
- **Read-only endpoints.** All endpoints are unauthenticated `GET`/`HEAD`, nothing writes to disk, and
  replay parameters are validated against allow-lists with bounded seeds. Unknown parameters are rejected.
- **No leaked internals.** Unexpected exceptions return a generic `internal_error` and are logged with the
  request id; tracebacks are never sent to clients. Client-supplied request ids are pattern-checked before
  being echoed or logged.
- **Security headers.** Responses set `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.
  There is no Content-Security-Policy yet.
- **Container user.** The container runs as `nobody` with no package installs.
- **Public verdicts on static hosts.** On a static host the verdict files (`web/data/verdicts/*.json`) are
  public, so the reveal can be skipped. This leaks the game, not data: everything is synthetic.
- **No rate limiting or TLS.** Put the server behind a reverse proxy before exposing it publicly.

## 10. Research-study links, and product vs research

- **Research:** the preregistered experiment is packaged as an algorithmacy-lab study in
  [PR #809](https://github.com/rogerSuperBuilderAlpha/algorithmacy-lab/pull/809), from the fork branch
  [Adhithyan245/algorithmacy-lab@study/who-broke-prod](https://github.com/Adhithyan245/algorithmacy-lab/tree/study/who-broke-prod):
  - [`org_frontier/studies/who_broke_prod/`](https://github.com/Adhithyan245/algorithmacy-lab/tree/study/who-broke-prod/org_frontier/studies/who_broke_prod):
    hypotheses, analysis of the saved 2,400 runs, FINDINGS.
  - [`org_frontier/studies/who_broke_prod_phi/`](https://github.com/Adhithyan245/algorithmacy-lab/tree/study/who-broke-prod/org_frontier/studies/who_broke_prod_phi):
    a separate, preregistered exact-Φ (IIT 4.0) study of small Boolean models of each topology's
    coordination step. Φ is evidence about those models, not about real organisations, and is not
    derived from the accuracy numbers here.
- **Product:** this repository (API, web app, export, CI, container) is a presentation and engineering
  layer over the same deterministic simulator. It adds no findings. `HYPOTHESES.md` and `results/` are the
  preregistered artefacts and are unchanged by the platform work. Numbers in the UI's evaluation lab are
  read from those saved results, and everything else in the UI is labelled simulated or presentation copy.
