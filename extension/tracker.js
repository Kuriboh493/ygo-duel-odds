// Content script on DuelingBook. Turns the page hook's board snapshots and duel events into a "view"
// of the opponent's public information, and sends it to the side panel, which works out the odds.
// It lives as long as the tab, so closing and reopening the panel mid-duel loses nothing.
(function(){
  "use strict";
  const api = globalThis.browser || globalThis.chrome;
  const TAG = "__ygoOdds";
  const STORE = "tracker-duel-v1";
  const HISTORY = "duel-history-v1", HISTORY_MAX = 80;
  const EV_TEXT = {atk:"ignored an attack", sum:"ignored a summon", neg:"let a card resolve", hatk:"no hand trap on attack"};
  // Plays that don't end a response window: chat, thinking, targeting.
  const NEUTRAL = new Set(["Duel message","Edit duel message","Thinking","Good","Stop good","Target card","Look at cards","Look at opponent cards","Look at top card","Stop viewing","Show hand","Show deck","Show ED","Show Extra Deck","Check Options","Countdown","Pause game","Resume game","Call admin","Cancel call","Add watcher","Remove watcher"]);
  const SUMMON = /^(Normal Summon|Flip Summon|SS ATK|SS DEF|S\. Summon|OL ATK|OL DEF)/;
  const ATTACK = /^Attack/;
  const ACTIVATE_ST = /^(Activate ST|Activate Spell|Activate Field Spell|Activate$|Activate )/;
  const PHASE = /^(Enter (BP|M2|EP|DP|SP|M1)|End turn)$/;
  const WINDOW_MS = 30000;

  let settings = {enabled:true, auto:true, strength:0.7, side:"auto"};
  const on = () => settings.enabled !== false;
  let T = null, snap = null, hooked = false, events = 0, timer = 0, sendTimer = 0;

  // maxSeen: the most copies of each card identified at once this duel. Cards shuffled back into the deck still count.
  // soft: hand cards marked known only because the duel log suggested it (see catchUp).
  function blank(key){ return {key, game:1, known:{}, soft:{}, wasSet:{}, sets:{}, nst:0, nmon:0, ev:{}, log:[], windows:[], lastTurn:0, maxSeen:{}, size:0, started:Date.now()}; }
  function save(){ try { api.storage.local.set({[STORE]:T}).catch(noteError); } catch (e){ noteError(e); } }

  // ---------- Diagnostics ----------
  // Kept for the report page: recent errors, a short event history and counters. Events keep only public card names.
  const diag = {errors:[], recent:[], snapshots:0, started:Date.now(), lastSnapshot:null};
  function noteError(e){
    const msg = String(e && (e.stack || e.message) || e).slice(0, 600);
    const last = diag.errors[diag.errors.length - 1];
    if (last && last.msg === msg){ last.n++; return; }
    diag.errors.push({t:Date.now(), msg, n:1});
    if (diag.errors.length > 20) diag.errors.shift();
  }
  const guard = fn => function(){ try { return fn.apply(this, arguments); } catch (e){ noteError(e); } };
  function clientVersion(){
    const el = document.querySelector('script[src*="duel.js"]');
    const m = el && el.src.match(/[?&]v=([^&]+)/);
    return m ? m[1] : null;
  }
  function diagnostics(){
    const s = snap;
    return {
      page: location.host + location.pathname, client: clientVersion(), hooked, events, snapshots: diag.snapshots,
      upMinutes: Math.round((Date.now() - diag.started) / 60000), settings,
      snapshot: !s ? null : s.ok ? {label:s.label, turn:s.turn, phase:s.phase, spectating:s.spectating, hand:s.hand.length, field:s.field.length,
        faceDown:s.field.filter(c => c.fd).length, gy:s.gy.length, banished:s.ban.length, deck:s.deck, extra:s.extra,
        missingIds: s.hand.concat(s.field).filter(c => !c.id).length, me:s.me, opp:s.opp} : {ok:false, label:s.label || "", error:s.error || null},
      tracker: !T ? null : {game:T.game, known:Object.keys(T.known).length, sets:Object.keys(T.sets).length, evidence:Object.values(T.ev).reduce((a,l) => a + l.length, 0), windows:T.windows.length, log:T.log.slice(-40)},
      recentEvents: diag.recent.slice(), errors: diag.errors.slice(),
    };
  }
  function log(msg){ T.log.push({t: snap && snap.turn || T.lastTurn || 0, msg}); if (T.log.length > 300) T.log.splice(0, T.log.length - 300); }

  api.storage.local.get(["settings", STORE]).then(r => {
    if (r.settings) settings = Object.assign(settings, r.settings);
    // Restores the duel after a page reload. A duel already being tracked wins over a stale save.
    if (!on()) T = null;
    else if (r[STORE] && r[STORE].key && (!T || T.key === r[STORE].key)){ T = r[STORE]; T.maxSeen = T.maxSeen || {}; T.soft = T.soft || {}; if (snap) onSnapshot(snap); }
    toHook("side", settings.side); toHook("pause", !on()); send();
  }).catch(noteError);
  api.storage.onChanged.addListener((ch, area) => {
    if (area !== "local" || !ch.settings) return;
    const prevSide = settings.side, wasOn = on();
    settings = Object.assign(settings, ch.settings.newValue || {});
    if (settings.side !== prevSide){ toHook("side", settings.side); T = null; }
    // Turning tracking off forgets the duel. Turning it back on starts over from the board and the duel log.
    if (on() !== wasOn){ T = null; closeWindowsQuiet(); toHook("pause", !on()); if (!on()) api.storage.local.remove(STORE).catch(noteError); }
    send();
  });
  function toHook(kind, data){ window.postMessage({[TAG]:"tracker", kind, data}, "*"); }

  // ---------- Snapshots ----------
  const onBoard = s => s.field.length + s.gy.length + s.ban.length;
  // Each finished duel is kept so the panel can learn which decks you run into.
  function record(){
    if (!T || !T.opp) return;
    let n = 0; for (const k in T.maxSeen) n += T.maxSeen[k];
    if (n < 4) return;
    const rec = {fmt:settings.format || "goat", opp:T.opp, seen:T.maxSeen, size:T.size || 40, t:T.started || Date.now()};
    api.storage.local.get([HISTORY]).then(r => {
      const h = Array.isArray(r[HISTORY]) ? r[HISTORY] : [];
      h.push(rec); if (h.length > HISTORY_MAX) h.splice(0, h.length - HISTORY_MAX);
      return api.storage.local.set({[HISTORY]:h});
    }).catch(noteError);
  }
  function startDuel(s, why){
    record();
    const key = `${s.duelId || ""}|${s.me}|${s.opp}`;
    const game = T && T.key === key ? T.game + 1 : 1;
    T = blank(key); T.game = game; T.opp = s.opp;
    log(why || `Duel against ${s.opp} started.`);
    // If this duel is already under way, DuelingBook's duel log fills in what happened before.
    toHook("history");
  }

  // ---------- Catching up from the duel log ----------
  // Reads this game's public log lines. Every card name in the opponent's lines proves their deck runs it.
  // A card they sent to hand and haven't mentioned since is probably still there, so it's marked as known,
  // softly: the mark moves off as soon as they play a copy of that card.
  const GAME_START = /^Chose to go (first|second)$/;
  const SKIP_LINE = /target|attack/i;
  const TO_HAND = /\bto (?:the |their |your )?hand\b/i;
  function catchUp(entries){
    if (!T || !snap || !snap.ok || T.caughtUp || !Array.isArray(entries)) return;
    let start = 0;
    entries.forEach((e, i) => { if (GAME_START.test(e.text)) start = i; });
    const game = entries.slice(start).filter(e => e.type === "duel" || GAME_START.test(e.text));
    const opp = snap.opp, me = snap.me, toHand = {}, mentioned = {};
    let plays = 0, turn = 0;
    const earlier = [];
    for (const e of game){
      if (GAME_START.test(e.text)) turn = 1;
      else if (e.text === "Entered Draw Phase") turn++;
      if (e.u === opp || e.u === me) earlier.push({t:turn || 1, msg:`Earlier · ${e.u === opp ? "They" : "You"}: ${e.text}`});
      if (e.u !== opp) continue;
      plays++;
      if (SKIP_LINE.test(e.text)) continue;
      const names = [...e.text.matchAll(/"([^"]+)"/g)].map(m => m[1]);
      for (const n of names){
        mentioned[n] = true;
        if (TO_HAND.test(e.text)) toHand[n] = (toHand[n] || 0) + 1;
        else if (!/revealed/i.test(e.text) && toHand[n] > 0) toHand[n]--;
      }
    }
    T.caughtUp = {plays, at:Date.now()};
    if (!plays) return;
    T.log.splice(0, 0, ...earlier.slice(-80));
    for (const n in mentioned) T.maxSeen[n] = Math.max(T.maxSeen[n] || 0, 1);
    const free = handIds(), inHand = [];
    for (const n in toHand) for (let k = 0; k < toHand[n] && free.length; k++){ const id = free.shift(); T.known[id] = n; T.soft[id] = true; inHand.push(n); }
    T.caughtUp.inHand = inHand;
    log(`Caught up from DuelingBook's duel log: read ${plays} of their plays from before tracking started.` + (inHand.length ? ` Probably still in their hand: ${inHand.join(", ")}.` : ""));
    save(); send();
  }
  function onSnapshot(s){
    const prev = snap; snap = s;
    if (!s.ok || !on()){ send(); return; }
    const key = `${s.duelId || ""}|${s.me}|${s.opp}`;
    if (!T || T.key !== key) startDuel(s);
    // A cleared board with a refilled deck means the next game of the match began.
    else if (prev && prev.ok && onBoard(prev) > 0 && onBoard(s) === 0 && s.deck > prev.deck + 5) startDuel(s, `Game ${T.game + 1} against ${s.opp} started.`);
    if (s.turn !== T.lastTurn){ if (T.lastTurn) closeWindows(true); T.lastTurn = s.turn; }

    for (const c of s.field) if (!c.fd && c.name && c.id) T.known[c.id] = c.name;
    for (const c of s.gy) if (c.name && c.id) T.known[c.id] = c.name;
    for (const c of s.ban) if (!c.fd && c.name && c.id) T.known[c.id] = c.name;
    // A card shuffled back into the deck is anonymous again.
    for (const id of s.deckIds){ delete T.known[id]; delete T.wasSet[id]; delete T.ev[id]; delete T.sets[id]; }

    const live = new Set();
    for (const c of s.field){
      if (!c.fd || !c.id || T.known[c.id]) continue;
      live.add(c.id);
      if (!T.sets[c.id]){
        const n = c.zone === "st" ? ++T.nst : ++T.nmon;
        T.sets[c.id] = {label: (c.zone === "st" ? "Spell/trap " : "Monster ") + n, turn: s.turn, zone: c.zone};
      }
      T.sets[c.id].zone = c.zone;
      T.wasSet[c.id] = c.zone;
    }
    for (const id in T.sets) if (!live.has(id)) delete T.sets[id];
    const vis = visible();
    for (const n in vis) if (vis[n] > (T.maxSeen[n] || 0)) T.maxSeen[n] = vis[n];
    T.size = Math.max(T.size || 0, s.deck + s.hand.length + s.field.length + s.gy.length + s.ban.length);
    save(); send();
  }

  // ---------- Events ----------
  function describe(e){
    const n = e.name ? ` ${e.name}` : "";
    const p = e.play;
    if (p === "Draw card") return "Drew a card.";
    if (/^Set ST|^Set \(To S\/T\)|^Set Field Spell/.test(p)) return "Set a spell/trap.";
    if (/^Set monster/.test(p)) return "Set a monster.";
    if (p === "End turn") return "Ended their turn.";
    if (p === "Shuffle deck") return "Shuffled their deck.";
    if (p === "Shuffle hand") return "Shuffled their hand.";
    return `${p}${n ? ":" + n : ""}.`;
  }
  function onEvent(e){
    events++; hooked = true;
    if (!on() || !T || !snap || !snap.ok) return;
    T.soft = T.soft || {};
    // They played a copy of a card the duel log put in their hand: that was probably the one.
    if (e.who === "opp" && e.name && e.id && !T.soft[e.id]){
      const sid = Object.keys(T.soft).find(id => T.known[id] === e.name);
      if (sid){ delete T.soft[sid]; delete T.known[sid]; }
    }
    if (e.who === "opp" && e.id && e.name && /^(Reveal|To hand)/.test(e.play) && !e.discreet){ T.known[e.id] = e.name; delete T.soft[e.id]; }
    if (e.who === "opp"){
      if (e.play === "Thinking"){ armTimer(); return; }
      if (NEUTRAL.has(e.play)) return;
      if (T.windows.length){ log(`They responded, so no "no response" evidence was logged.`); T.windows = []; }
      log(describe(e));
    } else if (e.who === "me"){
      if (NEUTRAL.has(e.play)) return;
      closeWindows(true);
      if (settings.auto && !PHASE.test(e.play)) openWindows(e);
    }
    save(); send();
  }
  function stIds(){ return snap.field.filter(c => c.zone === "st" && c.fd && c.id && T.sets[c.id]).map(c => c.id); }
  function handIds(){ return snap.hand.filter(c => c.id && !T.known[c.id]).map(c => c.id); }
  function openWindows(e){
    const add = (tag, ids, where) => { if (ids.length) T.windows.push({tag, ids, where, play:e.play, name:e.name || null}); };
    if (ATTACK.test(e.play)){ add("atk", stIds(), "backrow"); add("hatk", handIds(), "hand"); }
    else if (SUMMON.test(e.play)) add("sum", stIds(), "backrow");
    else if (ACTIVATE_ST.test(e.play) && (!e.ctype || /Spell|Trap/i.test(e.ctype))) add("neg", stIds(), "backrow");
    if (T.windows.length) armTimer();
  }
  function armTimer(){ clearTimeout(timer); timer = setTimeout(() => { closeWindows(true); save(); send(); }, WINDOW_MS); }
  function closeWindowsQuiet(){ clearTimeout(timer); }
  function closeWindows(commit){
    clearTimeout(timer);
    if (!T || !T.windows.length) return;
    if (commit){
      const s = settings.strength;
      for (const w of T.windows){
        const ids = w.ids.filter(id => w.where === "hand" ? snap && snap.hand.some(c => c.id === id) : T.sets[id]);
        if (!ids.length) continue;
        for (const id of ids) (T.ev[id] = T.ev[id] || []).push({kind:"tag", tag:w.tag, s, auto:true});
        const what = w.name ? `${w.play}: ${w.name}` : w.play;
        log(`Auto: ${w.where === "hand" ? "hand" : `${ids.length} face-down`} ${EV_TEXT[w.tag]} (${what}, ${Math.round(s*100)}% sure).`);
      }
    }
    T.windows = [];
  }

  // ---------- View for the panel ----------
  // Cards currently identified: face-up, in the GY, face-up banished, or known in hand or face-down.
  function counts(){
    const pub = {}, kh = {};
    const inc = (o, k) => { o[k] = (o[k] || 0) + 1; };
    for (const c of snap.field){ const n = c.fd ? T.known[c.id] : c.name; if (n) inc(pub, n); }
    for (const c of snap.gy) if (c.name) inc(pub, c.name);
    for (const c of snap.ban){ const n = c.fd ? T.known[c.id] : c.name; if (n) inc(pub, n); }
    for (const c of snap.hand){ const n = c.id && T.known[c.id]; if (n) inc(kh, n); }
    return {pub, kh};
  }
  function visible(){ const {pub, kh} = counts(); for (const n in kh) pub[n] = (pub[n] || 0) + kh[n]; return pub; }
  function view(){
    const base = {type:"view", hooked, events, settings};
    if (!on()) return Object.assign(base, {state:"off"});
    if (!snap) return Object.assign(base, {state:"loading"});
    if (!snap.ok || !T) return Object.assign(base, {state:"idle", label:snap.label || "", error:snap.error || null});
    const {pub, kh} = counts();
    const lost = snap.ban.filter(c => c.fd && !T.known[c.id]).length;
    const hand = [];
    for (const c of snap.hand){
      if (c.id && T.known[c.id]) continue;
      const ev = (T.ev[c.id] || []).slice();
      if (c.id && T.wasSet[c.id]) ev.push({kind:"wasSet", zone:T.wasSet[c.id]});
      hand.push({id:c.id, ev});
    }
    const sets = [];
    for (const c of snap.field){
      if (!c.fd || !c.id || !T.sets[c.id]) continue;
      const info = T.sets[c.id];
      sets.push({id:c.id, zone:c.zone, label:info.label, turn:info.turn, ev:T.ev[c.id] || []});
    }
    return Object.assign(base, {
      state:"duel", key:T.key, game:T.game, me:snap.me, opp:snap.opp, spectating:snap.spectating,
      turn:snap.turn, myTurn:snap.turnPlayer === snap.me, phase:snap.phase,
      deck:snap.deck, extra:snap.extra, pub, kh, seen:T.maxSeen, caughtUp:T.caughtUp && T.caughtUp.plays ? T.caughtUp : null, hand, sets, lost, log:T.log.slice(-120), pending:T.windows.length,
    });
  }
  function send(){
    clearTimeout(sendTimer);
    // Rejects when no panel is open, which is normal.
    sendTimer = setTimeout(() => { try { api.runtime.sendMessage(view()).catch(() => {}); } catch (e){} }, 60);
  }

  // ---------- Messages ----------
  window.addEventListener("message", ev => {
    const d = ev.data;
    if (ev.source !== window || !d || d[TAG] !== "hook") return;
    if (d.kind === "hooked"){ hooked = true; send(); }
    else if (d.kind === "error") noteError("Page hook: " + d.data);
    else if (d.kind === "history") guard(catchUp)(d.data);
    else if (d.kind === "snapshot"){
      diag.snapshots++;
      if (d.data && d.data.error) noteError("Board read failed: " + d.data.error);
      guarded.onSnapshot(d.data);
    }
    else if (d.kind === "event"){
      const e = d.data || {};
      diag.recent.push({t:Date.now(), play:e.play, who:e.who, name:e.name || null, turn:e.turn});
      if (diag.recent.length > 40) diag.recent.shift();
      guarded.onEvent(e);
    }
  });
  const guarded = {onSnapshot: guard(onSnapshot), onEvent: guard(onEvent)};
  api.runtime.onMessage.addListener((msg, sender, reply) => {
    if (!msg || !msg.type) return;
    if (msg.type === "getView"){ reply(view()); return; }
    if (msg.type === "diag"){ reply(diagnostics()); return; }
    if (!T || !snap || !snap.ok){ reply({ok:false}); return; }
    if (msg.type === "evidence"){
      // ev: {kind:"tag", tag, s} or {kind:"card", name, s}; scope: "hand", "backrow" or one card id.
      const ids = msg.scope === "hand" ? handIds() : msg.scope === "backrow" ? stIds() : [msg.scope];
      for (const id of ids) (T.ev[id] = T.ev[id] || []).push(msg.ev);
      if (msg.text) log(msg.text);
    } else if (msg.type === "rmev"){
      const list = T.ev[msg.id];
      if (list && list[msg.index]) list.splice(msg.index, 1);
    } else if (msg.type === "newduel"){
      startDuel(snap, "Tracking restarted from the current board.");
      onSnapshot(snap); reply({ok:true}); return;
    }
    save(); send(); reply({ok:true});
  });
  toHook("resend");

  // Chrome and Firefox start page-hook.js inside the page themselves (world: MAIN in the manifest).
  // Safari may not, so if the hook hasn't answered shortly after load, add it to the page by hand.
  // page-hook.js ignores a second copy, so this is safe everywhere.
  let hookSeen = false;
  window.addEventListener("message", ev => { const d = ev.data; if (ev.source === window && d && d[TAG] === "hook") hookSeen = true; });
  toHook("ping");
  setTimeout(() => {
    if (hookSeen) return;
    try {
      const s = document.createElement("script");
      s.src = api.runtime.getURL("page-hook.js");
      s.onload = () => { s.remove(); toHook("resend"); toHook("side", settings.side); toHook("pause", !on()); };
      (document.head || document.documentElement).appendChild(s);
    } catch (e){ noteError(e); }
  }, 1500);
})();
