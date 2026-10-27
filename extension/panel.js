"use strict";
// Side panel. Gets the opponent's public state from tracker.js on the DuelingBook tab, adds the decklist,
// and runs the same simulation as goat-odds.html / edison-odds.html.
const DEFAULT_SETW = {M:0.5,Sn:0.05,Sq:0.6,Sc:0.1,T:1};
const TYPE_NAME = {M:"Monster",Sn:"Normal spell",Sq:"Quick-play spell",Sc:"Cont./equip spell",T:"Trap"};
const EV_TEXT = {atk:"Ignored an attack",sum:"Ignored a summon",neg:"Let a card resolve",rem:"Held off S/T removal",mrem:"Held off monster removal",chaos:"Skipped a Chaos summon",hatk:"No hand trap on attack"};
const HAND_BTN = {goat:"Could have summoned Chaos, didn't", edison:"I attacked, no Gorz or Fader"};
const N_SAMPLES = 30000;

const norm = s => String(s).toLowerCase().replace(/[^a-z0-9]/g,"");
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const tcls = t => "t-" + t[0];
const $ = id => document.getElementById(id);

// Full card pool from cards.js (built by tools/build_cards.py). Hand-tuned format entries win over it.
const TAGMAP = {a:"atk",s:"sum",r:"rem",m:"mrem",n:"neg",d:"draw",h:"hatk"};
const GEN = {}, BYID = {};
(function(){
  const raw = window.CARD_DATA; if (typeof raw !== "string") return;
  for (const line of raw.split("\n")){
    const f = line.split("\t"); if (f.length < 5) continue;
    const c = {name:f[0], type:f[1], setW:(+f[2])/100, tags:[...f[3]].map(x => TAGMAP[x]).filter(Boolean)};
    GEN[norm(f[0])] = c; for (const id of f[4].split(",")) if (id) BYID[+id] = c;
  }
})();
const HAS_FULL_DB = Object.keys(GEN).length > 0;

// ---------- Settings and decklist ----------
let settings = {format:"goat", auto:true, strength:0.7, side:"auto"};
let decks = {};            // format -> {text, deck}
let F, DBN;                // current format data and its normalized name index
function useFormat(key){
  F = FORMATS[key] || FORMATS.goat; settings.format = FORMATS[key] ? key : "goat";
  DBN = {}; for (const n in F.db) DBN[norm(n)] = n;
  $("title").textContent = F.title; $("format").value = settings.format;
  $("b-evhand").textContent = HAND_BTN[settings.format];
}
function deckFor(){
  let d = decks[settings.format];
  if (!d || !Array.isArray(d.deck) || !d.deck.length){ d = {text:F.sample, deck:parseDeck(F.sample), sample:true}; decks[settings.format] = d; }
  return d;
}
function saveSettings(){ chrome.storage.local.set({settings}); }
function saveDecks(){ chrome.storage.local.set({decks}); }

