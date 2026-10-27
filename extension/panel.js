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
// mode: "guess" works out their deck from what they play; "list" uses the pasted decklist.
let settings = {format:"goat", mode:"guess", learned:true, enabled:true, auto:true, strength:0.7, side:"auto"};
let decks = {};            // format -> {text, deck}
let F, DBN;                // current format data and its normalized name index
function useFormat(key){
  F = FORMATS[key] || FORMATS.goat; settings.format = FORMATS[key] ? key : "goat";
  DBN = {}; for (const n in F.db) DBN[norm(n)] = n;
  $("title").textContent = F.title; $("format").value = settings.format;
  $("b-evhand").textContent = HAND_BTN[settings.format];
  const L = window.LEARNED && window.LEARNED[settings.format];
  $("learned").disabled = !L; $("learned").checked = !!L && settings.learned !== false;
  $("learned-lbl").textContent = L ? `Guess from archetypes learned from ${L.decks.toLocaleString()} ${F.title} decklists${L.topping ? ` (${L.topping.toLocaleString()} topping)` : ""}` : "No learned archetypes for this format. Run tools/train_decks.py";
}
function deckFor(){
  let d = decks[settings.format];
  if (!d || !Array.isArray(d.deck) || !d.deck.length){ d = {text:F.sample, deck:parseDeck(F.sample), sample:true}; decks[settings.format] = d; }
  return d;
}
function saveSettings(){ api.storage.local.set({settings}); }
function saveDecks(){ api.storage.local.set({decks}); }

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
let V = null, tabId = null, S = null, lastRes = null, history = [];
function toast(msg){ const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._h); toast._h = setTimeout(()=>{ t.hidden = true; }, 3200); }
function toTab(msg){
  if (tabId === null) return toast("Open a duel on DuelingBook first.");
  api.tabs.sendMessage(tabId, msg).catch(() => toast("Lost the DuelingBook tab. Reload it."));
}

// ---------- Deck model ----------
// Their deck is a mixture of "components". Each one is a guess at what they're playing: a built-in archetype sketch,
// a deck seen in one of your earlier duels, or your pasted list. For every card, a component holds a distribution over
// how many copies (0 to 3) the deck runs. What they show reweights the components and updates each card's copy count.
const OTHER = [
  {name:"Unlisted monster", type:"M", setW:0.4, tags:[], known:true, other:true},
  {name:"Unlisted spell", type:"Sn", setW:0.2, tags:[], known:true, other:true},
  {name:"Unlisted trap", type:"T", setW:1, tags:[], known:true, other:true},
];
const typeIdx = t => t === "M" ? 0 : t === "T" ? 2 : 1;
const SHRINK = 0.1;                  // pull of each archetype toward the format-wide average, for tech choices
const TECH = [0.97, 0.03, 0, 0];     // copies of a card no sketch runs
const UNLISTED = 0.12;               // pull of "a card no known deck runs" when a sampled deck is short
const TECH_MEAN = 1.5;               // cards no known deck runs, on average, in a guessed deck
const SAME_MATCH_MS = 3 * 3600e3;
const BINOM = [[1],[1,1],[1,2,1],[1,3,3,1]];
// Chance of having seen n copies of a card with j copies in the deck, when a share f of the deck has been seen.
const seenLik = (j, n, f) => j < n ? 0 : BINOM[j][n] * Math.pow(f, n) * Math.pow(1 - f, j - n);
function spread(m, cap){
  const a = [0,0,0,0]; m = Math.min(m, 3);
  if (!m){ a[0] = 1; return a; }
  // Centered on the listed count. At the copy limit the only way is down, so keep that small to keep the mean near m.
  if (m + 1 <= cap){ a[m] += 0.7; a[m-1] += 0.15; a[m+1] += 0.15; }
  else { a[m] += 0.92; a[m-1] += 0.08; }
  return a;
}
// A card seen n times runs at least n copies, probably exactly n.
function atLeast(n){ const a = [0,0,0,0]; n = Math.min(n, 3); a[n] += 0.6; a[Math.min(3,n+1)] += 0.3; a[Math.min(3,n+2)] += 0.1; return a; }

const LEARNED_MIN = 0.985;          // learned cards an archetype runs at least this rarely are left to the tech allowance
const LEARNED_SHRINK = 0.05;
function learned(){
  const L = window.LEARNED && window.LEARNED[settings.format];
  return settings.learned !== false && L && L.components && L.components.length ? L : null;
}

