// Content script on DuelingBook. Turns the page hook's board snapshots and duel events into a "view"
// of the opponent's public information, and sends it to the side panel, which works out the odds.
// It lives as long as the tab, so closing and reopening the panel mid-duel loses nothing.
(function(){
  "use strict";
  const TAG = "__ygoOdds";
  const STORE = "tracker-duel-v1";
  const EV_TEXT = {atk:"ignored an attack", sum:"ignored a summon", neg:"let a card resolve", hatk:"no hand trap on attack"};
  // Plays that don't end a response window: chat, thinking, targeting.
  const NEUTRAL = new Set(["Duel message","Edit duel message","Thinking","Good","Stop good","Target card","Look at cards","Look at opponent cards","Look at top card","Stop viewing","Show hand","Show deck","Show ED","Show Extra Deck","Check Options","Countdown","Pause game","Resume game","Call admin","Cancel call","Add watcher","Remove watcher"]);
  const SUMMON = /^(Normal Summon|Flip Summon|SS ATK|SS DEF|S\. Summon|OL ATK|OL DEF)/;
  const ATTACK = /^Attack/;
  const ACTIVATE_ST = /^(Activate ST|Activate Spell|Activate Field Spell|Activate$|Activate )/;
  const PHASE = /^(Enter (BP|M2|EP|DP|SP|M1)|End turn)$/;
  const WINDOW_MS = 30000;

  let settings = {auto:true, strength:0.7, side:"auto"};
  let T = null, snap = null, hooked = false, events = 0, timer = 0, sendTimer = 0;

  function blank(key){ return {key, game:1, known:{}, wasSet:{}, sets:{}, nst:0, nmon:0, ev:{}, log:[], windows:[], lastTurn:0}; }
  function save(){ try { chrome.storage.local.set({[STORE]:T}); } catch (e){} }
  function log(msg){ T.log.push({t: snap && snap.turn || T.lastTurn || 0, msg}); if (T.log.length > 300) T.log.splice(0, T.log.length - 300); }

  chrome.storage.local.get(["settings", STORE], r => {
    if (r.settings) settings = Object.assign(settings, r.settings);
    // Restores the duel after a page reload. A duel already being tracked wins over a stale save.
    if (r[STORE] && r[STORE].key && (!T || T.key === r[STORE].key)){ T = r[STORE]; if (snap) onSnapshot(snap); }
    toHook("side", settings.side);
  });
  chrome.storage.onChanged.addListener((ch, area) => {
    if (area !== "local" || !ch.settings) return;
    const prevSide = settings.side;
    settings = Object.assign(settings, ch.settings.newValue || {});
    if (settings.side !== prevSide){ toHook("side", settings.side); T = null; }
    send();
  });
  function toHook(kind, data){ window.postMessage({[TAG]:"tracker", kind, data}, "*"); }

  // ---------- Snapshots ----------
  const onBoard = s => s.field.length + s.gy.length + s.ban.length;
  function startDuel(s, why){
    const key = `${s.duelId || ""}|${s.me}|${s.opp}`;
    const game = T && T.key === key ? T.game + 1 : 1;
    T = blank(key); T.game = game;
    log(why || `Duel against ${s.opp} started.`);
  }
  function onSnapshot(s){
    const prev = snap; snap = s;
    if (!s.ok){ send(); return; }
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
    if (!T || !snap || !snap.ok) return;
    if (e.who === "opp" && e.id && e.name && /^(Reveal|To hand)/.test(e.play) && !e.discreet) T.known[e.id] = e.name;
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
  function view(){
    const base = {type:"view", hooked, events, settings};
    if (!snap) return Object.assign(base, {state:"loading"});
    if (!snap.ok || !T) return Object.assign(base, {state:"idle", label:snap.label || "", error:snap.error || null});
    const pub = {}, kh = {};
    const inc = (o, k) => { o[k] = (o[k] || 0) + 1; };
    for (const c of snap.field){ const n = c.fd ? T.known[c.id] : c.name; if (n) inc(pub, n); }
    for (const c of snap.gy) if (c.name) inc(pub, c.name);
    let lost = 0;
    for (const c of snap.ban){ const n = c.fd ? T.known[c.id] : c.name; if (n) inc(pub, n); else lost++; }
    const hand = [];
    for (const c of snap.hand){
      const n = c.id && T.known[c.id];
      if (n){ inc(kh, n); continue; }
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
      deck:snap.deck, extra:snap.extra, pub, kh, hand, sets, lost, log:T.log.slice(-120), pending:T.windows.length,
    });
  }
  function send(){
    clearTimeout(sendTimer);
    sendTimer = setTimeout(() => { try { chrome.runtime.sendMessage(view()).catch(() => {}); } catch (e){} }, 60);
  }

  // ---------- Messages ----------
  window.addEventListener("message", ev => {
    const d = ev.data;
    if (ev.source !== window || !d || d[TAG] !== "hook") return;
    if (d.kind === "hooked"){ hooked = true; send(); }
    else if (d.kind === "snapshot") onSnapshot(d.data);
    else if (d.kind === "event") onEvent(d.data);
  });
  chrome.runtime.onMessage.addListener((msg, sender, reply) => {
    if (!msg || !msg.type) return;
    if (msg.type === "getView"){ reply(view()); return; }
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
})();