function lookupCard(name){
  const canon = DBN[norm(name)];
  if (canon){ const [type,setW,tags] = F.db[canon]; return {name:canon,type,setW,tags:tags.slice()}; }
  const g = GEN[norm(name)];
  return g ? {name:g.name,type:g.type,setW:g.setW,tags:g.tags.slice()} : null;
}
function makeEntry(name, count){
  const c = lookupCard(name);
  if (c) return Object.assign(c, {count, known:true});
  return {name:name.trim(),count,type:"M",setW:DEFAULT_SETW.M,tags:[],known:false};
}
function addTo(out, idx, e){
  if (e.type === "X"){ out.skipped.push(e.name); return; }
  const k = norm(e.name);
  if (idx[k] !== undefined) out[idx[k]].count += e.count; else { idx[k] = out.length; out.push(e); }
}
function parseYdk(text){
  const out = []; out.skipped = []; out.badIds = 0; const idx = {}; let skip = false;
  for (const raw of text.split(/\r?\n/)){
    const line = raw.trim().toLowerCase(); if (!line) continue;
    if (line.startsWith("#main")){ skip = false; continue; }
    if (line.startsWith("#extra") || line.startsWith("!side")){ skip = true; continue; }
    if (line.startsWith("#") || skip || !/^\d+$/.test(line)) continue;
    const c = BYID[+line]; if (!c){ out.badIds++; continue; }
    addTo(out, idx, makeEntry(c.name, 1));
  }
  return out;
}
function parseDeck(text){
  const body = text.replace(/^\s*[#!].*$/gm, "");
  if (/^\s*#main/im.test(text) || (/^\s*\d{4,9}\s*$/m.test(body) && !/[a-z]{3}/i.test(body))) return parseYdk(text);
  const out = []; out.skipped = []; out.badIds = 0; const idx = {}; let skip = false;
  for (const raw of text.split(/\r?\n/)){
    const line = raw.trim();
    if (!line || line.startsWith("#") || line.startsWith("//")) continue;
    const h = line.toLowerCase().replace(/[:=\-\s]+$/,"").replace(/^[#=\-\s]+/,"");
    if (/^(extra|side)(\s*deck)?(\s*\(\d+\))?$/.test(h)){ skip = true; continue; }
    if (/^main(\s*deck)?(\s*\(\d+\))?$/.test(h)){ skip = false; continue; }
    if (/^(monsters?|spells?|traps?|monster cards|spell cards|trap cards)(\s*\(\d+\))?$/.test(h)) continue;
    if (skip) continue;
    let m, count = 1, name = line;
    if ((m = line.match(/^(\d+)\s*[xX]?\s+(.+)$/))){ count = +m[1]; name = m[2]; }
    else if ((m = line.match(/^(.+?)\s*[xX]\s*(\d+)$/))){ count = +m[2]; name = m[1]; }
    name = name.trim(); if (!name || count < 1) continue;
    addTo(out, idx, makeEntry(name, count));
  }
  return out;
}

// ---------- Live state ----------
let V = null, tabId = null, S = null, lastRes = null;
function toast(msg){ const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._h); toast._h = setTimeout(()=>{ t.hidden = true; }, 3200); }
function toTab(msg){
  if (tabId === null) return toast("Open a duel on DuelingBook first.");
  chrome.tabs.sendMessage(tabId, msg).catch(() => toast("Lost the DuelingBook tab. Reload it."));
}

// Combines the view with the decklist. Cards they showed beyond the list are added, so a side-decked card never breaks the odds.
function build(){
  const base = deckFor().deck;
  const deck = base.map(e => Object.assign({}, e, {tags:e.tags.slice()}));
  const idx = {}; deck.forEach((e,k) => idx[norm(e.name)] = k);
  const pub = {}, kh = {}, added = [], skipped = new Set();
  const place = (name, n, into) => {
    let k = idx[norm(name)];
    if (k === undefined){
      const c = lookupCard(name);
      if (!c || c.type === "X"){ skipped.add(name); return; }
      k = idx[norm(c.name)];
      if (k === undefined){ k = deck.length; idx[norm(c.name)] = k; deck.push(Object.assign(c, {count:0, known:true})); }
    }
    const e = deck[k]; into[e.name] = (into[e.name] || 0) + n;
  };
  if (V && V.state === "duel"){
    for (const n in V.pub) place(n, V.pub[n], pub);
    for (const n in V.kh) place(n, V.kh[n], kh);
  }
  for (const e of deck){
    const seen = (pub[e.name] || 0) + (kh[e.name] || 0);
    if (seen > e.count){ added.push(`${e.name}${e.count ? ` (list has ${e.count}, seen ${seen})` : ""}`); e.count = seen; }
  }
  const duel = V && V.state === "duel";
  return {deck, pub, kh, added, hand: duel ? V.hand : [], sets: duel ? V.sets : [], lost: duel ? V.lost : 0, turn: duel ? V.turn : 0, duel};
}
const khTotal = () => { let n = 0; for (const k in S.kh) n += S.kh[k]; return n; };
function hiddenTotal(){ let P = 0; for (const e of S.deck) P += Math.max(0, e.count - (S.pub[e.name]||0) - (S.kh[e.name]||0)); return P; }
function deckSize(){ return hiddenTotal() - S.hand.length - S.sets.length - S.lost; }

// ---------- Simulation ----------
function zoneOK(zone, type){ return zone === "mon" ? type === "M" : type !== "M"; }
function lik(ev, e){
  if (ev.kind === "tag") return e.tags.includes(ev.tag) ? 1 - ev.s : 1;
  if (ev.kind === "card") return e.name === ev.name ? 1 - ev.s : 1;
  if (ev.kind === "wasSet") return zoneOK(ev.zone, e.type) ? e.setW : 0;
  return 1;
}
function simulate(){
  const deck = S.deck, K = deck.length;
  const pool = new Int32Array(K); let P = 0;
  deck.forEach((e,k) => { pool[k] = Math.max(0, e.count - (S.pub[e.name]||0) - (S.kh[e.name]||0)); P += pool[k]; });
  const nS = S.sets.length, nH = S.hand.length;
  // Face-down banished cards are hidden but say nothing about the rest, so they only shrink the deck.
  const D = P - nS - nH - S.lost;
  if (D < 0) return {error:`Their hidden cards outnumber the unseen cards in the list by ${-D}. The decklist is probably missing cards.`};
  const setW = S.sets.map(sl => { const w = new Float64Array(K); deck.forEach((e,k) => { let v = zoneOK(sl.zone,e.type) ? e.setW : 0; for (const ev of sl.ev) v *= lik(ev,e); w[k] = v; }); return w; });
  const handW = S.hand.map(h => { if (!h.ev.length) return null; const w = new Float64Array(K); deck.forEach((e,k) => { let v = 1; for (const ev of h.ev) v *= lik(ev,e); w[k] = v; }); return w; });
  const nSlot = nS + nH, N = N_SAMPLES;
  const assign = new Int16Array(N * Math.max(1,nSlot)); const logw = new Float64Array(N);
  const cnt = new Int32Array(K);
  const pickW = (w, Z) => { let u = Math.random()*Z, acc = 0, last = -1; for (let k=0;k<K;k++){ const m = cnt[k]*w[k]; if (m > 0){ last = k; acc += m; if (u < acc) return k; } } return last; };
  const pickU = R => { let u = Math.floor(Math.random()*R); for (let k=0;k<K;k++){ if (u < cnt[k]) return k; u -= cnt[k]; } return -1; };
  for (let i=0;i<N;i++){
    cnt.set(pool); let R = P, lw = 0, ok = true; const off = i*nSlot;
    for (let j=0;j<nSlot && ok;j++){
      const w = j < nS ? setW[j] : handW[j-nS];
      let k;
      if (w){ let Z = 0; for (let q=0;q<K;q++) Z += cnt[q]*w[q]; if (Z <= 0){ ok = false; break; } k = pickW(w,Z); lw += Math.log(Z/R); }
      else k = pickU(R);
      if (k < 0){ ok = false; break; }
      cnt[k]--; R--; assign[off+j] = k;
    }
    logw[i] = ok ? lw : -Infinity;
  }
  let mx = -Infinity; for (let i=0;i<N;i++) if (logw[i] > mx) mx = logw[i];
  if (mx === -Infinity) return {error:"No arrangement of their unseen cards fits everything logged. Remove some evidence tags or check the decklist."};
  const tagArr = t => deck.map(e => e.tags.includes(t));
  const T = {atk:tagArr("atk"), sum:tagArr("sum"), rem:tagArr("rem"), mrem:tagArr("mrem"), ht:tagArr(F.fmt.handTag)};
  const khHas = t => deck.some((e,k) => T[t][k] && (S.kh[e.name]||0) > 0);
  const kAny = {rem:khHas("rem"), mrem:khHas("mrem"), ht:khHas("ht")};
  const setDist = S.sets.map(() => new Float64Array(K));
  const handAny = new Float64Array(K), handExp = new Float64Array(K), setExp = new Float64Array(K), next = new Float64Array(K);
  const th = {atk:0, sum:0, rem:0, mrem:0, ht:0};
  const tally = new Int32Array(K), seen = new Uint8Array(K);
  let W = 0, W2 = 0;
  for (let i=0;i<N;i++){
    if (logw[i] === -Infinity) continue;
    const w = Math.exp(logw[i]-mx); W += w; W2 += w*w; const off = i*nSlot;
    tally.fill(0); seen.fill(0);
    let a = false, s = false, r = kAny.rem, m = kAny.mrem, c = kAny.ht;
    for (let j=0;j<nS;j++){ const k = assign[off+j]; setDist[j][k] += w; setExp[k] += w; tally[k]++; if (S.sets[j].zone === "st"){ if (T.atk[k]) a = true; if (T.sum[k]) s = true; } }
    for (let j=nS;j<nSlot;j++){ const k = assign[off+j]; handExp[k] += w; tally[k]++; if (!seen[k]){ seen[k] = 1; handAny[k] += w; } if (T.rem[k]) r = true; if (T.mrem[k]) m = true; if (T.ht[k]) c = true; }
    if (D > 0){ const rem = P - nSlot; if (rem > 0) for (let k=0;k<K;k++) next[k] += w * (pool[k]-tally[k]) / rem; }
    if (a) th.atk += w; if (s) th.sum += w; if (r) th.rem += w; if (m) th.mrem += w; if (c) th.ht += w;
  }
  const div = arr => { for (let k=0;k<arr.length;k++) arr[k] /= W; };
  setDist.forEach(div); div(handAny); div(handExp); div(setExp); div(next);
  for (const k in th) th[k] /= W;
  deck.forEach((e,k) => { if ((S.kh[e.name]||0) > 0) handAny[k] = 1; handExp[k] += (S.kh[e.name]||0); });
  let ns = 0; for (let k=0;k<K;k++) ns += next[k]; if (ns > 0) for (let k=0;k<K;k++) next[k] /= ns;
  return {N, ess: W*W/W2, setDist, handAny, handExp, setExp, next, th, pool, P, D};
}

// ---------- Rendering ----------
function pct(p){ if (p <= 0) return "0%"; if (p < 0.01) return "<1%"; if (p >= 1) return "100%"; if (p > 0.99) return ">99%"; return Math.round(p*100) + "%"; }
function sev(p){ return p >= 0.6 ? "sev-hi" : p >= 0.3 ? "sev-mid" : "sev-lo"; }
function cand(e, p, slotId){
  const x = slotId ? `<button class="x" data-sa="notcard" data-slot="${esc(slotId)}" data-name="${esc(e.name)}" title="Rule out ${esc(e.name)} for this card" aria-label="Rule out ${esc(e.name)}">✕</button>` : "";
  return `<div class="cand ${tcls(e.type)}"${slotId ? "" : ` style="grid-template-columns:minmax(0,1fr) 46px"`}><div class="nm"><span class="pip"></span><span class="txt">${esc(e.name)}</span></div><div class="pc">${pct(p)}</div>${x}<div class="bar"${slotId ? "" : ` style="grid-column:1/-1"`}><i style="width:${(p*100).toFixed(1)}%"></i></div></div>`;
}
function evLabel(ev){
  const s = ev.s !== undefined ? ` ${Math.round(ev.s*100)}%` : "";
  if (ev.kind === "tag") return (ev.auto ? "Auto: " : "") + EV_TEXT[ev.tag] + s;
  if (ev.kind === "card") return "Not " + ev.name + s;
  if (ev.kind === "wasSet") return "Was set";
  return "Evidence";
}
function renderConn(){
  const dot = $("dot"), c = $("conn");
  if (!V || V.state === "loading"){ dot.className = "dot"; c.textContent = "Looking for a DuelingBook tab… Open duelingbook.com, or reload it if it was open before the extension."; return; }
  if (V.state === "idle"){ dot.className = "dot wait"; c.textContent = V.error ? `Connected, but the duel couldn't be read: ${V.error}` : "Connected to DuelingBook. Waiting for a duel to start."; return; }
  dot.className = "dot on";
  c.textContent = `${V.spectating ? "Watching" : "Live"}: tracking ${V.opp}${V.game > 1 ? `, game ${V.game}` : ""}.` + (V.hooked ? "" : " Duel events aren't coming through, so only the board is read and \"no response\" isn't logged automatically.");
}
function renderStatus(){
  const kh = khTotal(), st = S.sets.filter(x=>x.zone==="st").length, mon = S.sets.length - st;
  const item = (v,l) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`;
  const deck = V && V.state === "duel" ? V.deck : deckSize();
  $("status").innerHTML = item(S.turn || "–","Turn") + item(deck,"Deck") + item(S.hand.length + kh, kh ? `Hand · ${kh} known` : "Hand") + item(st,"Backrow") + item(mon,"Set mons");
}
function renderLog(){
  const log = V && V.log || [];
  $("log").innerHTML = log.length ? log.slice().reverse().map(l => `<li class="${l.msg.startsWith("Auto:") ? "auto" : ""}"><span>T${l.t}</span><div>${esc(l.msg)}</div></li>`).join("") : `<li><span></span><div class="dim">Nothing logged yet. Plays show up here as they happen on DuelingBook.</div></li>`;
}
function renderBanner(res){
  let h = "";
  const d = deckFor();
  if (d.sample) h += `<div class="banner"><span>Using the sample ${esc(F.fmt.sampleName)} list. Paste your opponent's list under Opponent decklist for better odds.</span></div>`;
  if (res && res.error) h += `<div class="err">${esc(res.error)}</div>`;
  if (S.added.length) h += `<div class="banner"><span>Seen but not in the list, so added for this duel: ${S.added.map(esc).join(", ")}.</span></div>`;
  if (res && !res.error && S.duel && res.D !== V.deck) h += `<div class="banner"><span>DuelingBook shows ${V.deck} cards in their deck, but the list leaves ${res.D}. The list is probably ${res.D > V.deck ? "longer" : "shorter"} than their real deck.</span></div>`;
  const unk = S.deck.filter(e=>!e.known).length;
  if (unk) h += `<div class="err">${unk} card${unk>1?"s":""} in the list ${unk>1?"aren't":"isn't"} recognized. Set the type under Opponent decklist so face-down odds stay right.</div>`;
  $("banner").innerHTML = h; $("banner").hidden = !h;
}
function renderThreats(res){
  const nST = S.sets.filter(x=>x.zone==="st").length;
  const tiles = [
    ["Backrow can stop an attack", res.th.atk, nST ? "" : "No backrow"],
    ["Backrow can answer a summon", res.th.sum, nST ? "" : "No backrow"],
    ["Hand holds spell/trap removal", res.th.rem, ""],
    ["Hand holds monster removal", res.th.mrem, ""],
    [F.fmt.handTile, res.th.ht, ""],
  ];
  $("threats").innerHTML = tiles.map(([l,p,note]) => `<div class="threat"><div class="lbl">${l}</div><div class="val ${note ? "" : sev(p)}">${note ? "—" : pct(p)}</div><div class="bar ${sev(p)}"><i style="width:${(p*100).toFixed(1)}%"></i></div></div>`).join("");
  $("simmeta").textContent = `Based on ${res.N.toLocaleString()} simulated deals, ${Math.round(res.ess).toLocaleString()} effective after weighting.` + (V && V.pending ? " Waiting to see if they respond to your last play." : "");
}
function renderSets(res){
  if (!S.sets.length){ $("sets").innerHTML = `<p class="empty">No face-down cards. They appear here as soon as they set one.</p>`; return; }
  $("sets").innerHTML = S.sets.map((sl,j) => {
    const dist = res.setDist[j];
    const order = S.deck.map((e,k)=>[e,dist[k]]).filter(x=>x[1]>0.0005).sort((a,b)=>b[1]-a[1]);
    const top = order.slice(0,6), rest = order.slice(6).reduce((a,x)=>a+x[1],0);
    const typeSum = t => order.filter(x=>x[0].type[0]===t).reduce((a,x)=>a+x[1],0);
    const typeLine = sl.zone === "st" ? `<span class="meta"><span class="t-S">Spell ${pct(typeSum("S"))}</span> · <span class="t-T">Trap ${pct(typeSum("T"))}</span></span>` : "";
    const chips = sl.ev.map((ev,x) => `<button class="chip" data-slot="${esc(sl.id)}" data-sa="rmev" data-x="${x}" title="Remove this evidence">${esc(evLabel(ev))} ✕</button>`).join("");
    return `<div class="slot ${sl.zone}">
      <div class="slot-head"><b><span class="facedown" aria-hidden="true"></span>${esc(sl.label)}</b><span>set turn ${sl.turn}</span></div>
      ${typeLine}
      <div class="cands">${top.map(([e,p]) => cand(e,p,sl.id)).join("")}${rest > 0.005 ? `<div class="meta">Everything else: ${pct(rest)}</div>` : ""}</div>
      ${chips ? `<div class="chips">${chips}</div>` : ""}
      ${sl.zone === "st" ? `<div class="row"><button class="btn small" data-slot="${esc(sl.id)}" data-sa="atk">Ignored attack</button><button class="btn small" data-slot="${esc(sl.id)}" data-sa="sum">Ignored summon</button></div>` : ""}
    </div>`;
  }).join("");
}
function renderHand(res){
  const kh = khTotal(), n = S.hand.length + kh;
  if (!n){ $("hand").innerHTML = `<p class="empty">Their hand is empty.</p>`; return; }
  const rows = S.deck.map((e,k)=>[e,res.handAny[k],res.handExp[k],S.kh[e.name]||0]).filter(x=>x[1]>0.005).sort((a,b)=>b[1]-a[1]||b[2]-a[2]);
  const typeExp = t => S.deck.reduce((a,e,k)=> a + (e.type[0]===t ? res.handExp[k] : 0), 0);
  $("hand").innerHTML = `<p class="meta" style="margin:0 0 8px">${n} card${n>1?"s":""}${kh?`, ${kh} known`:""}. Expected mix: <span class="t-M">${typeExp("M").toFixed(1)} monsters</span>, <span class="t-S">${typeExp("S").toFixed(1)} spells</span>, <span class="t-T">${typeExp("T").toFixed(1)} traps</span>.</p>
  <div class="tablewrap"><table><thead><tr><th>Card</th><th class="n">Holds one+</th><th class="n">Copies</th></tr></thead><tbody>${
    rows.slice(0,12).map(([e,p,x,k]) => `<tr><td class="${tcls(e.type)}"><span class="pip"></span><span style="color:var(--ink)">${esc(e.name)}</span>${k?` <span class="meta">(${k} known)</span>`:""}</td><td class="n">${pct(p)}</td><td class="n">${x.toFixed(2)}</td></tr>`).join("")
  }</tbody></table></div>${rows.length > 12 ? `<p class="meta" style="margin:6px 0 0">${rows.length - 12} less likely cards are under Every card in their list.</p>` : ""}`;
}
function renderNext(res){
  if (res.D <= 0){ $("next").innerHTML = `<p class="empty">Their deck is empty.</p>`; return; }
  const order = S.deck.map((e,k)=>[e,res.next[k]]).filter(x=>x[1]>0.0005).sort((a,b)=>b[1]-a[1]);
  const typeSum = t => order.filter(x=>x[0].type[0]===t).reduce((a,x)=>a+x[1],0);
  $("next").innerHTML = `<p class="meta" style="margin:0 0 8px"><span class="t-M">Monster ${pct(typeSum("M"))}</span> · <span class="t-S">Spell ${pct(typeSum("S"))}</span> · <span class="t-T">Trap ${pct(typeSum("T"))}</span></p><div class="cands">${order.slice(0,10).map(([e,p])=>cand(e,p)).join("")}</div>`;
}
function renderAll(res){
  $("alltable").innerHTML = `<table><thead><tr><th>Card</th><th class="n">In list</th><th class="n">Seen</th><th class="n">Unseen</th><th class="n">In hand</th><th class="n">Face-down</th><th class="n">Next draw</th></tr></thead><tbody>${
    S.deck.map((e,k) => { const seen = (S.pub[e.name]||0) + (S.kh[e.name]||0); return `<tr><td class="${tcls(e.type)}"><span class="pip"></span><span style="color:var(--ink)">${esc(e.name)}</span></td><td class="n">${e.count}</td><td class="n ${seen?"":"dim"}">${seen}</td><td class="n">${res.pool[k]}</td><td class="n">${pct(res.handAny[k])}</td><td class="n">${res.setExp[k] > 0.005 ? res.setExp[k].toFixed(2) : "–"}</td><td class="n">${pct(res.next[k])}</td></tr>`; }).join("")
  }</tbody></table>`;
}
function renderDeckTable(){
  const deck = deckFor().deck, total = deck.reduce((a,e)=>a+e.count,0);
  $("decktable").innerHTML = `<p class="meta" style="margin:0 0 6px">${total} cards in the main deck.</p><table><thead><tr><th>Card</th><th class="n">#</th><th>Type</th><th class="n">Set chance</th></tr></thead><tbody>${
    deck.map((e,k) => `<tr><td class="${tcls(e.type)}"><span class="pip"></span><span style="color:var(--ink)">${esc(e.name)}</span>${e.known?"":`<span class="flag">not recognized</span>`}</td><td class="n">${e.count}</td><td><select id="dt-type-${k}" data-k="${k}" data-f="type" aria-label="Type of ${esc(e.name)}">${Object.keys(TYPE_NAME).map(t=>`<option value="${t}"${t===e.type?" selected":""}>${TYPE_NAME[t]}</option>`).join("")}</select></td><td class="n"><input type="number" id="dt-setw-${k}" data-k="${k}" data-f="setW" min="0" max="100" step="5" value="${Math.round(e.setW*100)}" aria-label="Set chance for ${esc(e.name)}">%</td></tr>`).join("")
  }</tbody></table>`;
}
function syncDeckUI(){ $("decktext").value = deckFor().text; renderDeckTable(); }
let simTimer = 0;
function commit(){
  S = build(); renderConn(); renderStatus(); renderLog();
  clearTimeout(simTimer);
  simTimer = setTimeout(() => {
    const res = simulate(); lastRes = res; renderBanner(res);
    if (res.error){ ["threats","sets","hand","next","alltable"].forEach(id => $(id).innerHTML = ""); $("simmeta").textContent = ""; return; }
    renderThreats(res); renderSets(res); renderHand(res); renderNext(res); renderAll(res);
  }, 30);
}

// ---------- Actions ----------
const strength = () => settings.strength;
function evidence(scope, tag, where){
  if (!V || V.state !== "duel") return toast("No duel is being tracked yet.");
  if (scope === "backrow" && !S.sets.some(x => x.zone === "st")) return toast("They have no face-down spells or traps.");
  if (scope === "hand" && !S.hand.length) return toast("Their hand has no unseen cards.");
  toTab({type:"evidence", scope, ev:{kind:"tag", tag, s:strength()}, text:`${EV_TEXT[tag]} (${where}, ${Math.round(strength()*100)}% sure).`});
}
const ACTIONS = {
  "ev-atk": () => evidence("backrow","atk","backrow"),
  "ev-sum": () => evidence("backrow","sum","backrow"),
  "ev-neg": () => evidence("backrow","neg","backrow"),
  "ev-rem": () => evidence("hand","rem","hand"),
  "ev-mrem": () => evidence("hand","mrem","hand"),
  "ev-hand": () => evidence("hand",F.fmt.handTag,"hand"),
  restart(){ if (!V || V.state !== "duel") return toast("No duel is being tracked yet."); toTab({type:"newduel"}); toast("Tracking restarted from the current board."); },
  loaddeck(){
    const txt = $("decktext").value, d = parseDeck(txt), total = d.reduce((a,e)=>a+e.count,0);
    if (!d.length) return toast(d.badIds && !HAS_FULL_DB ? "The card database didn't load, so .ydk files can't be read. Paste card names instead." : "No cards found in that list.");
    decks[settings.format] = {text:txt, deck:d}; saveDecks(); syncDeckUI(); commit();
    const unk = d.filter(e=>!e.known).length;
    toast(`Loaded ${total} cards.` + (d.skipped.length ? ` Skipped ${d.skipped.length} Extra Deck card${d.skipped.length>1?"s":""}.` : "") + (d.badIds ? ` ${d.badIds} card ID${d.badIds>1?"s":""} not found.` : "") + (unk ? ` ${unk} not recognized; set their type below.` : "") + (total < 40 || total > 60 ? " A main deck should be 40 to 60 cards; check the list." : ""));
  },
  sampledeck(){ $("decktext").value = F.sample; toast("Sample list pasted. Press Load list to use it."); },
};
function slotAction(act, id, extra, name){
  const slot = S.sets.find(x => x.id === id); if (!slot) return;
  if (act === "notcard") toTab({type:"evidence", scope:id, ev:{kind:"card", name, s:strength()}, text:`${slot.label} is likely not ${name} (${Math.round(strength()*100)}% sure).`});
  else if (act === "atk" || act === "sum") toTab({type:"evidence", scope:id, ev:{kind:"tag", tag:act, s:strength()}, text:`${slot.label}: ${EV_TEXT[act].toLowerCase()}.`});
  else if (act === "rmev") toTab({type:"rmev", id, index:extra});
}

// ---------- Events ----------
document.addEventListener("click", ev => {
  const b = ev.target.closest("[data-a],[data-sa]"); if (!b) return;
  if (b.dataset.sa){ slotAction(b.dataset.sa, b.dataset.slot, +b.dataset.x, b.dataset.name); return; }
  const fn = ACTIONS[b.dataset.a]; if (fn) fn();
});
document.addEventListener("change", ev => {
  const t = ev.target; if (!t.dataset || t.dataset.k === undefined) return;
  const d = deckFor(), e = d.deck[+t.dataset.k]; if (!e) return;
  if (t.dataset.f === "type"){ e.type = t.value; if (!e.known) e.setW = DEFAULT_SETW[e.type]; e.known = true; renderDeckTable(); }
  if (t.dataset.f === "setW") e.setW = Math.max(0, Math.min(100, +t.value || 0)) / 100;
  saveDecks(); commit();
});
$("ydkfile").addEventListener("change", ev => {
  const f = ev.target.files && ev.target.files[0]; if (!f) return;
  const r = new FileReader();
  r.onload = () => { $("decktext").value = String(r.result || ""); ACTIONS.loaddeck(); ev.target.value = ""; };
  r.onerror = () => toast("That file couldn't be read.");
  r.readAsText(f);
});
$("format").addEventListener("change", () => { useFormat($("format").value); saveSettings(); syncDeckUI(); commit(); });
$("strength").addEventListener("input", () => { $("strength-out").textContent = $("strength").value + "%"; });
$("strength").addEventListener("change", () => { settings.strength = (+$("strength").value)/100; saveSettings(); });
$("auto").addEventListener("change", () => { settings.auto = $("auto").checked; saveSettings(); toast(settings.auto ? "\"No response\" will be logged automatically." : "Automatic \"no response\" logging is off."); });
$("side").addEventListener("change", () => { settings.side = $("side").value; saveSettings(); toast("Switched sides. Tracking restarts."); });

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (!msg || msg.type !== "view" || !sender.tab) return;
  // With several DuelingBook tabs open, follow the one in front.
  if (tabId !== null && sender.tab.id !== tabId && !sender.tab.active) return;
  tabId = sender.tab.id; V = msg; commit();
});
// Find a DuelingBook tab on open, preferring the one in front.
async function connect(){
  const tabs = await chrome.tabs.query({url:["https://www.duelingbook.com/*","https://duelingbook.com/*"]});
  tabs.sort((a,b) => (b.active - a.active) || (b.lastAccessed||0) - (a.lastAccessed||0));
  for (const t of tabs){
    try {
      const v = await chrome.tabs.sendMessage(t.id, {type:"getView"});
      if (v){ tabId = t.id; V = v; commit(); return; }
    } catch (e){}
  }
  commit();
}
chrome.tabs.onActivated.addListener(async ({tabId:id}) => {
  try { const v = await chrome.tabs.sendMessage(id, {type:"getView"}); if (v){ tabId = id; V = v; commit(); } } catch (e){}
});

// ---------- Boot ----------
chrome.storage.local.get(["settings","decks"], r => {
  if (r.settings) settings = Object.assign(settings, r.settings);
  if (r.decks) decks = r.decks;
  useFormat(settings.format);
  $("auto").checked = settings.auto; $("strength").value = Math.round(settings.strength*100); $("strength-out").textContent = $("strength").value + "%"; $("side").value = settings.side;
  syncDeckUI(); connect();
});
