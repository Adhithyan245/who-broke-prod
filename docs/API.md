# HTTP API

Stdlib server: `python -m whobrokeprod.presentation.server`. All endpoints are `GET` (and `HEAD`), read-only,
unauthenticated, and deterministic for the same parameters. No credentials are read.

| Endpoint | Purpose | Returns |
|---|---|---|
| `/healthz` | liveness + presence of `web/index.html` and `results/summary.json` | `{"status":"ok"\|"degraded","version","checks":{...}}` |
| `/api/meta` | scenarios, topologies (note + graph), defaults, deadline, budget, decision-reason texts | JSON |
| `/api/case` | stage 1: incident, agents (role, role_text), event log, claims (no stances), transcript, topology graph | JSON |
| `/api/investigate` | stage 2: per-round checks, attribution + reason per round, deliveries (`via`), per-claim check status, `final_reason_text` | JSON |
| `/api/verdict` | stage 3: culprit, root-cause and red-herring events, correctness, corrective action (presentation copy) | JSON |
| `/api/export?format=json\|csv` | evaluation export derived read-only from `results/` | JSON or `text/csv` |

## Replay parameters (`/api/case`, `/api/investigate`, `/api/verdict`)

| Param | Required | Values | Default |
|---|---|---|---|
| `scenario` | yes | `bad_deploy`, `flag_flip`, `migration_lock`, `cache_stampede` | – |
| `topology` | yes | `flat`, `hub`, `chain` | – |
| `incentive` | no | `neutral`, `self_protective` | `self_protective` |
| `access` | no | `full`, `claims_only` | `full` |
| `seed` | no | integer 0–10000 | `7` |

Unknown parameters are rejected (400), so a typo cannot silently fall back to a default.

## Errors

One shape for every error:

```json
{"error": {"code": "invalid_parameter", "message": "scenario must be one of [...]", "field": "scenario"}, "request_id": "3f2a..."}
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `invalid_parameter` | missing/unknown/invalid parameter (`field` names it) |
| 404 | `not_found` | unknown `/api/*` path |
| 503 | `results_unavailable` | `/api/export` when `results/runs.csv` or `summary.json` is missing |
| 500 | `internal_error` | unexpected exception (no traceback is returned; it is logged) |

## Request ids and logs

Send `X-Request-ID` (`[A-Za-z0-9._-]{1,64}`) to have it echoed; otherwise the server generates one. Every
response carries `X-Request-ID`. One JSON line per request goes to stderr:

```json
{"ts": "2026-10-09T12:06:18-0400", "level": "INFO", "event": "request", "request_id": "...", "method": "GET", "path": "/api/verdict", "status": 200, "duration_ms": 0.51}
```

## Configuration (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `WBP_HOST` | `127.0.0.1` | use `0.0.0.0` in containers |
| `WBP_PORT` / `PORT` | `8000` | `WBP_PORT` wins; must be an integer 0–65535 |
| `WBP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `WBP_WEB_DIR` | `<repo>/web` | static files |
| `WBP_RESULTS_DIR` | `<repo>/results` | saved experiment results for `/api/export` |
| `XAI_API_KEY` | unset | CLI `demo --grok` only; never used by the server, tests or experiment |

## Export contents

`run_count`, `config` (grid, seeds, simulator parameters), `cells` (the 12 summary cells), `hypotheses`, `per_scenario` (48 cells of 50 runs:
accuracy, false_blame, abstain, mean_steps, n_steps, mean_messages), `reproducibility`
(`summary_matches_runs`, mismatches, SHA-256 fingerprints of `runs.csv`, `summary.json`, `HYPOTHESES.md`,
preregistration commit URLs), `raw_results` links, and `execution_timing: null` (the saved run was not timed).
The CSV form contains the `per_scenario` table only. The CLI equivalent is
`python -m whobrokeprod export --format json|csv [--out path]`.
