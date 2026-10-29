// Runs in DuelingBook's own page context (world: MAIN) so it can see the duel client's globals.
// It reads the opponent's side of the board and taps duel events, then hands both to tracker.js.
// Only public information leaves this file: names are sent for face-up cards and revealed cards, never for hand or face-down cards.
(function(){
  "use strict";
  if (window.__ygoOddsHook) return;
  window.__ygoOddsHook = true;

  const TAG = "__ygoOdds";
  const post = (kind, data) => window.postMessage({[TAG]:"hook", kind, data}, "*");
  let sideOverride = "auto", paused = false;
  window.addEventListener("message", ev => {
    const d = ev.data;
    if (ev.source !== window || !d || d[TAG] !== "tracker") return;
    if (d.kind === "side"){ sideOverride = d.data || "auto"; lastSig = ""; }
    if (d.kind === "pause"){ paused = !!d.data; lastSig = ""; }
    if (d.kind === "history") post("history", history());
    if (d.kind === "ping") post("pong", true);
    if (d.kind === "exec"){
      let res;
      try { res = execute(d.data && d.data.req || {}); } catch (e){ res = {ok:false, reason:String(e && e.message || e)}; }
      post("execResult", Object.assign({rid: d.data && d.data.rid}, res));
    }
    if (d.kind === "resend"){ lastSig = ""; if (window.duelResponse && window.duelResponse.__ygoOdds) post("hooked", true); }
  });

  // Duel globals are classic-script globals, so typeof is the only safe probe.
  const G = {
    p1: () => typeof player1 !== "undefined" ? player1 : null,
    p2: () => typeof player2 !== "undefined" ? player2 : null,
    me: () => typeof username !== "undefined" ? username : null,
    label: () => typeof currentLabel !== "undefined" ? currentLabel : "",
    turn: () => typeof turnCount !== "undefined" ? turnCount : 0,
    turnPlayer: () => typeof turn_player !== "undefined" && turn_player ? turn_player.username : null,
    phase: () => typeof currentPhase !== "undefined" ? currentPhase : "",
    duelId: () => typeof duelId !== "undefined" ? duelId : null,
    linkL: () => typeof linkLeft !== "undefined" ? linkLeft : null,
    linkR: () => typeof linkRight !== "undefined" ? linkRight : null,
  };
  const DUEL_LABELS = new Set(["rps_start","tp_start","tp_start2","duel_start","duel_start1","duel_start2","duel_start3","duel_start4","siding"]);

  function sides(){
    const p1 = G.p1(), p2 = G.p2(), me = G.me();
    if (!p1 || !p2 || !p1.username || !p2.username) return null;
    let opp;
    if (sideOverride === "p1") opp = p1;
    else if (sideOverride === "p2") opp = p2;
    else if (me && p1.username === me) opp = p2;
    else if (me && p2.username === me) opp = p1;
    else opp = p2;
    const spectating = !(me && (p1.username === me || p2.username === me));
    return {opp, mine: opp === p1 ? p2 : p1, spectating};
  }

  const isCard = el => el && typeof el.data === "function";
  function front(el){
    const cf = el.data("cardfront");
    if (!cf || typeof cf.data !== "function") return {name:null, ctype:null};
    return {name: cf.data("name") || null, ctype: cf.data("card_type") || null};
  }
  // pub: the zone is public, so a face-up card's name may be read.
  function read(el, pub){
    if (!isCard(el)) return null;
    const id = el.data("id"); const fd = !!el.data("face_down");
    const c = {id: id === undefined || id === null ? null : String(id), fd};
    if (pub && !fd){ const f = front(el); c.name = f.name; c.ctype = f.ctype; }
    return c;
  }
  const list = arr => Array.isArray(arr) ? arr : [];

  function snapshot(){
    const sd = sides(); const label = G.label();
    if (!sd || !DUEL_LABELS.has(label)) return {ok:false, label};
    const {opp, mine} = sd;
    const field = [];
    const zones = [["m1","mon"],["m2","mon"],["m3","mon"],["m4","mon"],["m5","mon"],["s1","st"],["s2","st"],["s3","st"],["s4","st"],["s5","st"],["fieldSpell","st"],["pendulumLeft","st"],["pendulumRight","st"]];
    for (const p of [opp, mine]){
      for (const [z, kind] of zones){
        const el = p[z]; if (!isCard(el)) continue;
        // Cards follow their owner, so a monster they took from me doesn't count as theirs.
        const owner = el.data("owner") || p;
        if (owner !== opp) continue;
        const c = read(el, true); if (c){ c.zone = kind; c.slot = z; field.push(c); }
      }
    }
    for (const el of [G.linkL(), G.linkR()]){
      if (!isCard(el)) continue;
      const owner = el.data("owner") || el.data("controller");
      if (owner !== opp) continue;
      const c = read(el, true); if (c){ c.zone = "mon"; c.slot = "emz"; field.push(c); }
    }
    const hand = list(opp.hand_arr).map(el => read(el, false)).filter(Boolean);
    const gy = list(opp.grave_arr).map(el => read(el, true)).filter(Boolean);
    const ban = list(opp.banished_arr).map(el => read(el, true)).filter(Boolean);
    const deckIds = list(opp.main_arr).map(el => isCard(el) ? el.data("id") : null).filter(x => x !== null && x !== undefined).map(String);
    return {
      ok:true, label, spectating: sd.spectating, me: mine.username, opp: opp.username,
      duelId: G.duelId(), turn: G.turn(), turnPlayer: G.turnPlayer(), phase: G.phase(),
      hand, field, gy, ban, deck: list(opp.main_arr).length, deckIds, extra: list(opp.extra_arr).length,
    };
  }

  // DuelingBook's own duel log, for catching up when tracking starts partway through a duel.
  // Only the public text is passed on: the same lines both players see in the Duel Log window.
  function history(){
    try {
      const L = typeof duel_logs !== "undefined" && Array.isArray(duel_logs) ? duel_logs : [];
      return L.filter(e => e && !e.hidden).map(e => ({u: e.username || null, type: e.type || null, text: String(e.public_log || "")}));
    } catch (e){ return []; }
  }

  let lastSig = "";
  function tick(){
    if (paused) return;
    let snap;
    try { snap = snapshot(); } catch (e){ snap = {ok:false, error:String(e && e.message || e)}; }
    const sig = JSON.stringify(snap);
    if (sig !== lastSig){ lastSig = sig; post("snapshot", snap); }
  }
  setInterval(tick, 250);

  // Opponent plays whose card is shown to both players. Everything else keeps its name out of the event.
  const PUBLIC_PLAY = /^(Activate|Normal Summon|Flip Summon|Flip$|Flip monster|SS |S\. Summon|OL |Summon Token|To GY|To Graveyard|To grave|Mill|Reveal|To hand|Attack|To ATK|To DEF|To ST from grave|Banish(?!.*FD))/;
  function summarize(d){
    const sd = sides();
    const who = !sd ? "other" : d.username === sd.opp.username ? "opp" : d.username === sd.mine.username ? "me" : "other";
    const e = {play: String(d.play || ""), who, id: d.id === undefined || d.id === null ? null : String(d.id), discreet: !!d.discreet, turn: G.turn(), phase: G.phase()};
    const card = d.card && typeof d.card === "object" ? d.card : null;
    const showName = who === "me" || (who === "opp" && PUBLIC_PLAY.test(e.play) && !e.discreet && !/FD/.test(e.play));
    if (card && showName){ e.name = card.name || null; e.ctype = card.card_type || null; }
    return e;
  }
  function wrap(){
    if (typeof window.duelResponse !== "function" || window.duelResponse.__ygoOdds) return;
    const orig = window.duelResponse;
    const wrapped = function(data){
      // The board as it was just before this play goes first, so the tracker sees what the play responded to.
      try { if (data && data.play && !paused){ tick(); post("event", summarize(data)); } } catch (e){ post("error", String(e && e.message || e)); }
      return orig.apply(this, arguments);
    };
    wrapped.__ygoOdds = true;
    window.duelResponse = wrapped;
    post("hooked", true);
  }
  wrap(); setInterval(wrap, 1000);

  // ---------- Auto-play executor ----------
  // Lists and performs plays through the client's own menu code, exactly as hovering and clicking would.
  // Locked to DuelingBook's Solo mode, where you control both sides, so it never plays against another person.
  const isSolo = () => typeof solo !== "undefined" && solo === true;
  const GLOBAL_PLAYS = new Set(["Enter DP","Enter SP","Enter M1","Enter BP","Enter M2","Enter EP","End turn"]);
  const MIN_GAP_MS = 300;
  const SKIP_ITEMS = new Set(["This is backwards","This looks right"]);
  let lastExec = 0;

  // Runs a menu builder with showMenu swapped for a recorder, so the menu's items come back instead of appearing.
  function captureMenu(build){
    if (typeof showMenu !== "function") return [];
    const real = window.showMenu; let items = null;
    window.showMenu = (card, list) => { items = list; };
    try { build(); } catch (e){} finally { window.showMenu = real; }
    return (items || []).map(i => i && (i.data || i.label)).filter(x => x && !SKIP_ITEMS.has(x));
  }
  function menuFor(el){
    const content = el.find && el.find(".content:first")[0];
    if (!content || typeof cardMenuE !== "function") return [];
    return captureMenu(() => cardMenuE.call(content));
  }
  function ownCards(p, side){
    const out = [], add = (el, zone) => { if (isCard(el)) out.push({el, zone, side}); };
    list(p.hand_arr).forEach(el => add(el, "hand"));
    for (const z of ["m1","m2","m3","m4","m5"]) add(p[z], "monster");
    for (const z of ["s1","s2","s3","s4","s5","pendulumLeft","pendulumRight"]) add(p[z], "spell/trap");
    add(p.fieldSpell, "field");
    list(p.grave_arr).forEach(el => add(el, "graveyard"));
    list(p.banished_arr).forEach(el => add(el, "banished"));
    return out;
  }
  function describeCard(c){
    const f = front(c.el);
    return {id: String(c.el.data("id")), name: f.name, ctype: f.ctype, zone: c.zone, side: c.side, faceDown: !!c.el.data("face_down"),
            position: c.zone === "monster" ? (c.el.data("inDEF") ? "DEF" : "ATK") : null};
  }
  function moves(){
    const p1 = G.p1(), p2 = G.p2();
    const base = {solo: isSolo(), label: G.label(), turn: G.turn(), turnPlayer: G.turnPlayer(), phase: G.phase(), me: p1 && p1.username, other: p2 && p2.username};
    if (!base.solo || !p1 || !p2) return Object.assign(base, {cards: [], deck: [], globals: []});
    // In Solo you control both sides, so both are listed.
    const cards = ownCards(p1, "player1").concat(ownCards(p2, "player2")).map(c => Object.assign(describeCard(c), {options: menuFor(c.el)}));
    const deck = typeof showDeckMenu === "function" && list(p1.main_arr).length ? captureMenu(() => showDeckMenu()) : [];
    const targets = [];
    for (const [p, side] of [[p1, "player1"], [p2, "player2"]]) for (const z of ["m1","m2","m3","m4","m5"]) if (isCard(p[z])) targets.push(Object.assign(describeCard({el: p[z], zone: "monster", side})));
    return Object.assign(base, {cards, deck, globals: [...GLOBAL_PLAYS], monsters: targets});
  }
  function findCard(id){
    const p1 = G.p1(), p2 = G.p2();
    return ownCards(p1, "player1").concat(ownCards(p2, "player2")).find(c => String(c.el.data("id")) === String(id)) || null;
  }
  function execute(req){
    if (req.type === "moves") return {ok: true, moves: moves()};
    if (!isSolo()) return {ok: false, reason: "Auto-play only runs in DuelingBook's Solo mode."};
    if (Date.now() - lastExec < MIN_GAP_MS) return {ok: false, reason: "Too soon after the last play."};
    if (typeof Send !== "function" || typeof cardMenuClicked !== "function") return {ok: false, reason: "DuelingBook's play functions weren't found."};
    const p1 = G.p1();
    if (req.type === "global"){
      if (!GLOBAL_PLAYS.has(req.play)) return {ok: false, reason: `"${req.play}" isn't a phase or turn play.`};
      lastExec = Date.now(); Send({action: "Duel", play: req.play});
      return {ok: true};
    }
    if (req.type === "deck"){
      const opts = captureMenu(() => showDeckMenu());
      if (!opts.includes(req.play)) return {ok: false, reason: `"${req.play}" isn't on the deck's menu right now.`};
      lastExec = Date.now(); cardMenuClicked(list(p1.main_arr)[0], req.play);
      return {ok: true};
    }
    if (req.type === "card"){
      const c = findCard(req.card);
      if (!c) return {ok: false, reason: "That card isn't in a hand, on the field, in a graveyard or banished."};
      const opts = menuFor(c.el);
      if (!opts.includes(req.play)) return {ok: false, reason: `"${req.play}" isn't on that card's menu right now.`, options: opts};
      lastExec = Date.now();
      if (req.play === "Attack"){
        // The click version asks you to pick a target with the mouse; send the chosen one directly instead.
        const t = req.target && findCard(req.target);
        if (!t || t.zone !== "monster" || t.side === c.side) return {ok: false, reason: "Attack needs one of the other side's monsters as its target."};
        Send({action: "Duel", play: "Attack", attacking_card: c.el.data("id"), attacked_card: t.el.data("id")});
        return {ok: true};
      }
      cardMenuClicked(c.el, req.play);
      return {ok: true};
    }
    return {ok: false, reason: "Unknown request."};
  }
})();
