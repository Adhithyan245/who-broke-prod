"use strict";
// Rendering only. Every value shown comes from the Python simulator via /api/* (live) or the pre-built
// JSON bundle in data/ (offline). No simulation, verification or scoring happens in this file.
const $ = (id) => document.getElementById(id);
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));
const SVGNS = "http://www.w3.org/2000/svg";
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined) n.append(c instanceof Node ? c : String(c));
  return n;
}
function svg(tag, attrs = {}, text) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
}
const S = { mode: null, meta: null, case: null, inv: null, verdict: null, run: 0, selected: null,
            scenario: null, topology: "hub", research: null, labAccess: "full" };

async function getJSON(url) {
  let r;
  try { r = await fetch(url, { cache: "no-store" }); } catch { throw new Error(`network error loading ${url}`); }
  let body = null;
  try { body = await r.json(); } catch { throw new Error(`unreadable response from ${url} (HTTP ${r.status})`); }
  if (!r.ok) {
    const e = body && body.error;
    throw new Error(e ? `${e.message}${body.request_id ? ` [request ${body.request_id}]` : ""}` : `HTTP ${r.status} for ${url}`);
  }
  return body;
}
let retryFn = null;
function showError(msg, retry = null) {
  $("error-msg").textContent = msg || ""; $("error").hidden = !msg; retryFn = retry; $("retry").hidden = !retry;
}
const params = () => ({ scenario: S.scenario, topology: S.topology });
const qs = (p) => new URLSearchParams(p).toString();
const key = (p) => `${p.scenario}__${p.topology}`;
const bundleCache = {};
async function bundle(p) { return bundleCache[key(p)] ||= await getJSON(`data/cases/${key(p)}.json`); }
const api = {
  case: async (p) => S.mode === "live" ? getJSON(`/api/case?${qs(p)}`) : (await bundle(p)).case,
  investigate: async (p) => S.mode === "live" ? getJSON(`/api/investigate?${qs(p)}`) : (await bundle(p)).investigation,
  verdict: async (p) => S.mode === "live" ? getJSON(`/api/verdict?${qs(p)}`) : getJSON(`data/verdicts/${key(p)}.json`),
};

