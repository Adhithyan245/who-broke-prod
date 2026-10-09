"use strict";
// Rendering only. Every value shown comes from the Python simulator via /api/* (live) or the
// pre-built JSON bundle in data/ (offline). No simulation, verification or scoring happens here.
const $ = (id) => document.getElementById(id);
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined) n.append(c instanceof Node ? c : String(c));
  return n;
}
const S = { mode: null, meta: null, case: null, inv: null, verdict: null, run: 0, selected: null };

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  let body = null;
  try { body = await r.json(); } catch { throw new Error(`Bad response from ${url}`); }
  if (!r.ok) throw new Error(body && body.error ? body.error : `HTTP ${r.status} for ${url}`);
  return body;
}
function showError(msg) { const e = $("error"); e.textContent = msg; e.hidden = !msg; }
const params = () => ({ scenario: $("scenario").value, topology: $("topology").value });
const qs = (p) => new URLSearchParams(p).toString();
const key = (p) => `${p.scenario}__${p.topology}`;
const bundleCache = {};
async function bundle(p) { return bundleCache[key(p)] ||= await getJSON(`data/cases/${key(p)}.json`); }

const api = {
  case: async (p) => S.mode === "live" ? getJSON(`/api/case?${qs(p)}`) : (await bundle(p)).case,
  investigate: async (p) => S.mode === "live" ? getJSON(`/api/investigate?${qs(p)}`) : (await bundle(p)).investigation,
  verdict: async (p) => S.mode === "live" ? getJSON(`/api/verdict?${qs(p)}`) : getJSON(`data/verdicts/${key(p)}.json`),
};

async function init() {
  try { S.meta = await getJSON("/api/meta"); S.mode = "live"; }
  catch {
    try { S.meta = await getJSON("data/meta.json"); S.mode = "offline"; }
    catch { showError("No data source: the API is unreachable and the offline bundle (data/meta.json) is missing."); return; }
  }
  $("mode").textContent = S.mode === "live" ? "LIVE · Python API" : "OFFLINE · static bundle";
  $("mode").className = `pill ${S.mode === "live" ? "live" : "off"}`;
  for (const s of S.meta.scenarios) $("scenario").append(el("option", { value: s.id }, s.title));
  for (const t of S.meta.topologies) $("topology").append(el("option", { value: t.id }, t.id));
  $("topology").value = "hub";
  const u = new URLSearchParams(location.search);
  if (u.get("scenario")) $("scenario").value = u.get("scenario");
  if (u.get("topology")) $("topology").value = u.get("topology");
  $("scenario").onchange = $("topology").onchange = load;
  $("reset").onclick = load;
  $("replay").onclick = async () => { await load(); investigate(); };
  $("investigate").onclick = investigate;
  $("reveal").onclick = reveal;
  renderLab();
  await load();
  if (u.get("autoplay") === "1") { await investigate(); await reveal(); }  // kiosk/demo mode
}

function setStatus(s) { $("status").textContent = s.toUpperCase(); $("status").className = `v st-${s}`; }

async function load() {
  const run = ++S.run;
  showError(""); S.inv = S.verdict = S.selected = null;
  $("verdict").hidden = true; $("reveal").disabled = true; $("investigate").disabled = true;
  $("dialogue").replaceChildren(); $("checks").replaceChildren();
  const p = params();
  history.replaceState(null, "", `?${qs(p)}`);
  try { S.case = await api.case(p); } catch (e) { showError(`Could not load case: ${e.message}`); return; }
  if (run !== S.run) return;
  const c = S.case;
  $("cmd-h").textContent = c.incident.title;
  $("svc").textContent = c.incident.service;
  $("clock").textContent = `t=${c.incident.first_alert_t} (first alert)`;
  $("ind-agents").textContent = "0";
  $("ind-evidence").textContent = c.log.length;
  $("ind-claims").textContent = c.claims.filter((x) => x.accused).length;
  $("hash").textContent = `deterministic · seed ${c.params.seed} · ${c.replay_hash}`;
  setStatus("unresolved");
  renderAgents(); renderTimeline(); renderDetail();
  $("investigate").disabled = false;
}

function claimOf(name) { return S.case.claims.find((c) => c.speaker === name); }
function invClaim(i) { return S.inv ? S.inv.claims.find((c) => c.i === i) : null; }

