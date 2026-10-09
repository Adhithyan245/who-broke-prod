# Architecture

```mermaid
flowchart LR
  subgraph simulation [simulation]
    SC[scenarios.py<br/>fixed incidents + event trace]
  end
  subgraph agents [agents]
    RA[rule_agents.py<br/>deterministic claims]
    GN[grok_narrator.py<br/>optional, off by default, CLI only]
  end
  subgraph orchestration [orchestration]
    TP[topologies.py<br/>flat / hub / chain delivery]
  end
  subgraph evaluation [evaluation]
    IV[investigator.py<br/>budgeted checks + decide reasons]
    EX[experiment.py<br/>preregistered grid, H1-H6]
    ST[stats.py<br/>Wilson, sign test]
    XP[export.py<br/>read-only export + fingerprints]
  end
  subgraph presentation [presentation]
    RP[replay.py<br/>case → investigate → verdict]
    SV[server.py<br/>/healthz /api/*]
    BS[build_static.py<br/>web/data bundle + --check]
    CLI[cli.py<br/>demo / experiment / export]
  end
  R[(results/<br/>runs.csv, summary.json)]
  W[web/<br/>index.html, app.js, styles.css]
  D[(web/data<br/>offline bundle)]

  SC --> RA --> TP --> IV
  IV --> EX --> R
  ST --> EX
  R --> XP
  IV --> RP
  RP --> SV
  XP --> SV
  RP --> BS
  XP --> BS --> D
  SV -- live JSON --> W
  D -- offline JSON --> W
  CLI --> EX
  CLI --> XP
  GN -.-> CLI
```

Layering rules:

- `simulation`, `agents`, `orchestration` and `evaluation` never import `presentation`.
- The browser only renders. Every claim, check, attribution, reason and verdict is computed in Python
  (live via `server.py`, or precomputed into `web/data` by `build_static.py`).
- Ground truth is staged: `case` carries no stances or culprit; `investigate` adds check results;
  only `verdict` names the culprit. On a static host the verdict files are public URLs (documented limitation).
- `export.py` and the lab view read saved results; nothing in the web path reruns the 2,400-run experiment.
- `contracts.py` holds typed request/response contracts (`ReplayParams`, `ApiError`, `Health`); `config.py`
  holds environment configuration.
