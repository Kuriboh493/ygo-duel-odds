"use strict";
// The MTG Arena panel. Polls mtga_odds.py for the opponent's public state, runs odds.js on it and draws the result.
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const {norm} = MtgOdds;
const DB = MtgOdds.parseCards(window.MTG_CARD_DATA);
const DECKS = window.MTG_DECKS || {};
const FORMAT_TITLE = {standard:"Standard", alchemy:"Alchemy", explorer:"Explorer", historic:"Historic", timeless:"Timeless", brawl:"Brawl", limited:"Limited"};
const DECK_SIZE = {brawl:100, limited:40};
const SAME_OPP_PRIOR = 3, SAME_MATCH_PRIOR = 12, OTHER_PRIOR = 0.3;

let settings = {format:"auto", mode:"guess", auto:true, strength:0.7};
let listText = "", listCounts = null;
let V = null, history = [], lastVersion = -1, simTimer = 0, S = null, res = null;
const ignored = new Set();
const fmtNow = () => settings.format !== "auto" ? settings.format : (V && V.format) || "standard";
function save(){ try { localStorage.setItem("mtga-settings", JSON.stringify(settings)); localStorage.setItem("mtga-list", listText); } catch (e){} }
function toast(msg){ const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.h); toast.h = setTimeout(() => { t.hidden = true; }, 3200); }

// Cards the database doesn't know yet still count, using the type the log gave them.
function lookup(name){
  const c = DB[norm(name)];
  if (c) return c;
  const type = (V && V.types && V.types[name]) || "?";
  return {name, type, cmc:0, cost:"", produced:"", tags:[]};
}

function parseList(text){
  const counts = {}; let total = 0, unknown = 0, skip = false;
  for (const raw of text.split(/\r?\n/)){
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith("#") || line.startsWith("//")) continue;
    if (/^(sideboard|maybeboard)\b/i.test(line)){ skip = true; continue; }
    if (/^(deck|main|maindeck|commander|companion)\b/i.test(line)){ skip = false; continue; }
    if (skip) continue;
    const m = line.match(/^(\d+)\s*[xX]?\s+(.+?)(?:\s+\([A-Za-z0-9]+\)(?:\s+\S+)?)?$/);
    if (!m) continue;
    const c = DB[norm(m[2])];
    if (!c) unknown += +m[1];
    const name = c ? c.name : m[2];
    counts[name] = (counts[name] || 0) + +m[1]; total += +m[1];
  }
  return {counts, total, unknown};
}

// ---------- Deck components ----------
function archetypes(fmt){
  const L = DECKS[fmt];
  return L && L.components && L.components.length ? L.components.map(c => Object.assign({}, c, {prior:c.weight * L.components.length})) : [];
}
function pastGame(r, arch, opp, match){
  // A past game only showed part of that deck, so the rest comes from the archetype it looks most like.
  let best = null, bestScore = -Infinity;
  for (const a of arch){
    let s = Math.log(a.weight || 0.01);
    for (const n in r.seen){ const p = a.copies[n]; if (p) s += Math.log(Math.max(1e-3, p.slice(Math.min(4, r.seen[n])).reduce((x, y) => x + y, 0))); else if (!MtgOdds.BASIC.test(n)) s += Math.log(0.02); }
    if (s > bestScore){ bestScore = s; best = a; }
  }
  const copies = Object.assign({}, best ? best.copies : {}), basics = Object.assign({}, best ? best.basics : {});
  for (const n in r.seen){
    if (MtgOdds.BASIC.test(n)){ basics[n] = Math.max(basics[n] || 0, r.seen[n]); continue; }
    const k = Math.min(4, r.seen[n]), a = [0,0,0,0,0];
    a[k] += 0.6; a[Math.min(4, k+1)] += 0.3; a[Math.min(4, k+2)] += 0.1;
    copies[n] = a;
  }
  const same = opp && r.opp === opp, sameMatch = same && match && r.match === match;
  const label = sameMatch ? `Their deck in game ${r.game} of this match` : same ? `${r.opp}'s deck, seen before` : `${r.opp}'s deck`;
  return {name:label, prior:sameMatch ? SAME_MATCH_PRIOR : same ? SAME_OPP_PRIOR : OTHER_PRIOR, copies, basics, record:true};
}
function components(fmt){
  if (settings.mode === "list" && listCounts) return [{name:"Your pasted list", prior:1, list:true, counts:listCounts, copies:{}, basics:{}}];
  const arch = archetypes(fmt);
  const opp = V && V.state === "duel" ? V.opp : null, match = V && V.state === "duel" ? V.match : null;
  const recs = history.filter(r => r.fmt === fmt).slice(-40).map(r => pastGame(r, arch, opp, match));
  const comps = arch.concat(recs);
  // Without archetypes (Limited, Brawl, or a format with no data), all that's known is what they've shown.
  if (!comps.length) comps.push({name:"Unknown deck", prior:1, copies:{}, basics:{}});
  return comps;
}