function renderAgents(speaking = new Set(), said = {}) {
  const box = $("agents"); box.replaceChildren();
  const rows = S.case.agents.map((a) => ({ ...a, kind: "agent" }))
    .concat(S.case.relays.map((r) => ({ name: r, role: "mediator (hub only)", kind: "relay" })),
            [{ name: "Investigator", role: `verifies ${S.meta.verification_budget} claim/round`, kind: "inv" }]);
  for (const a of rows) {
    const c = a.kind === "agent" ? claimOf(a.name) : null;
    const ic = c ? invClaim(c.i) : null;
    const accusedBy = S.case.claims.filter((x) => x.accused === a.name).length;
    const tags = [];
    if (ic) tags.push(el("span", { class: `tag ${ic.check}` }, `own claim: ${ic.check}`));
    if (ic && ic.cited_event_found === false) tags.push(el("span", { class: "tag nf" }, "EVIDENCE NOT FOUND"));
    if (a.kind === "agent") tags.push(el("span", { class: "tag" }, `accused by ${accusedBy}`));
    let line = said[a.name] || (a.kind === "inv" && S.inv ? `Final attribution: ${S.inv.final_attribution || "insufficient evidence"}` : "—");
    box.append(el("article", { class: `agent${speaking.has(a.name) ? " speaking" : ""}`, "aria-label": a.name },
      el("b", {}, a.name), el("span", { class: "role" }, a.role),
      el("p", { class: "said" }, line), el("div", {}, tags),
      a.kind === "agent" ? el("div", { class: "fine" }, "confidence: not modelled") : null));
  }
}

function claimLabel(c) {
  return `${c.speaker} → ${c.accused || "nobody"}${c.cites ? ` (cites ${c.cites})` : " (no citation)"}`;
}
function claimButton(c) {
  const ic = invClaim(c.i);
  const b = el("button", { type: "button", class: "claimbtn", "aria-pressed": S.selected === c.i ? "true" : "false",
    onclick: () => { S.selected = c.i; renderTimeline(); renderDetail(); } }, claimLabel(c));
  if (ic) b.append(" ", el("span", { class: `tag ${ic.check}` }, ic.check));
  if (ic && ic.cited_event_found === false) b.append(" ", el("span", { class: "tag nf" }, "EVIDENCE NOT FOUND"));
  return b;
}

function renderTimeline() {
  const c = S.case, tl = $("tl"); tl.replaceChildren();
  const ids = new Set(c.log.map((e) => e.id));
  const rootId = S.verdict ? S.verdict.root_cause_event.id : null;
  for (const e of c.log) {
    const cls = [e.kind === "alert" ? "alert" : "", e.id === rootId ? "root" : ""].join(" ");
    tl.append(el("li", { class: cls },
      el("span", { class: "t" }, `t=${e.t}`), el("span", { class: "id" }, e.id),
      `${e.actor} · ${e.kind} · ${e.service} — ${e.detail}`,
      e.id === rootId ? el("span", { class: "tag supported" }, " ROOT CAUSE") : null,
      c.claims.filter((x) => x.cites === e.id && x.accused).map(claimButton)));
  }
  // Placement only: assertions whose cited id is not a log line, or that cite nothing. The server
  // states whether a cited event exists (shown after INVESTIGATE).
  const orphans = c.claims.filter((x) => x.accused && (!x.cites || !ids.has(x.cites)));
  if (orphans.length) tl.append(el("li", { class: "orphan" }, el("span", { class: "t" }, "—"),
    "Assertions not attached to any log line", orphans.map(claimButton)));
}

function renderDetail() {
  const d = $("detail");
  if (S.selected === null) return;
  const c = S.case.claims[S.selected], ic = invClaim(c.i);
  const kids = [el("b", {}, claimLabel(c)), el("p", {}, `“${c.line}”`)];
  if (!ic) kids.push(el("p", { class: "fine" }, "Pending investigation. Press INVESTIGATE INCIDENT."));
  else {
    kids.push(el("p", {}, "Cited event: ", c.cites === null ? el("span", { class: "tag unverifiable" }, "NO CITATION")
      : ic.cited_event_found ? el("span", { class: "tag supported" }, `${c.cites} EXISTS IN LOG`)
      : el("span", { class: "tag nf" }, `${c.cites}: EVIDENCE NOT FOUND`)));
    kids.push(el("p", {}, "Investigator check: ", el("span", { class: `tag ${ic.check}` }, ic.check)));
    if (!ic.reached_investigator_as_sent) kids.push(el("p", { class: "warn" }, "This claim was altered or dropped in transit before reaching the investigator."));
  }
  d.replaceChildren(...kids);
}