// Accessible radio group built from buttons: arrow keys move, Enter/Space/click select.
function radioGroup(container, items, current, onPick) {
  container.replaceChildren();
  const btns = items.map((it) => el("button", { type: "button", role: "radio", class: it.cls || "",
    "aria-checked": String(it.id === current), tabindex: it.id === current ? "0" : "-1",
    onclick: () => onPick(it.id) }, ...(it.kids || [it.label])));
  container.addEventListener("keydown", (e) => {
    const i = btns.indexOf(document.activeElement);
    if (i < 0 || !["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(e.key)) return;
    e.preventDefault();
    const j = (i + (e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1) + btns.length) % btns.length;
    btns[j].focus(); btns[j].click();
  });
  container.append(...btns);
}
function markRadio(container, id) {
  for (const b of container.querySelectorAll("[role=radio]")) {
    const on = b.dataset.id === id; b.setAttribute("aria-checked", String(on)); b.tabIndex = on ? 0 : -1;
  }
}

async function init() {
  $("retry").onclick = () => retryFn && retryFn();
  try { S.meta = await getJSON("/api/meta"); S.mode = "live"; }
  catch {
    try { S.meta = await getJSON("data/meta.json"); S.mode = "offline"; }
    catch { showError("No data source: the API is unreachable and the offline bundle (data/meta.json) is missing.", init); return; }
  }
  showError("");
  $("mode").textContent = S.mode === "live" ? "LIVE · Python API" : "OFFLINE · static bundle";
  $("mode").className = `pill ${S.mode === "live" ? "live" : "off"}`;
  const u = new URLSearchParams(location.search);
  const ids = S.meta.scenarios.map((s) => s.id), tops = S.meta.topologies.map((t) => t.id);
  S.scenario = ids.includes(u.get("scenario")) ? u.get("scenario") : ids[0];
  S.topology = tops.includes(u.get("topology")) ? u.get("topology") : "hub";
  if ((u.get("scenario") && !ids.includes(u.get("scenario"))) || (u.get("topology") && !tops.includes(u.get("topology"))))
    showError("Unknown scenario or topology in the URL; showing the default instead.");
  radioGroup($("incidents"), S.meta.scenarios.map((s) => ({ id: s.id, cls: "incident",
    kids: [el("b", {}, s.title), el("span", {}, `${s.id} · ${s.service}`)] })), S.scenario,
    (id) => { S.scenario = id; load(); });
  radioGroup($("topology"), tops.map((t) => ({ id: t, label: t })), S.topology, (id) => { S.topology = id; load(); });
  for (const g of ["incidents", "topology"]) [...$(g).children].forEach((b, i) => { b.dataset.id = (g === "incidents" ? ids : tops)[i]; });
  $("reset").onclick = load;
  $("replay").onclick = async () => { await load(); await investigate(); };
  $("investigate").onclick = investigate;
  $("reveal").onclick = reveal;
  renderMethod();
  renderLab();
  await load();
  if (u.get("autoplay") === "1") { await investigate(); await reveal(); }  // judge/kiosk mode
}

function setStatus(s) { $("status").textContent = s.toUpperCase(); $("status").className = `v st-${s}`; }
const emptyLi = (t) => el("li", { class: "empty" }, t);

async function load() {
  const run = ++S.run;
  showError(""); S.inv = S.verdict = S.selected = null;
  markRadio($("incidents"), S.scenario); markRadio($("topology"), S.topology);
  $("verdict").hidden = true; $("reveal").disabled = true; $("investigate").disabled = true;
  $("dialogue").replaceChildren(emptyLi("Press INVESTIGATE INCIDENT to play the claims."));
  $("checks").replaceChildren(emptyLi("Not started.")); $("deliveries").replaceChildren(emptyLi("Not started."));
  $("contra").textContent = "Not started.";
  $("workspace").setAttribute("aria-busy", "true"); $("cmd-h").textContent = "Loading incident…";
  const p = params();
  history.replaceState(null, "", `?${qs(p)}${location.hash}`);
  try { S.case = await api.case(p); }
  catch (e) { if (run === S.run) { showError(`Could not load case: ${e.message}`, load); $("cmd-h").textContent = "Incident unavailable"; } return; }
  finally { $("workspace").removeAttribute("aria-busy"); }
  if (run !== S.run) return;
  const c = S.case;
  $("cmd-h").textContent = c.incident.title;
  $("svc").textContent = c.incident.service;
  $("clock").textContent = `t=${c.incident.first_alert_t} · first alert`;
  $("ind-agents").textContent = "0";
  $("ind-evidence").textContent = c.log.length;
  $("ind-claims").textContent = c.claims.filter((x) => x.accused).length;
  $("hash").textContent = `deterministic · seed ${c.params.seed} · ${c.replay_hash}`;
  setStatus("unresolved");
  renderTopology(); renderAgents(); renderTimeline(); renderDetail();
  $("investigate").disabled = false;
}

function renderTopology(active = null) {
  const g = S.case.graph, t = S.meta.topologies.find((x) => x.id === S.topology);
  $("topo-name").textContent = `· ${S.topology}`; $("topo-note").textContent = t ? t.note : "";
  const W = 420, H = 230, bw = 92, bh = 24, pos = {};
  const agents = g.nodes.filter((n) => n.kind === "agent");
  agents.forEach((n, i) => {
    pos[n.id] = S.topology === "chain" ? [16 + i * 66, 20 + i * 38] : [16, 14 + i * 42];
  });
  const med = g.nodes.find((n) => n.kind === "mediator");
  if (med) pos[med.id] = [170, 98];
  pos.Investigator = S.topology === "chain" ? [312, 196] : [312, 98];
  const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  const defs = svg("defs"); const m = svg("marker", { id: "arr", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" });
  m.append(svg("path", { d: "M0 0L10 5L0 10z", fill: "#5b6474" })); defs.append(m); s.append(defs);
  for (const [a, b] of g.edges) {
    const [x1, y1] = pos[a], [x2, y2] = pos[b];
    s.append(svg("path", { class: "edge", "marker-end": "url(#arr)",
      d: `M${x1 + bw} ${y1 + bh / 2} C${(x1 + bw + x2) / 2} ${y1 + bh / 2} ${(x1 + bw + x2) / 2} ${y2 + bh / 2} ${x2} ${y2 + bh / 2}` }));
  }
  for (const n of g.nodes) {
    const [x, y] = pos[n.id], gg = svg("g", { class: `n ${n.kind}${active === n.id ? " on" : ""}` });
    gg.append(svg("rect", { x, y, width: bw, height: bh, rx: 5 }), svg("text", { x: x + 8, y: y + 16 }, n.id));
    s.append(gg);
  }
  $("topo-svg").replaceChildren(s);
}

function claimOf(name) { return S.case.claims.find((c) => c.speaker === name); }
function invClaim(i) { return S.inv ? S.inv.claims.find((c) => c.i === i) : null; }

function renderAgents(speaking = new Set(), said = {}) {
  const rows = S.case.agents.map((a) => ({ ...a, kind: "agent" }))
    .concat(S.case.relays.map((r) => ({ name: r, role: "mediator", role_text: "Collects claims, checks one, forwards (hub only)", kind: "relay" })),
            [{ name: "Investigator", role: "investigator", role_text: `Checks ${S.meta.verification_budget} citation per round for ${S.meta.deadline_rounds} rounds`, kind: "inv" }]);
  $("agents").replaceChildren(...rows.map((a) => {
    const c = a.kind === "agent" ? claimOf(a.name) : null, ic = c ? invClaim(c.i) : null;
    const tags = [];
    if (ic) tags.push(el("span", { class: `tag ${ic.check}` }, `own claim: ${ic.check}`));
    if (ic && ic.cited_event_found === false) tags.push(el("span", { class: "tag nf" }, "EVIDENCE NOT FOUND"));
    if (a.kind === "agent") tags.push(el("span", { class: "tag" }, `accused by ${S.case.claims.filter((x) => x.accused === a.name).length}`));
    const line = said[a.name] || (a.kind === "inv" && S.inv ? `Final attribution: ${S.inv.final_attribution || "insufficient evidence"}` : "—");
    return el("article", { class: `agent${speaking.has(a.name) ? " speaking" : ""}`, "aria-label": `${a.name}, ${a.role}` },
      el("b", {}, a.name), el("span", { class: "role" }, `${a.role} · ${a.role_text}`),
      el("p", { class: "said" }, line), el("div", {}, tags));
  }));
}

function claimLabel(c) { return `${c.speaker} → ${c.accused || "nobody"}${c.cites ? ` (cites ${c.cites})` : " (no citation)"}`; }
function claimButton(c) {
  const ic = invClaim(c.i);
  const b = el("button", { type: "button", class: "claimbtn", "aria-pressed": String(S.selected === c.i),
    onclick: () => { S.selected = c.i; renderTimeline(); renderDetail(); $("detail").focus?.(); } }, claimLabel(c));
  if (ic) b.append(" ", el("span", { class: `tag ${ic.check}` }, ic.check));
  if (ic && ic.cited_event_found === false) b.append(" ", el("span", { class: "tag nf" }, "EVIDENCE NOT FOUND"));
  return b;
}

function renderTimeline() {
  const c = S.case, ids = new Set(c.log.map((e) => e.id));
  const rootId = S.verdict ? S.verdict.root_cause_event.id : null;
  const items = c.log.map((e) => el("li", { class: [e.kind === "alert" ? "alert" : "", e.id === rootId ? "root" : ""].join(" ") },
    el("span", { class: "t" }, `t=${e.t}`), el("span", { class: "id" }, e.id), `${e.actor} · ${e.kind} · ${e.service} — ${e.detail}`,
    e.id === rootId ? el("span", { class: "tag supported" }, "ROOT CAUSE") : null,
    c.claims.filter((x) => x.cites === e.id && x.accused).map(claimButton)));
  // Placement only; whether a cited id exists in the log is stated by the server after INVESTIGATE.
  const orphans = c.claims.filter((x) => x.accused && (!x.cites || !ids.has(x.cites)));
  if (orphans.length) items.push(el("li", { class: "orphan" }, el("span", { class: "t" }, "—"), "Assertions not attached to any log line", orphans.map(claimButton)));
  $("tl").replaceChildren(...items);
}

function renderDetail() {
  if (S.selected === null) return;
  const c = S.case.claims[S.selected], ic = invClaim(c.i);
  const kids = [el("b", {}, claimLabel(c)), el("p", {}, `“${c.line}” `, el("span", { class: "lbl sim" }, "simulated"))];
  if (!ic) kids.push(el("p", { class: "fine" }, "Pending investigation. Press INVESTIGATE INCIDENT."));
  else {
    kids.push(el("p", {}, "Cited log entry: ", c.cites === null ? el("span", { class: "tag unverifiable" }, "NO CITATION")
      : ic.cited_event_found ? el("span", { class: "tag supported" }, `${c.cites} EXISTS IN LOG`)
      : el("span", { class: "tag nf" }, `${c.cites}: EVIDENCE NOT FOUND`)));
    kids.push(el("p", {}, "Investigator check: ", el("span", { class: `tag ${ic.check}` }, ic.check)));
    if (!ic.reached_investigator_as_sent) kids.push(el("p", { class: "warn" }, "Altered or dropped in transit before reaching the investigator."));
  }
  $("detail").replaceChildren(...kids);
}

async function investigate() {
  const run = S.run, p = params();
  $("investigate").disabled = true; setStatus("investigating");
  try { S.inv = await api.investigate(p); }
  catch (e) { showError(`Investigation failed: ${e.message}`, investigate); setStatus("unresolved"); $("investigate").disabled = false; return; }
  $("dialogue").replaceChildren(); $("checks").replaceChildren();
  const said = {}, spoke = new Set();
  for (const m of S.case.transcript) {
    if (run !== S.run) return;
    const who = m.text.split(":")[0].split(" (")[0];
    if (!m.text.includes("(relaying")) said[who] = m.text.slice(m.text.indexOf(":") + 1).trim();
    spoke.add(who);
    $("dialogue").append(el("li", {}, el("span", { class: "r" }, `r${m.round}`), m.text));
    $("dialogue").lastChild.scrollIntoView({ block: "nearest" });
    $("ind-agents").textContent = spoke.size;
    renderAgents(new Set([who]), said); renderTopology(who);
    await sleep(500);
  }
  renderTopology();
  for (const a of S.inv.attributions) {
    if (run !== S.run) return;
    $("clock").textContent = `round ${a.round}/${S.meta.deadline_rounds}`;
    for (const ch of S.inv.checks.filter((x) => x.round === a.round))
      $("checks").append(el("li", {}, `r${ch.round} checked “${ch.accused} via ${ch.cites}” → `, el("span", { class: ch.result === "supported" ? "ok" : "bad" }, ch.result.toUpperCase())));
    $("checks").append(el("li", {}, `r${a.round} attribution: ${a.attribution || "none"} `, el("span", { class: "fine" }, `(${a.reason.replaceAll("_", " ")})`)));
    await sleep(400);
  }
  $("deliveries").replaceChildren(...(S.inv.delivered.length ? S.inv.delivered.map((d) => el("li", {},
    `r${d.round} ${d.speaker} → ${d.accused || "nobody"}${d.cites ? ` [${d.cites}]` : " [no citation]"}${d.via.length ? ` via ${d.via.join(" → ")}` : ""}`)) : [emptyLi("Nothing reached the investigator.")]));
  const counts = Object.entries(S.inv.accused_counts).sort((a, b) => b[1] - a[1]);
  $("contra").replaceChildren(el("p", {}, S.inv.contradictions ? `${counts.length} different agents accused:` : "All accusations agree."),
    el("ul", {}, counts.map(([n, k]) => el("li", {}, `${n}: ${k}`))),
    el("p", {}, `${S.inv.claims.filter((c) => c.cited_event_found === false).length} citation(s) point to log entries that do not exist.`));
  $("ind-claims").textContent = S.inv.claims.filter((c) => c.accused && c.check !== "supported" && c.check !== "refuted").length;
  renderAgents(new Set(), said); renderTimeline(); renderDetail();
  $("reveal").disabled = false; $("reveal").focus();
}

async function reveal() {
  const p = params();
  try { S.verdict = await api.verdict(p); } catch (e) { showError(`Verdict unavailable: ${e.message}`, reveal); return; }
  const v = S.verdict, ic = S.inv.claims.filter((c) => c.accused), n = (k) => ic.filter((c) => c.check === k).length;
  const outcome = v.correct ? ["CORRECT", "good"] : v.abstained ? ["ABSTAINED", "warn"] : ["WRONG · innocent agent blamed", "badc"];
  const card = (k, val, cls = "", note = null, lbl = null) => el("div", { class: "card" }, el("span", { class: "k" }, k, lbl ? " " : "", lbl),
    el("div", { class: `v ${cls}` }, val), note ? el("div", { class: "fine" }, note) : null);
  $("verdict-body").replaceChildren(
    card("Investigator named", v.investigator_named || "nobody", "", `Why: ${S.inv.final_reason_text}`),
    card("Actual culprit (from the trace)", v.culprit),
    card("Outcome", outcome[0], outcome[1]),
    card("Root-cause event", `${v.root_cause_event.id} · t=${v.root_cause_event.t}`, "", v.root_cause_event.detail),
    card("Red herring", `${v.red_herring_event.id} · t=${v.red_herring_event.t}`, "", `${v.red_herring_event.actor}: ${v.red_herring_event.detail}`),
    card("Claims", `${n("supported")} supported · ${n("refuted")} contradicted`, "", `${n("unverifiable")} unverifiable · ${n("unchecked")} unchecked`),
    card("Steps to attribution", v.steps_to_attribution ?? "never stable", "", `${v.messages} messages`),
    card("Corrective action", v.corrective_action, "", null, el("span", { class: "lbl copy" }, "presentation copy")));
  $("verdict").hidden = false; setStatus("resolved"); $("reveal").disabled = true;
  renderTimeline(); $("verdict").scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
}

function renderMethod() {
  $("rules").replaceChildren(...Object.entries(S.meta.reasons).map(([k, t]) => el("li", {}, el("code", {}, k), ` — ${t}`)));
}

async function renderLab() {
  try { S.research = await getJSON("data/research.json"); }
  catch (e) { $("lab-src").textContent = `Results unavailable: ${e.message}`; return; }
  const R = S.research;
  $("lab-src").textContent = `${R.n_runs} runs · 4 scenarios × 3 topologies × 2 incentives × 2 access levels × 50 seeds · ${R.source}`;
  $("metrics").querySelector("tbody").replaceChildren(...R.metrics.map((m) => el("tr", {}, el("td", {}, m.name), el("td", {}, m.definition), el("td", { class: "fine" }, m.denominator),
    el("td", {}, el("span", { class: `lbl ${m.status === "computed" ? "meas" : m.status === "illustrative" ? "copy" : "nm"}` }, m.status)))));
  radioGroup($("lab-access"), [{ id: "full", label: "full trace access" }, { id: "claims_only", label: "claims only" }], S.labAccess, (id) => { S.labAccess = id; markRadio($("lab-access"), id); renderMatrix(); });
  [...$("lab-access").children].forEach((b, i) => { b.dataset.id = ["full", "claims_only"][i]; });
  renderMatrix();
  $("chart").replaceChildren(el("div", { class: "row" }, el("span", {}, "condition"), el("span", {}, "accuracy"), el("span", {}, "false blame")),
    ...R.cells.filter((c) => c.incentive === "self_protective").map((c) => el("div", { class: "row" }, el("span", {}, `${c.topology} · ${c.access}`), bar(c.accuracy, "acc"), bar(c.false_blame, "fb"))));
  $("hyp").querySelector("tbody").replaceChildren(...R.hypotheses.map((h) => el("tr", {}, el("td", {}, h.id), el("td", {}, h.claim),
    el("td", { class: h.supported ? "good" : "badc" }, h.supported ? "SUPPORTED" : "REFUTED"),
    el("td", { class: "n" }, Object.entries(h.numbers).map(([k, v]) => `${k}=${typeof v === "number" ? +v.toPrecision(4) : JSON.stringify(v)}`).join(", ")),
    el("td", { class: "fine" }, h.design_note))));
  const rp = R.reproducibility;
  $("repro").replaceChildren(
    el("p", {}, "Summary re-derived from saved runs: ", el("b", { class: rp.summary_matches_runs ? "good" : "badc" }, rp.summary_matches_runs ? "matches" : "MISMATCH")),
    el("p", {}, "Preregistration commits: ", ...rp.preregistration.flatMap((p, i) => [i ? " → " : "", el("a", { href: p.url, rel: "noopener" }, `${p.step} ${p.commit.slice(0, 7)}`)])),
    el("ul", {}, Object.entries(rp.fingerprints_sha256).map(([f, h]) => el("li", {}, `${f}: `, el("code", {}, h)))),
    el("p", {}, "Raw results: ", el("a", { href: "data/raw/runs.csv" }, "runs.csv"), " · ", el("a", { href: "data/raw/summary.json" }, "summary.json"), " · ",
      el("a", { href: "data/export.json" }, "export.json"), S.mode === "live" ? [" · ", el("a", { href: "/api/export?format=csv" }, "per-scenario CSV (API)")] : []),
    el("p", {}, "Execution timing: not measured for the saved run."));
  $("caveats").replaceChildren(...R.caveats.map((c) => el("li", {}, c)));
}
const bar = (v, cls) => el("div", { class: `bar ${cls}`, role: "img", "aria-label": `${cls === "fb" ? "false blame" : "accuracy"} ${v.toFixed(3)}` },
  el("span", { style: `width:${(v * 100).toFixed(1)}%` }), el("em", {}, v.toFixed(3)));

function renderMatrix() {
  const R = S.research, tops = S.meta.topologies.map((t) => t.id);
  const head = el("tr", {}, el("th", { scope: "col" }, "scenario"), ...tops.map((t) => el("th", { scope: "col" }, t)));
  const rows = S.meta.scenarios.map((s) => el("tr", {}, el("th", { scope: "row" }, s.id), ...tops.map((t) => {
    const c = R.per_scenario.find((x) => x.scenario === s.id && x.topology === t && x.incentive === "self_protective" && x.access === S.labAccess);
    return el("td", { class: "cellv" }, el("span", { class: "heat" }, el("i", { style: `width:${(c.accuracy * 100).toFixed(0)}%` })), `${c.accuracy.toFixed(2)} `, el("span", { class: "fine" }, `n=${c.n}`));
  })));
  const cap = $("matrix").querySelector("caption");
  $("matrix").replaceChildren(cap, el("thead", {}, head), el("tbody", {}, rows));
}

init();