// ---------- Running the model ----------
function build(){
  const duel = V && V.state === "duel", fmt = fmtNow();
  const pub = duel ? V.pub : {}, kh = duel ? V.kh : {}, seen = duel ? Object.assign({}, V.seen) : {};
  const visible = {};
  for (const o of [pub, kh]) for (const n in o) visible[n] = (visible[n] || 0) + o[n];
  for (const n in visible) seen[n] = Math.max(seen[n] || 0, visible[n]);
  const hand = duel ? (settings.auto ? V.hand : V.hand.map(h => ({id:h.id, ev:[]}))) : [];
  const lost = duel ? V.lost : 0;
  const listTotal = listCounts ? Object.values(listCounts).reduce((a, b) => a + b, 0) : 0;
  const H = duel ? V.library + hand.length + lost : settings.mode === "list" && listCounts ? listTotal : DECK_SIZE[fmt] || 60;
  const M = MtgOdds.buildModel({lookup, comps:components(fmt), seen, visible, H, singleton:fmt === "brawl"});
  const view = {hand, kh, pub, lost, library:duel ? V.library : H, mana:duel ? V.mana : [], manaAll:duel ? V.manaAll : []};
  return {M, view, duel, fmt, seen, H, hasDecks:M.comps.some(c => c.list || c.record) || archetypes(fmt).length > 0};
}
function renderPlays(){
  const s = (V && V.suggest) || {state:"idle"};
  const msg = {nomodel:"No model is loaded.", locked:"Locked: this game is against a person.", idle:"Waiting for a game against Arena's bot, or a replay."}[s.state];
  if (msg){ $("plays").innerHTML = `<p class="empty">${msg}</p>`; return; }
  if (!s.decisions.length){ $("plays").innerHTML = `<p class="empty">Waiting for your next decision.</p>`; return; }
  $("plays").innerHTML = s.decisions.map(d => `${d.attacker ? `<h3>${esc(d.attacker)}</h3>` : ""}<div class="cands">${d.plays.map(x => cand({name:x.name ? `${x.play}: ${x.name}${x.commander ? " (commander)" : ""}` : x.play, type:"U"}, x.p)).join("")}</div>`).join("");
}
function commit(){
  S = build(); renderConn(); renderStatus(); renderLog(); renderEvidence(); renderPlays();
  document.body.classList.toggle("idle", !S.duel);
  $("title").textContent = FORMAT_TITLE[S.fmt] || "Standard";
  clearTimeout(simTimer);
  simTimer = setTimeout(() => {
    res = MtgOdds.simulate(S.M, S.view, {strength:settings.strength, ignored});
    renderBanner();
    if (res.error){ for (const id of ["threats","hand","next","guess"]) $(id).innerHTML = ""; return; }
    renderThreats(); renderHand(); renderNext(); renderGuess();
  }, 30);
}