async function investigate() {
  const run = S.run, p = params();
  $("investigate").disabled = true; setStatus("investigating");
  try { S.inv = await api.investigate(p); } catch (e) { showError(`Investigation failed: ${e.message}`); setStatus("unresolved"); return; }
  const said = {}, spoke = new Set();
  for (const m of S.case.transcript) {
    if (run !== S.run) return;
    const who = m.text.split(":")[0].split(" (")[0];
    said[who] = m.text.slice(m.text.indexOf(":") + 1).trim(); spoke.add(who);
    $("dialogue").append(el("li", {}, el("span", { class: "r" }, `r${m.round}`), m.text));
    $("dialogue").lastChild.scrollIntoView({ block: "nearest" });
    $("ind-agents").textContent = spoke.size;
    renderAgents(new Set([who]), said);
    await sleep(550);
  }
  for (const a of S.inv.attributions) {
    if (run !== S.run) return;
    $("clock").textContent = `round ${a.round}/${S.meta.deadline_rounds}`;
    for (const ch of S.inv.checks.filter((x) => x.round === a.round))
      $("checks").append(el("li", {}, `r${ch.round} checked “${ch.accused} via ${ch.cites}” → `,
        el("span", { class: ch.result === "supported" ? "ok" : "bad" }, ch.result.toUpperCase())));
    $("checks").append(el("li", {}, `r${a.round} attribution: ${a.attribution || "insufficient evidence"}`));
    await sleep(450);
  }
  $("ind-claims").textContent = S.inv.claims.filter((c) => c.accused && c.check !== "supported" && c.check !== "refuted").length;
  renderAgents(new Set(), said); renderTimeline(); renderDetail();
  $("reveal").disabled = false; $("reveal").focus();
}

async function reveal() {
  const p = params();
  try { S.verdict = await api.verdict(p); } catch (e) { showError(`Verdict unavailable: ${e.message}`); return; }
  const v = S.verdict, ic = S.inv.claims.filter((c) => c.accused);
  const n = (k) => ic.filter((c) => c.check === k).length;
  const outcome = v.correct ? ["CORRECT", "good"] : v.abstained ? ["ABSTAINED", "warn"] : ["WRONG — innocent agent blamed", "badc"];
  const card = (k, val, cls = "", note = null) => el("div", { class: "card" }, el("span", { class: "k" }, k),
    el("div", { class: `v ${cls}` }, val), note ? el("div", { class: "fine" }, note) : null);
  $("verdict-body").replaceChildren(
    card("Investigator named", v.investigator_named || "nobody"),
    card("Actual culprit (from the log)", v.culprit),
    card("Outcome", outcome[0], outcome[1]),
    card("Root-cause event", `${v.root_cause_event.id} · t=${v.root_cause_event.t}`, "", v.root_cause_event.detail),
    card("Red herring", `${v.red_herring_event.id} · t=${v.red_herring_event.t}`, "", `${v.red_herring_event.actor}: ${v.red_herring_event.detail}`),
    card("Claims", `${n("supported")} supported · ${n("refuted")} contradicted`, "", `${n("unverifiable")} unverifiable · ${n("unchecked")} unchecked`),
    card("Steps to attribution", v.steps_to_attribution ?? "never stable", "", `${v.messages} messages`),
    card("Corrective action", v.corrective_action, "", "Presentation copy, not simulator output."));
  $("verdict").hidden = false; setStatus("resolved"); $("reveal").disabled = true;
  renderTimeline(); $("verdict").scrollIntoView({ behavior: reduced ? "auto" : "smooth" });
}

async function renderLab() {
  for (const t of S.meta.topologies)
    $("topos").append(el("div", { class: "card" }, el("span", { class: "k" }, "topology"), el("div", { class: "v" }, t.id), el("p", { class: "fine" }, t.note)));
  let R;
  try { R = await getJSON("data/research.json"); } catch (e) { $("lab-src").textContent = `(results unavailable: ${e.message})`; return; }
  $("lab-src").textContent = `· ${R.n_runs} runs · ${R.source}`;
  const tb = document.querySelector("#hyp tbody");
  for (const h of R.hypotheses) {
    const nums = Object.entries(h.numbers).map(([k, v]) => `${k}=${typeof v === "number" ? +v.toPrecision(4) : JSON.stringify(v)}`).join(", ");
    tb.append(el("tr", {}, el("td", {}, h.id), el("td", {}, h.claim),
      el("td", { class: h.supported ? "good" : "badc" }, h.supported ? "SUPPORTED" : "REFUTED"),
      el("td", { class: "n" }, nums), el("td", { class: "fine" }, h.design_note)));
  }
  const bar = (v, cls) => el("div", { class: `bar ${cls}` }, el("span", { style: `width:${(v * 100).toFixed(1)}%` }), el("em", {}, v.toFixed(3)));
  $("chart").append(el("div", { class: "row" }, el("span", {}, "condition"), el("span", {}, "accuracy"), el("span", {}, "false blame")));
  for (const c of R.cells.filter((c) => c.incentive === "self_protective"))
    $("chart").append(el("div", { class: "row" }, el("span", {}, `${c.topology} · ${c.access}`), bar(c.accuracy, "acc"), bar(c.false_blame, "fb")));
  for (const c of R.caveats) $("caveats").append(el("li", {}, c));
}

init();