let archCache = {};
function archetypes(){
  if (!archCache[settings.format]) archCache[settings.format] = (F.archetypes || [{name:F.fmt.sampleName, list:F.sample}]).map(a => ({name:a.name, deck:parseDeck(a.list)}));
  return archCache[settings.format];
}
function when(t){
  const d = Date.now() - t;
  if (d < 3600e3) return "earlier this hour";
  if (d < 86400e3) return "earlier today";
  const days = Math.round(d / 86400e3);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

// seen: lower bound on copies for each card name. visible: copies out of the hidden pool right now. H: hidden cards.
function buildModel(seen, visible, H, opp){
  const cards = [], idx = {};
  const add = e => { const k = norm(e.name); if (idx[k] === undefined){ idx[k] = cards.length; cards.push(e); } return idx[k]; };
  const addName = name => { const k = idx[norm(name)]; if (k !== undefined) return k; const c = lookupCard(name); if (!c || c.type === "X") return -1; return add(Object.assign(c, {known:true})); };
  const comps = [];
  const guess = settings.mode !== "list";

  if (!guess){
    const d = deckFor();
    const counts = d.deck.map(e => [add(Object.assign({}, e, {tags:e.tags.slice()})), e.count]);
    for (const n in seen) addName(n);
    const K = cards.length, P = new Float64Array(K*4);
    for (let c=0;c<K;c++) P[c*4] = 1;
    for (const [c, m] of counts){ P[c*4] = 0; P[c*4 + Math.min(3, m)] = 1; }
    comps.push({name:d.sample ? `Sample ${F.fmt.sampleName} list` : "Your pasted list", prior:1, P, list:true, counts});
  } else {
    // Archetypes learned from published decklists (learned.js) when there are any, else the sketches in formats.js.
    const L = learned();
    const arch = L ? [] : archetypes().map(a => ({name:a.name, counts:a.deck.map(e => [add(Object.assign({}, e, {tags:e.tags.slice()})), e.count])}));
    const lcomp = L ? L.components.map(c => ({c, ids:Object.keys(c.copies).filter(nm => c.copies[nm][0] < LEARNED_MIN).map(nm => [addName(nm), c.copies[nm]]).filter(x => x[0] >= 0)})) : [];
    const recs = history.filter(r => r.fmt === settings.format).slice(-40).map(r => {
      const counts = []; let s = 0;
      for (const n in r.seen){ const c = addName(n); if (c >= 0){ counts.push([c, r.seen[n]]); s += r.seen[n]; } }
      return Object.assign({}, r, {counts, s});
    }).filter(r => r.s >= 4);
    for (const n in seen) addName(n);
    const K = cards.length;
    let tmpl, bg = new Float64Array(K*4);
    if (L){
      tmpl = lcomp.map(({ids}) => { const T = new Float64Array(K*4); for (let c=0;c<K;c++){ T[c*4] = 1 - TECH[1]/10; T[c*4+1] = TECH[1]/10; } for (const [c, p] of ids) for (let j=0;j<4;j++) T[c*4+j] = p[j]; return T; });
      for (let c=0;c<K;c++){ const m = L.marginal[cards[c].name]; for (let j=0;j<4;j++) bg[c*4+j] = m ? 0.9 * m[j] + 0.1 * TECH[j] : TECH[j]; }
    } else {
      // A card that every sketch runs as a single copy is treated as limited.
      const maxCount = new Int32Array(K), inN = new Int32Array(K);
      for (const a of arch) for (const [c, m] of a.counts){ maxCount[c] = Math.max(maxCount[c], m); inN[c]++; }
      const cap = c => inN[c] >= 2 && maxCount[c] === 1 ? 1 : 3;
      tmpl = arch.map(a => { const T = new Float64Array(K*4); for (let c=0;c<K;c++) T[c*4] = 1; for (const [c, m] of a.counts){ const s = spread(m, cap(c)); for (let j=0;j<4;j++) T[c*4+j] = s[j]; } return T; });
      for (let c=0;c<K;c++) for (let j=0;j<4;j++){ let m = 0; for (const T of tmpl) m += T[c*4+j]; bg[c*4+j] = 0.9 * (tmpl.length ? m / tmpl.length : TECH[j]) + 0.1 * TECH[j]; }
    }
    const shrink = (T, a) => { const P = new Float64Array(K*4); for (let i=0;i<K*4;i++) P[i] = (1-a) * T[i] + a * bg[i]; return P; };
    // Learned copy counts are already smoothed by the trainer, so they get only a light pull toward the format.
    const archP = tmpl.map(T => shrink(T, L ? LEARNED_SHRINK : SHRINK));
    if (L) lcomp.forEach(({c}, i) => comps.push({name:c.name, prior:c.weight * lcomp.length, P:archP[i], signature:c.signature, topShare:c.topShare}));
    else arch.forEach((a,i) => comps.push({name:a.name, prior:1, P:archP[i]}));
    // A past duel only showed part of that deck, so fill the rest from whichever sketches it looked like.
    for (const r of recs){
      const n = new Int32Array(K); for (const [c, m] of r.counts) n[c] = Math.min(3, m);
      const f = Math.min(0.95, r.s / Math.max(r.size || 40, r.s + 1));
      const lw = archP.map(P => { let l = 0; for (let c=0;c<K;c++){ let s = 0; for (let j=0;j<4;j++) s += P[c*4+j] * seenLik(j, n[c], f); l += Math.log(Math.max(s, 1e-300)); } return l; });
      const mx = Math.max(...lw), aw = lw.map(l => Math.exp(l - mx)), aZ = aw.reduce((a,b)=>a+b, 0);
      const T = new Float64Array(K*4);
      for (let c=0;c<K;c++){
        if (n[c]){ const s = atLeast(n[c]); for (let j=0;j<4;j++) T[c*4+j] = s[j]; continue; }
        let z = 0; const q = [0,0,0,0];
        archP.forEach((P,i) => { for (let j=0;j<4;j++){ const v = aw[i]/aZ * P[c*4+j] * Math.pow(1-f, j); q[j] += v; z += v; } });
        for (let j=0;j<4;j++) T[c*4+j] = z > 0 ? q[j]/z : TECH[j];
      }
      const same = opp && r.opp === opp;
      const prior = same ? (Date.now() - r.t < SAME_MATCH_MS ? 12 : 3) : 0.3;
      comps.push({name: same ? `${r.opp}'s deck from ${when(r.t)}` : `${r.opp}'s deck, ${when(r.t)}`, prior, P:shrink(T, 0.2), record:true});
    }
  }

  // Update every component on what this duel has shown.
  const K = cards.length;
  const n = new Int32Array(K), vis = new Int32Array(K);
  let s = 0, vt = 0;
  for (const nm in seen){ const c = idx[norm(nm)] ?? idx[norm((lookupCard(nm)||{}).name || "")]; if (c !== undefined){ n[c] = Math.min(3, seen[nm]); s += n[c]; } }
  for (const nm in visible){ const c = idx[norm(nm)] ?? idx[norm((lookupCard(nm)||{}).name || "")]; if (c !== undefined){ vis[c] = Math.min(3, visible[nm]); vt += vis[c]; } }
  const Ntot = H + vt, f = guess ? Math.min(0.95, s / Math.max(Ntot, 1)) : 0;
  for (const cp of comps){
    let lw = Math.log(cp.prior); const cdf = new Float64Array(K*4), pm = new Float64Array(K*4), mix = [0,0,0]; let exp = 0;
    for (let c=0;c<K;c++){
      const q = [0,0,0,0]; let z = 0;
      for (let j=0;j<4;j++){ q[j] = cp.P[c*4+j] * (guess ? seenLik(j, n[c], f) : j >= n[c] ? 1 : 0); z += q[j]; }
      // A seen card the component can't explain: keep the component alive and let the card's count follow what was seen.
      if (z <= 0){ q.fill(0); q[n[c]] = 1e-6; z = 1e-6; }
      lw += Math.log(z);
      let acc = 0;
      for (let p=0;p<4;p++){ const j = p + vis[c]; acc += j < 4 ? q[j]/z : 0; cdf[c*4+p] = acc; }
      cdf[c*4+3] = 1;
      for (let j=0;j<4;j++){ pm[c*4+j] = q[j]/z; exp += j * q[j]/z; mix[typeIdx(cards[c].type)] += j * q[j]/z; }
    }
    const mz = mix[0] + mix[1] + mix[2] || 1;
    // Cards this component can plausibly put in the hidden pool. Rarer ones are left to the unlisted-card allowance,
    // which keeps sampling fast with a large learned vocabulary. Cards already seen are always kept.
    const live = []; for (let c=0;c<K;c++) if (cdf[c*4] < 0.998 || vis[c] || n[c]) live.push(c);
    Object.assign(cp, {lw, cdf, pm, mix: mix.map(x => x/mz), exp, live:Int32Array.from(live)});
  }
  const mx = Math.max(...comps.map(c => c.lw));
  let Z = 0; for (const c of comps){ c.w = Math.exp(c.lw - mx); Z += c.w; }
  for (const c of comps) c.w /= Z;
  const base = cards.length; OTHER.forEach(o => cards.push(Object.assign({}, o, {tags:[]})));
  return {cards, comps, K:base, H, vis, n, guess, f, Ntot};
}

// Turns the view into the simulation's inputs.
function build(){
  const duel = V && V.state === "duel";
  const pub = {}, kh = {}, seen = {};
  const canon = name => { const c = lookupCard(name); return c && c.type !== "X" ? c.name : null; };
  const acc = (o, name, k) => { const c = canon(name); if (c) o[c] = (o[c] || 0) + k; };
  if (duel){
    for (const nm in V.pub) acc(pub, nm, V.pub[nm]);
    for (const nm in V.kh) acc(kh, nm, V.kh[nm]);
    for (const nm in V.seen || {}){ const c = canon(nm); if (c) seen[c] = Math.max(seen[c] || 0, V.seen[nm]); }
  }
  const visible = {};
  for (const o of [pub, kh]) for (const nm in o) visible[nm] = (visible[nm] || 0) + o[nm];
  for (const nm in visible) seen[nm] = Math.max(seen[nm] || 0, visible[nm]);
  const hand = duel ? V.hand : [], sets = duel ? V.sets : [], lost = duel ? V.lost : 0;
  const listTotal = deckFor().deck.reduce((a,e) => a + e.count, 0);
  const H = duel ? V.deck + hand.length + sets.length + lost : settings.mode === "list" ? listTotal : 40;
  const M = buildModel(seen, visible, H, duel ? V.opp : null);
  const added = [];
  if (!M.guess){
    const counts = new Map(M.comps[0].counts);
    for (const nm in seen){ const k = M.cards.findIndex(e => e.name === nm); const m = counts.get(k) || 0; if (seen[nm] > m) added.push(`${nm}${m ? ` (list has ${m}, seen ${seen[nm]})` : ""}`); }
  }
  return {M, deck:M.cards, pub, kh, seen, added, hand, sets, lost, H, turn: duel ? V.turn : 0, duel, listTotal};
}
const khTotal = () => { let n = 0; for (const k in S.kh) n += S.kh[k]; return n; };

// ---------- Simulation ----------
function zoneOK(zone, type){ return zone === "mon" ? type === "M" : type !== "M"; }
function lik(ev, e){
  if (ev.kind === "tag") return e.tags.includes(ev.tag) ? 1 - ev.s : 1;
  if (ev.kind === "card") return e.name === ev.name ? 1 - ev.s : 1;
  if (ev.kind === "wasSet") return zoneOK(ev.zone, e.type) ? e.setW : 0;
  return 1;
}
// Each simulated deal first draws a whole deck from the model, then deals their hidden cards from it,
// weighting the deal by how well it fits the face-down and hand evidence.
function simulate(){
  const {M} = S, deck = M.cards, K = deck.length, KB = M.K, H = S.H;
  const nS = S.sets.length, nH = S.hand.length;
  const D = H - nS - nH - S.lost;
  if (D < 0) return {error:"Their hidden cards don't add up. Restart tracking under Tracking."};
  const setW = S.sets.map(sl => { const w = new Float64Array(K); deck.forEach((e,k) => { let v = zoneOK(sl.zone,e.type) ? e.setW : 0; for (const ev of sl.ev) v *= lik(ev,e); w[k] = v; }); return w; });
  const handW = S.hand.map(h => { if (!h.ev.length) return null; const w = new Float64Array(K); deck.forEach((e,k) => { let v = 1; for (const ev of h.ev) v *= lik(ev,e); w[k] = v; }); return w; });
  const nSlot = nS + nH, N = M.guess || M.comps.length > 1 ? 15000 : 30000;
  const assign = new Int16Array(N * Math.max(1,nSlot)), logw = new Float64Array(N);
  const pools = new Int8Array(N * K), compOf = new Int16Array(N);
  const cnt = new Int32Array(K), rw = new Float64Array(K);
  const ccum = []; { let a = 0; for (const c of M.comps){ a += c.w; ccum.push(a); } }
  // A sampled deck holds only a few dozen distinct cards, so slot picks loop over those (nz) instead of every card.
  const nz = new Int32Array(K); let nnz = 0;
  const pickW = (w, Z) => { let u = Math.random()*Z, acc = 0, last = -1; for (let q=0;q<nnz;q++){ const k = nz[q], m = cnt[k]*w[k]; if (m > 0){ last = k; acc += m; if (u < acc) return k; } } return last; };
  const pickU = R => { let u = Math.floor(Math.random()*R); for (let q=0;q<nnz;q++){ const k = nz[q]; if (u < cnt[k]) return k; u -= cnt[k]; } return -1; };
  for (let i=0;i<N;i++){
    let ci = 0; const u0 = Math.random() * ccum[ccum.length-1]; while (ci < ccum.length - 1 && u0 > ccum[ci]) ci++;
    const cp = M.comps[ci], cdf = cp.cdf; compOf[i] = ci;
    let sum = 0; cnt.fill(0);
    const live = cp.live;
    for (let q=0;q<live.length;q++){ const c = live[q], u = Math.random(); let p = 0; while (p < 3 && u > cdf[c*4+p]) p++; cnt[c] = p; sum += p; }
    cnt[KB] = cnt[KB+1] = cnt[KB+2] = 0;
    if (M.guess){ let x = 0, p = Math.exp(-TECH_MEAN), c = p; const u = Math.random(); while (u > c && x < 8){ x++; p *= TECH_MEAN / x; c += p; }
      for (; x > 0; x--, sum++){ const v = Math.random(); cnt[KB + (v < cp.mix[0] ? 0 : v < cp.mix[0] + cp.mix[1] ? 1 : 2)]++; } }
    // Make the deck the size DuelingBook shows. A short deck gains copies where the copy-count guess has room
    // (or an unlisted card); a long one loses copies where the guess allows fewer.
    const pm = cp.pm, vis = M.vis;
    for (; sum < H; sum++){
      let Z = UNLISTED;
      for (let q=0;q<live.length;q++){ const c = live[q], j = cnt[c] + vis[c]; rw[q] = j < 3 && pm[c*4+j] > 0 ? pm[c*4+j+1] / pm[c*4+j] : 0; Z += rw[q]; }
      let u = Math.random() * Z, q = 0;
      for (; q < live.length; q++){ u -= rw[q]; if (u < 0) break; }
      if (q < live.length) cnt[live[q]]++;
      else { const v = Math.random(); cnt[KB + (v < cp.mix[0] ? 0 : v < cp.mix[0] + cp.mix[1] ? 1 : 2)]++; }
    }
    if (sum > H){
      // Only cards in the deck can lose a copy, so work over those.
      nnz = 0; for (let q=0;q<live.length;q++) if (cnt[live[q]]) nz[nnz++] = live[q];
      for (let c=KB;c<K;c++) if (cnt[c]) nz[nnz++] = c;
      for (; sum > H; sum--){
        let Z = 0;
        for (let q=0;q<nnz;q++){ const c = nz[q], j = cnt[c] + (c < KB ? vis[c] : 0); rw[q] = !cnt[c] ? 0 : c >= KB ? cnt[c] : pm[c*4+j] > 0 ? pm[c*4+j-1] / pm[c*4+j] : 1; Z += rw[q]; }
        let u = Math.random() * Z, q = 0;
        if (Z > 0) for (; q < nnz - 1; q++){ u -= rw[q]; if (u < 0) break; }
        while (!cnt[nz[q]]) q = (q + 1) % nnz;
        cnt[nz[q]]--;
      }
    }
    pools.set(cnt.subarray(0, K), i*K);
    nnz = 0;
    for (let q=0;q<live.length;q++) if (cnt[live[q]]) nz[nnz++] = live[q];
    for (let c=KB;c<K;c++) if (cnt[c]) nz[nnz++] = c;
    let R = H, lw = 0, ok = true; const off = i*nSlot;
    for (let j=0;j<nSlot && ok;j++){
      const w = j < nS ? setW[j] : handW[j-nS];
      let k;
      if (w){ let Z = 0; for (let q=0;q<nnz;q++){ const c = nz[q]; Z += cnt[c]*w[c]; } if (Z <= 0){ ok = false; break; } k = pickW(w,Z); lw += Math.log(Z/R); }
      else k = pickU(R);
      if (k < 0){ ok = false; break; }
      cnt[k]--; R--; assign[off+j] = k;
    }
    logw[i] = ok ? lw : -Infinity;
  }
  let mx = -Infinity; for (let i=0;i<N;i++) if (logw[i] > mx) mx = logw[i];
  if (mx === -Infinity) return {error:"No deck and deal fits everything logged. Remove some evidence tags" + (M.guess ? "." : " or check the decklist.")};
  const tagArr = t => deck.map(e => e.tags.includes(t));
  const T = {atk:tagArr("atk"), sum:tagArr("sum"), rem:tagArr("rem"), mrem:tagArr("mrem"), ht:tagArr(F.fmt.handTag)};
  const khHas = t => deck.some((e,k) => T[t][k] && (S.kh[e.name]||0) > 0);
  const kAny = {rem:khHas("rem"), mrem:khHas("mrem"), ht:khHas("ht")};
  const setDist = S.sets.map(() => new Float64Array(K));
  const handAny = new Float64Array(K), handExp = new Float64Array(K), setExp = new Float64Array(K), next = new Float64Array(K);
  const deckExp = new Float64Array(K), unseenAny = new Float64Array(K), compPost = new Float64Array(M.comps.length);
  const th = {atk:0, sum:0, rem:0, mrem:0, ht:0};
  const tally = new Int32Array(K), seen = new Uint8Array(K), nzR = new Int32Array(K);
  let W = 0, W2 = 0;
  for (let i=0;i<N;i++){
    if (logw[i] === -Infinity) continue;
    const w = Math.exp(logw[i]-mx); W += w; W2 += w*w; const off = i*nSlot, po = i*K;
    compPost[compOf[i]] += w;
    tally.fill(0); seen.fill(0);
    let pn = 0; for (let k=0;k<K;k++) if (pools[po+k]) nzR[pn++] = k;
    for (let q=0;q<pn;q++){ const k = nzR[q], p = pools[po+k]; deckExp[k] += w * p; unseenAny[k] += w; }
    let a = false, s = false, r = kAny.rem, m = kAny.mrem, c = kAny.ht;
    for (let j=0;j<nS;j++){ const k = assign[off+j]; setDist[j][k] += w; setExp[k] += w; tally[k]++; if (S.sets[j].zone === "st"){ if (T.atk[k]) a = true; if (T.sum[k]) s = true; } }
    for (let j=nS;j<nSlot;j++){ const k = assign[off+j]; handExp[k] += w; tally[k]++; if (!seen[k]){ seen[k] = 1; handAny[k] += w; } if (T.rem[k]) r = true; if (T.mrem[k]) m = true; if (T.ht[k]) c = true; }
    if (D > 0){ const rem = H - nSlot; if (rem > 0) for (let q=0;q<pn;q++){ const k = nzR[q]; next[k] += w * (pools[po+k]-tally[k]) / rem; } }
    if (a) th.atk += w; if (s) th.sum += w; if (r) th.rem += w; if (m) th.mrem += w; if (c) th.ht += w;
  }
  const div = arr => { for (let k=0;k<arr.length;k++) arr[k] /= W; };
  setDist.forEach(div); div(handAny); div(handExp); div(setExp); div(next); div(deckExp); div(unseenAny); div(compPost);
  for (const k in th) th[k] /= W;
  deck.forEach((e,k) => { const v = (S.pub[e.name]||0) + (S.kh[e.name]||0); deckExp[k] += v; if ((S.kh[e.name]||0) > 0) handAny[k] = 1; handExp[k] += (S.kh[e.name]||0); });
  let ns = 0; for (let k=0;k<K;k++) ns += next[k]; if (ns > 0) for (let k=0;k<K;k++) next[k] /= ns;
  return {N, ess: W*W/W2, setDist, handAny, handExp, setExp, next, deckExp, unseenAny, compPost, th, D};
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
  if (settings.enabled === false || (V && V.state === "off")){ dot.className = "dot off"; c.textContent = "Tracking is off."; return; }
  if (!V || V.state === "loading"){ dot.className = "dot"; c.textContent = "Looking for a DuelingBook tab… Open duelingbook.com, or reload it if it was open before the extension."; return; }
  if (V.state === "idle"){ dot.className = "dot wait"; c.textContent = V.error ? `Connected, but the duel couldn't be read: ${V.error}` : "Connected to DuelingBook. Waiting for a duel to start."; return; }
  dot.className = "dot on";
  c.textContent = `${V.spectating ? "Watching" : "Live"}: tracking ${V.opp}${V.game > 1 ? `, game ${V.game}` : ""}.` + (V.hooked ? "" : " Duel events aren't coming through, so only the board is read and \"no response\" isn't logged automatically.");
}
function renderStatus(){
  const kh = khTotal(), st = S.sets.filter(x=>x.zone==="st").length, mon = S.sets.length - st;
  const item = (v,l,t) => `<div class="stat"${t ? ` title="${t}"` : ""}><b>${v}</b><span>${l}</span></div>`;
  const deck = V && V.state === "duel" ? V.deck : S.H;
  $("status").innerHTML = item(S.turn || "–","Turn") + item(deck,"Deck") + item(S.hand.length + kh, "Hand", kh ? `${S.hand.length + kh} cards, ${kh} known` : "") + item(st,"Backrow") + item(mon,"Set mons");
}
function renderLog(){
  const log = V && V.log || [];
  renderLogBadge();
  $("log").innerHTML = log.length ? log.slice().reverse().map(l => `<li class="${l.msg.startsWith("Auto:") ? "auto" : ""}"><span>T${l.t}</span><div>${esc(l.msg)}</div></li>`).join("") : `<li><span></span><div class="dim">Nothing logged yet. Plays show up here as they happen on DuelingBook.</div></li>`;
}
function renderBanner(res){
  let h = "";
  const d = deckFor(), list = settings.mode === "list";
  if (S.duel && V.caughtUp) h += `<div class="banner"><span>Tracking started partway through this duel, so it caught up from DuelingBook's duel log (${V.caughtUp.plays} of their plays). "No response" moments from before that weren't recorded.</span></div>`;
  if (list && d.sample) h += `<div class="banner"><span>Using the sample ${esc(F.fmt.sampleName)} list. Paste your opponent's list under Opponent decklist for better odds.</span></div>`;
  if (res && res.error) h += `<div class="err">${esc(res.error)}</div>`;
  if (S.added.length) h += `<div class="banner"><span>Seen but not in the list, so added for this duel: ${S.added.map(esc).join(", ")}.</span></div>`;
  if (list && S.duel && S.listTotal !== S.M.Ntot) h += `<div class="banner"><span>Their deck has ${S.M.Ntot} cards, but your list has ${S.listTotal}. The odds pad or trim the list to fit; check it for missing or extra cards.</span></div>`;
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
  const rows = S.deck.map((e,k) => [e,k]).filter(([e,k]) => res.deckExp[k] >= 0.05).sort((a,b) => res.deckExp[b[1]] - res.deckExp[a[1]]);
  $("alltable").innerHTML = `<table><thead><tr><th>Card</th><th class="n">${S.M.guess ? "In deck (est.)" : "In list"}</th><th class="n">Seen</th><th class="n">In hand</th><th class="n">Face-down</th><th class="n">Next draw</th></tr></thead><tbody>${
    rows.map(([e,k]) => { const seen = (S.pub[e.name]||0) + (S.kh[e.name]||0); return `<tr><td class="${tcls(e.type)}"><span class="pip"></span><span style="color:var(--ink)">${esc(e.name)}</span></td><td class="n">${S.M.guess ? res.deckExp[k].toFixed(1) : Math.round(res.deckExp[k])}</td><td class="n ${seen?"":"dim"}">${seen}</td><td class="n">${pct(res.handAny[k])}</td><td class="n">${res.setExp[k] > 0.005 ? res.setExp[k].toFixed(2) : "–"}</td><td class="n">${pct(res.next[k])}</td></tr>`; }).join("")
  }</tbody></table>`;
}
// What the model thinks they're playing, and its best guess at the list.
function renderGuess(res){
  if (!S.M.guess){
    const d = deckFor();
    $("guess").innerHTML = `<p class="meta" style="margin:0">Using ${d.sample ? `the sample ${esc(F.fmt.sampleName)} list` : "your pasted list"} (${S.listTotal} cards). Switch to guessing under Opponent decklist.</p>`;
    return;
  }
  const comps = S.M.comps.map((c,i) => [c, res.compPost[i]]).sort((a,b) => b[1]-a[1]);
  const top = comps.slice(0,4).filter(x => x[1] >= 0.01), restW = comps.slice(top.length).reduce((a,x) => a + x[1], 0);
  const seenN = Object.values(S.seen).reduce((a,b) => a+b, 0);
  const L = learned(), src = L ? ` Archetypes learned from ${L.decks.toLocaleString()} decklists${L.topping ? `, ${L.topping.toLocaleString()} of them topping lists` : ""}.` : "";
  const lead = !S.duel ? `No duel yet, so this is how often each deck gets played.${src}` : seenN ? `Guessed from ${seenN} card${seenN>1?"s":""} they've shown${S.M.comps.some(c => c.record) ? " and decks from your past duels" : ""}.${src}` : `They haven't shown a card yet.${src}`;
  const rows = S.deck.map((e,k) => [e, res.deckExp[k], (S.seen[e.name]||0)]).filter(x => !x[0].other && x[1] >= 0.35).sort((a,b) => b[1]-a[1] || b[2]-a[2]);
  const other = S.deck.reduce((a,e,k) => a + (e.other ? res.deckExp[k] : 0), 0);
  $("guess").innerHTML = `<p class="meta" style="margin:0 0 8px">${lead}</p>
  <div class="cands" style="margin-bottom:12px">${top.map(([c,p]) => `<div class="cand arch" style="grid-template-columns:minmax(0,1fr) 46px"><div class="nm"><span class="txt">${esc(c.name)}</span></div><div class="pc">${pct(p)}</div><div class="bar" style="grid-column:1/-1"><i style="width:${(p*100).toFixed(1)}%"></i></div>${c.signature ? `<div class="meta" style="grid-column:1/-1;margin-top:-1px">Runs ${c.signature.slice(0,3).map(esc).join(", ")}${c.topShare >= 0.005 ? ` · ${pct(c.topShare)} of topping lists` : c.topShare !== undefined ? " · casual, rarely tops" : ""}</div>` : ""}</div>`).join("")}${restW >= 0.01 ? `<div class="meta">Other decks: ${pct(restW)}</div>` : ""}</div>
  <details><summary class="sub">Best guess at their list</summary>
  <div class="tablewrap"><table><thead><tr><th>Card</th><th class="n">Seen</th><th class="n">Copies (est.)</th></tr></thead><tbody>${
    rows.map(([e,x,sn]) => `<tr><td class="${tcls(e.type)}"><span class="pip"></span><span style="color:var(--ink)">${esc(e.name)}</span></td><td class="n ${sn?"":"dim"}">${sn || "–"}</td><td class="n">${x.toFixed(1)}</td></tr>`).join("")
  }</tbody></table></div>
  <p class="meta" style="margin:6px 0 8px">Plus about ${other.toFixed(1)} card${Math.abs(other-1) < 0.05 ? "" : "s"} no known deck runs.</p>
  <button class="btn small" data-a="copyguess">Copy this guess into the decklist box</button></details>`;
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
  const off = settings.enabled === false;
  document.body.classList.toggle("off", off);
  document.body.classList.toggle("idle", !S.duel && !off);
  clearTimeout(simTimer);
  simTimer = setTimeout(() => {
    const t0 = performance.now();
    const res = simulate(); lastRes = res; simMs = Math.round(performance.now() - t0); renderBanner(res);
    if (res.error){ ["threats","guess","sets","hand","next","alltable"].forEach(id => $(id).innerHTML = ""); $("simmeta").textContent = ""; return; }
    renderThreats(res); renderGuess(res); renderSets(res); renderHand(res); renderNext(res); renderAll(res);
    saveDiag();
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
    decks[settings.format] = {text:txt, deck:d}; saveDecks(); setMode("list"); syncDeckUI(); commit();
    const unk = d.filter(e=>!e.known).length;
    toast(`Loaded ${total} cards.` + (d.skipped.length ? ` Skipped ${d.skipped.length} Extra Deck card${d.skipped.length>1?"s":""}.` : "") + (d.badIds ? ` ${d.badIds} card ID${d.badIds>1?"s":""} not found.` : "") + (unk ? ` ${unk} not recognized; set their type below.` : "") + (total < 40 || total > 60 ? " A main deck should be 40 to 60 cards; check the list." : ""));
  },
  copyguess(){
    if (!lastRes || lastRes.error) return;
    const lines = S.deck.map((e,k) => [e, Math.round(lastRes.deckExp[k])]).filter(([e,n]) => !e.other && n > 0).sort((a,b) => b[1]-a[1]).map(([e,n]) => `${n} ${e.name}`);
    $("decktext").value = `# Best guess at ${S.duel ? V.opp + "'s" : "their"} deck. Edit it, then press Load list to use it.\n` + lines.join("\n");
    showTab("deck"); $("d-deck").open = true; $("decktext").scrollIntoView({block:"center"});
    toast("Guess copied into the decklist box. Press Load list to use it as their list.");
  },
  forget(){ api.storage.local.set({"duel-history-v1":[]}); history = []; commit(); toast("Forgot all decks from past duels."); },
  sampledeck(){ $("decktext").value = F.sample; toast("Sample list pasted. Press Load list to use it."); },
};
function slotAction(act, id, extra, name){
  const slot = S.sets.find(x => x.id === id); if (!slot) return;
  if (act === "notcard") toTab({type:"evidence", scope:id, ev:{kind:"card", name, s:strength()}, text:`${slot.label} is likely not ${name} (${Math.round(strength()*100)}% sure).`});
  else if (act === "atk" || act === "sum") toTab({type:"evidence", scope:id, ev:{kind:"tag", tag:act, s:strength()}, text:`${slot.label}: ${EV_TEXT[act].toLowerCase()}.`});
  else if (act === "rmev") toTab({type:"rmev", id, index:extra});
}

function setMode(m){ settings.mode = m; saveSettings(); for (const r of document.querySelectorAll("input[name=mode]")) r.checked = r.value === m; }
for (const r of document.querySelectorAll("input[name=mode]")) r.addEventListener("change", () => { setMode(r.value); commit(); toast(r.value === "list" ? "Using the decklist below." : "Guessing their deck from what they play."); });

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
$("learned").addEventListener("change", () => { settings.learned = $("learned").checked; saveSettings(); commit(); });
function setPower(onNow){
  settings.enabled = onNow; saveSettings();
  $("enabled").checked = onNow; $("power-lbl").textContent = onNow ? "On" : "Off";
  commit();
}
$("enabled").addEventListener("change", () => { setPower($("enabled").checked); toast($("enabled").checked ? "Tracking is on. Catching up on the duel so far." : "Tracking is off. Nothing is read until you turn it back on."); });
ACTIONS.turnon = () => { setPower(true); toast("Tracking is on. Catching up on the duel so far."); };
$("auto").addEventListener("change", () => { settings.auto = $("auto").checked; saveSettings(); toast(settings.auto ? "\"No response\" will be logged automatically." : "Automatic \"no response\" logging is off."); });
$("side").addEventListener("change", () => { settings.side = $("side").value; saveSettings(); toast("Switched sides. Tracking restarts."); });

api.runtime.onMessage.addListener((msg, sender) => {
  if (!msg || msg.type !== "view" || !sender.tab) return;
  // With several DuelingBook tabs open, follow the one in front.
  if (tabId !== null && sender.tab.id !== tabId && !sender.tab.active) return;
  tabId = sender.tab.id; V = msg; commit();
});
// A duel that just ended joins the history the guesses learn from.
api.storage.onChanged.addListener((ch, area) => {
  if (area !== "local") return;
  if (ch["duel-history-v1"]){ history = ch["duel-history-v1"].newValue || []; commit(); }
  // Keeps the switch right when tracking is turned on or off from another panel window.
  const nv = ch.settings && ch.settings.newValue;
  if (nv && (nv.enabled !== false) !== (settings.enabled !== false)){
    settings.enabled = nv.enabled !== false;
    $("enabled").checked = settings.enabled; $("power-lbl").textContent = settings.enabled ? "On" : "Off";
    commit();
  }
});
const DB_ORIGINS = ["https://www.duelingbook.com/*","https://duelingbook.com/*"];
// Find a DuelingBook tab on open, preferring the one in front.
async function connect(){
  await checkAccess();
  let tabs = [];
  try { tabs = await api.tabs.query({url:DB_ORIGINS}); } catch (e){ noteError(e); }
  tabs.sort((a,b) => (b.active - a.active) || (b.lastAccessed||0) - (a.lastAccessed||0));
  for (const t of tabs){
    try {
      const v = await api.tabs.sendMessage(t.id, {type:"getView"});
      if (v){ tabId = t.id; V = v; commit(); return; }
    } catch (e){}
  }
  commit();
}
api.tabs.onActivated.addListener(async ({tabId:id}) => {
  try { const v = await api.tabs.sendMessage(id, {type:"getView"}); if (v){ tabId = id; V = v; commit(); } } catch (e){}
});
// Firefox can install with DuelingBook access switched off. Without it nothing runs on the page, so ask for it here.
async function checkAccess(){
  const box = $("perm");
  if (!api.permissions || !api.permissions.contains){ box.innerHTML = ""; return true; }
  let ok = true;
  try { ok = await api.permissions.contains({origins:DB_ORIGINS}); } catch (e){}
  box.innerHTML = ok ? "" : `<div class="perm"><b>The extension can't see DuelingBook yet.</b><span>Your browser needs your OK before the extension can read duels on duelingbook.com.</span><div class="row"><button class="btn primary" data-a="grant">Allow access to DuelingBook</button></div></div>`;
  return ok;
}
ACTIONS.grant = async () => {
  try {
    const ok = await api.permissions.request({origins:DB_ORIGINS});
    if (ok){ await checkAccess(); toast("Access granted. Reload your DuelingBook tab."); }
  } catch (e){ noteError(e); }
};

// ---------- Tabs ----------
let lastLogSeen = 0;
function showTab(name){
  for (const b of document.querySelectorAll(".tabs button")){
    const on = b.dataset.tab === name;
    b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1;
    $("pane-" + b.dataset.tab).hidden = !on;
  }
  if (name === "log"){ lastLogSeen = (V && V.log || []).length; renderLogBadge(); }
  try { localStorage.setItem("ygo-tab", name); } catch (e){}
}
let logPrimed = false;
function renderLogBadge(){
  const n = (V && V.log || []).length, b = $("logbadge"), onLog = !$("pane-log").hidden;
  // What was already logged when the panel opened isn't news.
  if (!logPrimed && n){ logPrimed = true; lastLogSeen = n; }
  if (onLog) lastLogSeen = n;
  const fresh = Math.max(0, n - lastLogSeen);
  b.hidden = !fresh; b.textContent = fresh > 99 ? "99+" : fresh;
}
$("logbadge").hidden = true;
document.querySelector(".tabs").addEventListener("click", ev => { const b = ev.target.closest("[data-tab]"); if (b) showTab(b.dataset.tab); });
document.querySelector(".tabs").addEventListener("keydown", ev => {
  if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
  const bs = [...document.querySelectorAll(".tabs button")], i = bs.findIndex(b => b.getAttribute("aria-selected") === "true");
  const nb = bs[(i + (ev.key === "ArrowRight" ? 1 : bs.length - 1)) % bs.length]; showTab(nb.dataset.tab); nb.focus();
});

// ---------- Diagnostics for the report page ----------
// The panel's side of a problem report: settings, the model's state and recent errors. No card names from their hand.
let simMs = 0, diagTimer = 0;
const panelErrors = [];
function noteError(e){
  const msg = String(e && (e.stack || e.message) || e).slice(0, 600);
  if (!panelErrors.length || panelErrors[panelErrors.length-1].msg !== msg) panelErrors.push({t:Date.now(), msg});
  if (panelErrors.length > 15) panelErrors.shift();
  saveDiag();
}
window.addEventListener("error", ev => noteError(ev.error || ev.message));
window.addEventListener("unhandledrejection", ev => noteError(ev.reason));
function saveDiag(){
  clearTimeout(diagTimer);
  diagTimer = setTimeout(() => {
    const res = lastRes || {};
    const comps = S && S.M && res.compPost ? S.M.comps.map((c,i) => [c.name, res.compPost[i]]).sort((a,b) => b[1]-a[1]).slice(0,5).map(([n,p]) => `${n} ${pct(p)}`) : [];
    const d = {t:Date.now(), version:VERSION, format:settings.format, mode:settings.mode, learned:!!learned(), auto:settings.auto, strength:settings.strength, side:settings.side,
      connected: V ? V.state : "none", hooked: V ? V.hooked : null, events: V ? V.events : 0,
      duel: S && S.duel ? {turn:V.turn, deck:V.deck, hand:S.hand.length, known:khTotal(), sets:S.sets.length, lost:S.lost, game:V.game, spectating:V.spectating} : null,
      model: S && S.M ? {cards:S.deck.length, comps:S.M.comps.length, top:comps, simMs, ess:Math.round(res.ess || 0), error:res.error || null} : null,
      history:history.length, errors:panelErrors.slice()};
    api.storage.local.set({"panel-diag":d}).catch(() => {});
  }, 500);
}

// ---------- Boot ----------
const VERSION = (() => { try { return api.runtime.getManifest().version; } catch (e){ return "dev"; } })();
$("version").textContent = `YGO Duel Odds ${VERSION}`;
let startTab = "odds"; try { startTab = localStorage.getItem("ygo-tab") || "odds"; } catch (e){}
showTab($("pane-" + startTab) ? startTab : "odds");
api.storage.local.get(["settings","decks","duel-history-v1"]).then(r => {
  if (r.settings) settings = Object.assign(settings, r.settings);
  if (r.decks) decks = r.decks;
  if (Array.isArray(r["duel-history-v1"])) history = r["duel-history-v1"];
  setMode(settings.mode);
  useFormat(settings.format);
  $("enabled").checked = settings.enabled !== false; $("power-lbl").textContent = settings.enabled !== false ? "On" : "Off";
  $("auto").checked = settings.auto; $("strength").value = Math.round(settings.strength*100); $("strength-out").textContent = $("strength").value + "%"; $("side").value = settings.side;
  syncDeckUI(); connect();
}).catch(noteError);