// ---------- Rendering ----------
const TYPE_CLASS = t => "t-" + ("LCISPBAE".includes(t) ? t : "U");
function pct(p){ if (p <= 0) return "0%"; if (p < 0.01) return "<1%"; if (p >= 1) return "100%"; if (p > 0.99) return ">99%"; return Math.round(p * 100) + "%"; }
function sev(p){ return p >= 0.6 ? "sev-hi" : p >= 0.3 ? "sev-mid" : "sev-lo"; }
function cand(e, p){
  return `<div class="cand ${TYPE_CLASS(e.type)}" style="grid-template-columns:minmax(0,1fr) 46px"><div class="nm"><span class="pip"></span><span class="txt">${esc(e.name)}</span></div><div class="pc">${pct(p)}</div><div class="bar" style="grid-column:1/-1"><i style="width:${(p*100).toFixed(1)}%"></i></div></div>`;
}
function renderConn(){
  const dot = $("dot"), c = $("conn");
  if (!V){ dot.className = "dot"; c.textContent = "Can't reach the odds tool. Is mtga_odds.py still running?"; return; }
  if (!V.found){ dot.className = "dot"; c.textContent = "Can't find Arena's log yet. Start Arena, or pass the log's location with --log."; return; }
  if (V.detailed === false){ dot.className = "dot off"; c.textContent = "Detailed logs are off. In Arena: Options, Account, tick Detailed Logs (Plugin Support), then restart Arena."; return; }
  if (V.state !== "duel"){ dot.className = "dot wait"; c.textContent = V.replay ? (V.replay_done ? "Replay finished." : "Replaying a saved log. Waiting for its next game.") : "Reading Arena's log. Waiting for a game to start."; return; }
  dot.className = "dot on";
  c.textContent = `${V.replay ? "Replay" : "Live"}: playing ${V.opp}${V.game > 1 ? `, game ${V.game}` : ""}.`;
}
function renderStatus(){
  const item = (v, l) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`;
  const d = S.duel;
  $("status").innerHTML = item(d ? V.turn || "–" : "–", "Turn") + item(d && V.life.opp != null ? V.life.opp : "–", "Their life") + item(d ? V.handCount : "–", "Hand") + item(d ? V.library : S.H, "Library") + item(d ? V.mana.length : "–", "Mana open");
}
function renderLog(){
  const log = V && V.log || [];
  $("log").innerHTML = log.length ? log.slice().reverse().map(l => `<li class="${l.msg.startsWith("Auto:") ? "auto" : ""}"><span>T${l.t}</span><div>${esc(l.msg)}</div></li>`).join("") : `<li><span></span><div class="dim">Nothing logged yet.</div></li>`;
}
function renderEvidence(){
  const seen = new Map();
  if (S.duel && settings.auto) for (const h of V.hand) for (const ev of h.ev) if (!seen.has(ev.n)) seen.set(ev.n, ev);
  $("evidence").innerHTML = seen.size ? [...seen.values()].map(ev => `<button class="chip ${ignored.has(ev.n) ? "ignored" : ""}" data-ev="${ev.n}" title="${ignored.has(ev.n) ? "Count this again" : "Stop counting this"}">${esc(ev.why)}${ev.mana ? ` (${ev.mana.length} open)` : ""}</button>`).join("") : `<p class="empty">Nothing yet, or none of it applies to the cards still in their hand.</p>`;
}
function renderBanner(){
  let h = "";
  if (res && res.error) h += `<div class="err">${esc(res.error)}</div>`;
  if (S.duel && settings.mode !== "list" && !S.hasDecks) h += `<div class="banner"><span>No deck data for ${esc(FORMAT_TITLE[S.fmt])}, so threat and card odds can't be worked out, only lands versus spells and what they've shown. Paste their list under Deck if you know it.</span></div>`;
  $("banner").innerHTML = h; $("banner").hidden = !h;
}
function renderThreats(){
  const tiles = [
    ["Can counter a spell now", res.threat.counter],
    ["Instant removal they can pay for", res.threat.removal],
    ["Combat trick they can pay for", res.threat.trick],
    ["Flash threat they can pay for", res.threat.flash],
    ["Board wipe next turn", res.threat.wipe],
  ];
  // With no deck to go on, "no threats known" must not read as a safe 0%.
  $("threats").innerHTML = tiles.map(([l, p]) => S.hasDecks || p > 0 ? `<div class="threat"><div class="lbl">${l}</div><div class="val ${sev(p)}">${pct(p)}</div><div class="bar ${sev(p)}"><i style="width:${(p*100).toFixed(1)}%"></i></div></div>` : `<div class="threat"><div class="lbl">${l}</div><div class="val" title="No deck data for this format">?</div></div>`).join("");
  const colors = {}; for (const s of S.view.mana) for (const c of s) colors[c] = (colors[c] || 0) + 1;
  $("mana").textContent = `${S.view.mana.length} mana open${Object.keys(colors).length ? ` (${Object.keys(colors).map(c => `${c}: ${colors[c]}`).join(", ")})` : ""}.`;
  $("simmeta").textContent = `Based on ${res.N.toLocaleString()} simulated deals, ${Math.round(res.ess).toLocaleString()} effective after weighting.`;
}
function renderHand(){
  const n = S.view.hand.length + Object.values(S.view.kh).reduce((a, b) => a + b, 0);
  if (!n){ $("hand").innerHTML = `<p class="empty">Their hand is empty.</p>`; return; }
  const deck = S.M.cards;
  const known = Object.values(S.view.kh).reduce((a, b) => a + b, 0);
  const lands = res.landDist.reduce((a, p, i) => a + i * p, 0) + res.knownLands;
  const noLand = res.knownLands ? 0 : res.landDist[0];
  const rows = deck.map((e, k) => [e, res.handAny[k], res.handExp[k], S.view.kh[e.name] || 0]).filter(x => x[1] > 0.005).sort((a, b) => b[1] - a[1] || b[2] - a[2]);
  $("hand").innerHTML = `<p class="meta" style="margin:0 0 8px">${n} card${n > 1 ? "s" : ""}${known ? `, ${known} known` : ""}. About ${lands.toFixed(1)} land${Math.abs(lands - 1) < 0.05 ? "" : "s"}. No land at all: ${pct(noLand)}.</p>
  <div class="tablewrap"><table><thead><tr><th>Card</th><th class="n">Holds one+</th><th class="n">Copies</th></tr></thead><tbody>${
    rows.slice(0, 14).map(([e, p, x, k]) => `<tr><td class="${TYPE_CLASS(e.type)}"><span class="pip"></span><span style="color:var(--ink)">${esc(e.name)}</span>${k ? ` <span class="meta">(${k} known)</span>` : ""}</td><td class="n">${pct(p)}</td><td class="n">${x.toFixed(2)}</td></tr>`).join("")
  }</tbody></table></div>`;
}
function renderNext(){
  if (S.view.library <= 0){ $("next").innerHTML = `<p class="empty">Their library is empty.</p>`; return; }
  const deck = S.M.cards;
  const order = deck.map((e, k) => [e, res.nextDraw[k]]).filter(x => x[1] > 0.0005).sort((a, b) => b[1] - a[1]);
  const land = order.filter(x => x[0].type === "L").reduce((a, x) => a + x[1], 0);
  $("next").innerHTML = `<p class="meta" style="margin:0 0 8px"><span class="t-L">Land ${pct(land)}</span> · <span class="t-S">Spell ${pct(1 - land)}</span></p><div class="cands">${order.slice(0, 10).map(([e, p]) => cand(e, p)).join("")}</div>`;
}
function renderGuess(){
  const comps = S.M.comps.map((c, i) => [c, res.compPost[i]]).sort((a, b) => b[1] - a[1]);
  const top = comps.slice(0, 5).filter(x => x[1] >= 0.01), rest = comps.slice(top.length).reduce((a, x) => a + x[1], 0);
  const L = DECKS[S.fmt], shown = Object.values(S.seen).reduce((a, b) => a + b, 0);
  const src = L ? ` Archetypes come from ${L.decks} tournament decklists, ${esc(L.oldest)} to ${esc(L.newest)}.` : "";
  const lead = !S.duel ? `No game yet, so this is how often each deck shows up.${src}` : shown ? `Guessed from ${shown} card${shown > 1 ? "s" : ""} they've shown.${src}` : `They haven't shown a card yet.${src}`;
  const rows = S.M.cards.map((e, k) => [e, res.deckExp[k], S.seen[e.name] || 0]).filter(x => !x[0].other && x[1] >= 0.35).sort((a, b) => b[1] - a[1] || b[2] - a[2]);
  const other = S.M.cards.reduce((a, e, k) => a + (e.other ? res.deckExp[k] : 0), 0);
  $("guess").innerHTML = `<p class="meta" style="margin:0 0 8px">${lead}</p>
  <div class="cands" style="margin-bottom:12px">${top.map(([c, p]) => `<div class="cand arch" style="grid-template-columns:minmax(0,1fr) 46px"><div class="nm"><span class="txt">${esc(c.name)}</span></div><div class="pc">${pct(p)}</div><div class="bar" style="grid-column:1/-1"><i style="width:${(p*100).toFixed(1)}%"></i></div>${c.signature && c.signature.length ? `<div class="meta" style="grid-column:1/-1;margin-top:-1px">Runs ${c.signature.slice(0, 3).map(esc).join(", ")}</div>` : ""}</div>`).join("")}${rest >= 0.01 ? `<div class="meta">Other decks: ${pct(rest)}</div>` : ""}</div>
  <details><summary class="sub">Best guess at their list</summary>
  <div class="tablewrap"><table><thead><tr><th>Card</th><th class="n">Seen</th><th class="n">Copies (est.)</th></tr></thead><tbody>${
    rows.map(([e, x, sn]) => `<tr><td class="${TYPE_CLASS(e.type)}"><span class="pip"></span><span style="color:var(--ink)">${esc(e.name)}</span></td><td class="n ${sn ? "" : "dim"}">${sn || "–"}</td><td class="n">${x.toFixed(1)}</td></tr>`).join("")
  }</tbody></table></div>
  <p class="meta" style="margin:6px 0 0">Plus about ${other.toFixed(1)} cards no known deck runs.</p></details>`;
}

// ---------- Tabs and controls ----------
function showTab(name){
  for (const b of document.querySelectorAll(".tabs button")){
    const on = b.dataset.tab === name;
    b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1;
    $("pane-" + b.dataset.tab).hidden = !on;
  }
  try { localStorage.setItem("mtga-tab", name); } catch (e){}
}
document.querySelector(".tabs").addEventListener("click", ev => { const b = ev.target.closest("[data-tab]"); if (b) showTab(b.dataset.tab); });
document.querySelector(".tabs").addEventListener("keydown", ev => {
  if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
  const bs = [...document.querySelectorAll(".tabs button")], i = bs.findIndex(b => b.getAttribute("aria-selected") === "true");
  const nb = bs[(i + (ev.key === "ArrowRight" ? 1 : bs.length - 1)) % bs.length]; showTab(nb.dataset.tab); nb.focus();
});
function setMode(m){ settings.mode = m; for (const r of document.querySelectorAll("input[name=mode]")) r.checked = r.value === m; save(); }
for (const r of document.querySelectorAll("input[name=mode]")) r.addEventListener("change", () => {
  if (r.value === "list" && !listCounts){ setMode("guess"); return toast("Paste a list and press Load list first."); }
  setMode(r.value); commit();
});
document.addEventListener("click", ev => {
  const chip = ev.target.closest("[data-ev]");
  if (chip){ const n = +chip.dataset.ev; if (ignored.has(n)) ignored.delete(n); else ignored.add(n); commit(); return; }
  if (ev.target.closest("[data-a=loaddeck]")){
    const p = parseList($("decktext").value);
    if (!p.total) return toast("No cards found in that list.");
    listText = $("decktext").value; listCounts = p.counts; setMode("list"); commit();
    toast(`Loaded ${p.total} cards.` + (p.unknown ? ` ${p.unknown} not recognized.` : ""));
  }
});
$("format").addEventListener("change", () => { settings.format = $("format").value; save(); commit(); });
$("auto").addEventListener("change", () => { settings.auto = $("auto").checked; save(); commit(); });
$("strength").addEventListener("input", () => { $("strength-out").textContent = $("strength").value + "%"; });
$("strength").addEventListener("change", () => { settings.strength = +$("strength").value / 100; save(); commit(); });

// ---------- Boot ----------
async function poll(){
  try {
    const v = await (await fetch("api/view")).json();
    const changed = v.version !== lastVersion || !V || v.found !== V.found || v.replay_done !== V.replay_done;
    // A game that just ended joins the decks the guess learns from, and the evidence numbering starts over.
    if (V && V.state === "duel" && (v.state !== "duel" || v.game !== V.game || v.match !== V.match)){ ignored.clear(); loadHistory(); }
    V = v; lastVersion = v.version;
    $("logpath").textContent = `Reading ${v.log_path}` + (v.error ? `. Last error: ${v.error}` : "");
    if (changed) commit();
  } catch (e){ if (V){ V = null; commit(); } else renderConn(); }
  setTimeout(poll, 500);
}
async function loadHistory(){ try { history = await (await fetch("api/history")).json(); } catch (e){} }
(async function boot(){
  try { settings = Object.assign(settings, JSON.parse(localStorage.getItem("mtga-settings") || "{}")); listText = localStorage.getItem("mtga-list") || ""; } catch (e){}
  if (listText){ const p = parseList(listText); if (p.total) listCounts = p.counts; }
  if (!listCounts) settings.mode = "guess";
  setMode(settings.mode); $("decktext").value = listText; $("format").value = settings.format;
  $("auto").checked = settings.auto; $("strength").value = Math.round(settings.strength * 100); $("strength-out").textContent = $("strength").value + "%";
  let tab = "odds"; try { tab = localStorage.getItem("mtga-tab") || "odds"; } catch (e){}
  showTab($("pane-" + tab) ? tab : "odds");
  await loadHistory();
  poll();
})();
