"use strict";
// The odds model for MTG Arena. Has no page or browser dependencies, so tools/test_mtga.py can run it directly.
// It follows extension/panel.js: their deck is a mixture of components that hold a copy-count distribution for each card.
// What they show reweights the components, and each simulated deal samples a whole deck, then deals their hidden cards.
// Magic differs in two ways: a threat only counts if their open mana can pay for it, and "no response" evidence only
// counts against cards they could have paid for at that moment.
var MtgOdds = (function(){
  const TECH_MEAN = 1.5;      // cards no known deck runs, on average, in a guessed deck
  const UNLISTED = 0.12;      // pull of "a card no known deck runs" when a sampled deck is short
  const OTHER = [
    {name:"Unlisted land", type:"L", cost:"", cmc:0, tags:[], other:true},
    {name:"Unlisted spell", type:"S", cost:"", cmc:0, tags:[], other:true},
  ];

  // ---------- Cards ----------
  const norm = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, "");
  function parseCards(raw){
    const byName = {};
    for (const line of String(raw || "").split("\n")){
      const f = line.split("\t"); if (f.length < 7) continue;
      const c = {name:f[0], type:f[1], cmc:+f[2], cost:f[3], produced:f[4], tags:[...f[5]]};
      byName[norm(f[0])] = c;
      if (f[0].includes(" // ")) byName[norm(f[0].split(" // ")[0])] = c;
    }
    return byName;
  }
  const BASIC = /^(Snow-Covered )?(Plains|Island|Swamp|Mountain|Forest)$|^Wastes$/;

  // ---------- Mana ----------
  // Colored symbols of a cost. Each is the colors that can pay it. Phyrexian symbols can be paid with life, so they're free here.
  function pips(cost){
    const out = [];
    for (const m of String(cost || "").matchAll(/\{([^}]+)\}/g)){
      const s = m[1];
      if (/^\d+$/.test(s) || s === "X" || s.includes("P")) continue;
      out.push(s.split("/").filter(x => "WUBRGC".includes(x)).join(""));
    }
    return out.filter(Boolean);
  }
  function castable(card, sources){
    if (!card || card.other) return false;
    if (sources.length < card.cmc) return false;
    const need = pips(card.cost);
    if (need.length > sources.length) return false;
    // Match each colored symbol to its own source. Costs are short, so a small search is enough.
    const used = new Array(sources.length).fill(false);
    const go = i => {
      if (i === need.length) return true;
      for (let s = 0; s < sources.length; s++){
        if (used[s] || ![...need[i]].some(x => sources[s].includes(x))) continue;
        used[s] = true;
        if (go(i + 1)){ used[s] = false; return true; }
        used[s] = false;
      }
      return false;
    };
    return go(0);
  }

  // ---------- Deck model ----------
  const binom = (n, k) => { let r = 1; for (let i = 1; i <= k; i++) r = r * (n - k + i) / i; return r; };
  const seenLik = (j, n, f) => j < n ? 0 : binom(j, n) * Math.pow(f, n) * Math.pow(1 - f, j - n);
  // A basic land's count is spread around the archetype's average. There's no four-copy limit on these.
  function basicPmf(mean, maxN){
    const sd = Math.max(1, mean * 0.25), L = Math.max(maxN + 3, Math.ceil(mean + 3 * sd) + 1), p = [];
    for (let j = 0; j < L; j++) p.push(Math.exp(-0.5 * ((j - mean) / sd) ** 2));
    const z = p.reduce((a, b) => a + b, 0);
    return p.map(x => x / z);
  }
  const techPmf = cap => cap === 1 ? [0.97, 0.03] : [0.97, 0.03, 0, 0, 0];

  // input: {lookup, comps:[{name,prior,copies:{card:[p0..p4]},basics:{card:mean},list?:bool,counts?}], seen, visible, H, singleton}
  function buildModel(input){
    const {lookup, seen, visible, H} = input;
    const cards = [], idx = {};
    const add = name => {
      const k = norm(name);
      if (idx[k] !== undefined) return idx[k];
      const c = lookup(name);
      idx[k] = cards.length;
      cards.push(c);
      return idx[k];
    };
    for (const cp of input.comps){
      for (const n in cp.copies) add(n);
      for (const n in cp.basics || {}) add(n);
      for (const n in cp.counts || {}) add(n);
    }
    for (const n in seen) add(n);
    const K = cards.length;
    const n = new Int32Array(K), vis = new Int32Array(K);
    let s = 0, vt = 0;
    for (const nm in seen){ const c = add(nm); n[c] = seen[nm]; s += n[c]; }
    for (const nm in visible){ const c = add(nm); vis[c] = visible[nm]; vt += vis[c]; }
    const guess = !input.comps.some(c => c.list);
    const Ntot = H + vt, f = guess ? Math.min(0.95, s / Math.max(Ntot, 1)) : 0;
    const comps = input.comps.map(cp => {
      const q = new Array(K); let lw = Math.log(cp.prior), landExp = 0, totalExp = 0;
      for (let c = 0; c < K; c++){
        const nm = cards[c].name, basic = BASIC.test(nm);
        let p;
        if (cp.list) { const m = (cp.counts && cp.counts[nm]) || 0, a = new Array(Math.max(m, n[c]) + 1).fill(0); a[Math.max(m, n[c])] = 1; p = a; }
        else if (basic) p = (cp.basics && cp.basics[nm] !== undefined) ? basicPmf(cp.basics[nm], n[c]) : basicPmf(0.2, n[c]);
        else if (cp.copies && cp.copies[nm]) p = cp.copies[nm].slice();
        else p = techPmf(input.singleton ? 1 : 4);
        while (p.length <= n[c]) p.push(0);
        const post = p.map((x, j) => x * (guess ? seenLik(j, n[c], f) : j >= n[c] ? 1 : 0));
        let z = post.reduce((a, b) => a + b, 0);
        // A seen card the component can't explain: keep the component alive and let the count follow what was seen.
        if (z <= 0){ post.fill(0); post[n[c]] = 1e-6; z = 1e-6; }
        lw += Math.log(z);
        q[c] = post.map(x => x / z);
        const e = q[c].reduce((a, x, j) => a + j * x, 0);
        totalExp += e; if (cards[c].type === "L") landExp += e;
      }
      const live = [];
      for (let c = 0; c < K; c++) if (q[c][0] < 0.998) live.push(c);
      // Unlisted cards take the mix of lands and spells the component already shows, or a typical deck's when it shows nothing.
      const landShare = totalExp >= 20 ? landExp / totalExp : 0.41;
      return {name:cp.name, signature:cp.signature, shareOf:cp.decks, record:cp.record, lw, q, live, landShare, list:!!cp.list};
    });
    const mx = Math.max(...comps.map(c => c.lw));
    let Z = 0; for (const c of comps){ c.w = Math.exp(c.lw - mx); Z += c.w; }
    for (const c of comps) c.w /= Z;
    const KB = cards.length;
    OTHER.forEach(o => cards.push(Object.assign({}, o)));
    return {cards, comps, K:KB, vis, n, H, guess, f, Ntot};
  }

  // ---------- Simulation ----------
  // How much a hidden hand card's identity fits one piece of evidence. strength is how sure they'd have used it.
  function evFactor(ev, card, strength, cache){
    if (ev.land) return card.type === "L" ? 1 - 0.95 : 1;
    if (!ev.tags.some(t => card.tags.includes(t))) return 1;
    const key = ev.n + "|" + card.name;
    if (!cache.has(key)) cache.set(key, castable(card, ev.mana));
    return cache.get(key) ? 1 - strength * (ev.w === undefined ? 1 : ev.w) : 1;
  }

  // Each threat is "a card in hand with one of these tags that this mana can pay for".
  const THREATS = {
    counter:{tags:["c","n"], mana:"open"},
    removal:{tags:["r"], mana:"open"},
    trick:{tags:["t"], mana:"open"},
    flash:{tags:["f"], mana:"open"},
    wipe:{tags:["w"], mana:"next"},
  };

  // view fields: hand:[{id,ev}], kh, pub, lost, library, mana, manaAll. N is the number of deals.
  function simulate(M, view, opts){
    const deck = M.cards, K = deck.length, KB = M.K, H = M.H;
    const slots = view.hand || [], nH = slots.length, lost = view.lost || 0;
    const strength = opts.strength === undefined ? 0.7 : opts.strength;
    const ignored = opts.ignored || new Set();
    if (H - nH - lost < 0) return {error:"Their hidden cards don't add up. Press Restart in Settings."};
    const N = opts.N || 8000, cache = new Map();
    const open = view.mana || [], next = (view.manaAll || []).concat(["WUBRG"]);
    const handW = slots.map(sl => {
      const evs = (sl.ev || []).filter(ev => !ignored.has(ev.n));
      if (!evs.length) return null;
      const w = new Float64Array(K);
      deck.forEach((e, k) => { let v = 1; for (const ev of evs) v *= evFactor(ev, e, strength, cache); w[k] = v; });
      return w;
    });
    const threat = {}, threatMask = {};
    for (const t in THREATS){
      threat[t] = 0;
      const src = THREATS[t].mana === "open" ? open : next;
      threatMask[t] = deck.map(e => THREATS[t].tags.some(x => e.tags.includes(x)) && castable(e, src));
    }
    const khHas = t => deck.some((e, k) => threatMask[t][k] && (view.kh || {})[e.name] > 0);
    const kAny = {}; for (const t in THREATS) kAny[t] = khHas(t);
    const ccum = []; { let a = 0; for (const c of M.comps){ a += c.w; ccum.push(a); } }
    const cnt = new Int32Array(K), rw = new Float64Array(K), nz = new Int32Array(K);
    const handAny = new Float64Array(K), handExp = new Float64Array(K), nextDraw = new Float64Array(K), deckExp = new Float64Array(K);
    const compPost = new Float64Array(M.comps.length), landDist = new Float64Array(nH + 1);
    const tally = new Int32Array(K), seen = new Uint8Array(K);
    const logws = new Float64Array(N);
    const rows = [];
    let bestLog = -Infinity;
    for (let i = 0; i < N; i++){
      let ci = 0; const u0 = Math.random() * ccum[ccum.length - 1];
      while (ci < ccum.length - 1 && u0 > ccum[ci]) ci++;
      const cp = M.comps[ci], live = cp.live;
      cnt.fill(0); let sum = 0;
      for (let q = 0; q < live.length; q++){
        const c = live[q], p = cp.q[c];
        let u = Math.random(), j = 0;
        while (j < p.length - 1 && u > p[j]){ u -= p[j]; j++; }
        const hid = Math.max(0, j - M.vis[c]);
        cnt[c] = hid; sum += hid;
      }
      if (M.guess){
        let x = 0, pr = Math.exp(-TECH_MEAN), acc = pr; const u = Math.random();
        while (u > acc && x < 8){ x++; pr *= TECH_MEAN / x; acc += pr; }
        for (; x > 0; x--, sum++) cnt[KB + (Math.random() < cp.landShare ? 0 : 1)]++;
      }
      // Make the deck the size the game shows. Short decks gain copies the guess has room for, or unlisted cards.
      for (; sum < H; sum++){
        let Z = UNLISTED;
        for (let q = 0; q < live.length; q++){
          const c = live[q], j = cnt[c] + M.vis[c], p = cp.q[c];
          rw[q] = j + 1 < p.length && p[j] > 0 ? p[j+1] / p[j] : 0;
          Z += rw[q];
        }
        let u = Math.random() * Z, q = 0;
        for (; q < live.length; q++){ u -= rw[q]; if (u < 0) break; }
        if (q < live.length) cnt[live[q]]++;
        else cnt[KB + (Math.random() < cp.landShare ? 0 : 1)]++;
      }
      // Long decks lose copies where the guess allows fewer.
      for (; sum > H; sum--){
        let n0 = 0, Z = 0;
        for (let c = 0; c < K; c++){
          if (!cnt[c]) continue;
          const j = cnt[c] + (c < KB ? M.vis[c] : 0);
          const v = c >= KB ? cnt[c] : (cp.q[c][j] > 0 ? cp.q[c][j-1] / cp.q[c][j] : 1);
          nz[n0] = c; rw[n0] = v; Z += v; n0++;
        }
        let u = Math.random() * Z, q = 0;
        if (Z > 0) for (; q < n0 - 1; q++){ u -= rw[q]; if (u < 0) break; }
        cnt[nz[q]]--;
      }
      // Deal the hand from the deck, weighted by the evidence on each card.
      let nn = 0; for (let c = 0; c < K; c++) if (cnt[c]) nz[nn++] = c;
      const pool = cnt.slice();
      let R = H, lw = 0, ok = true; const dealt = new Int32Array(nH);
      for (let j = 0; j < nH && ok; j++){
        const w = handW[j];
        let k = -1;
        if (w){
          let Z = 0; for (let q = 0; q < nn; q++){ const c = nz[q]; Z += cnt[c] * w[c]; }
          if (Z <= 0){ ok = false; break; }
          let u = Math.random() * Z;
          for (let q = 0; q < nn; q++){ const c = nz[q], m = cnt[c] * w[c]; if (m > 0){ k = c; if (u < m) break; u -= m; } }
          lw += Math.log(Z / R);
        } else {
          let u = Math.floor(Math.random() * R);
          for (let q = 0; q < nn; q++){ const c = nz[q]; if (u < cnt[c]){ k = c; break; } u -= cnt[c]; }
        }
        if (k < 0){ ok = false; break; }
        cnt[k]--; R--; dealt[j] = k;
      }
      logws[i] = ok ? lw : -Infinity;
      if (ok && lw > bestLog) bestLog = lw;
      rows.push(ok ? {ci, pool, dealt} : null);
    }
    if (bestLog === -Infinity) return {error:"No deck and hand fits everything logged. Turn off some evidence."};
    let W = 0, W2 = 0;
    const rem = H - nH;
    for (let i = 0; i < N; i++){
      const r = rows[i]; if (!r) continue;
      const w = Math.exp(logws[i] - bestLog); W += w; W2 += w * w;
      compPost[r.ci] += w;
      tally.fill(0); seen.fill(0);
      const hits = {}; for (const t in THREATS) hits[t] = kAny[t];
      let lands = 0;
      for (let j = 0; j < nH; j++){
        const k = r.dealt[j];
        handExp[k] += w; tally[k]++;
        if (!seen[k]){ seen[k] = 1; handAny[k] += w; }
        if (deck[k].type === "L") lands++;
        for (const t in THREATS) if (threatMask[t][k]) hits[t] = true;
      }
      landDist[lands] += w;
      for (const t in THREATS) if (hits[t]) threat[t] += w;
      for (let k = 0; k < K; k++){
        const p = r.pool[k]; if (!p) continue;
        deckExp[k] += w * p;
        if (rem > 0) nextDraw[k] += w * (p - tally[k]) / rem;
      }
    }
    const div = a => { for (let k = 0; k < a.length; k++) a[k] /= W; };
    div(handAny); div(handExp); div(nextDraw); div(deckExp); div(compPost); div(landDist);
    for (const t in threat) threat[t] /= W;
    deck.forEach((e, k) => {
      const kn = (view.kh || {})[e.name] || 0, pb = (view.pub || {})[e.name] || 0;
      deckExp[k] += kn + pb;
      if (kn > 0) handAny[k] = 1;
      handExp[k] += kn;
    });
    let ns = 0; for (let k = 0; k < K; k++) ns += nextDraw[k];
    if (ns > 0) for (let k = 0; k < K; k++) nextDraw[k] /= ns;
    return {N, ess:W * W / W2, handAny, handExp, nextDraw, deckExp, compPost, threat, landDist, knownLands:deck.reduce((a, e) => a + (e.type === "L" ? (view.kh || {})[e.name] || 0 : 0), 0)};
  }

  return {parseCards, castable, pips, buildModel, simulate, norm, BASIC};
})();
if (typeof window !== "undefined") window.MtgOdds = MtgOdds;
