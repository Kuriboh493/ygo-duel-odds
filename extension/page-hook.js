// Runs in DuelingBook's own page context (world: MAIN) so it can see the duel client's globals.
// It reads the opponent's side of the board and taps duel events, then hands both to tracker.js.
// Only public information leaves this file: names are sent for face-up cards and revealed cards, never for hand or face-down cards.
(function(){
  "use strict";
  if (window.__ygoOddsHook) return;
  window.__ygoOddsHook = true;

  const TAG = "__ygoOdds";
  const post = (kind, data) => window.postMessage({[TAG]:"hook", kind, data}, "*");
  let sideOverride = "auto", paused = false, recording = false;
  window.addEventListener("message", ev => {
    const d = ev.data;
    if (ev.source !== window || !d || d[TAG] !== "tracker") return;
    if (d.kind === "side"){ sideOverride = d.data || "auto"; lastSig = ""; }
    if (d.kind === "pause"){ paused = !!d.data; lastSig = ""; }
    if (d.kind === "record") recording = !!d.data;
    if (d.kind === "bot"){ bot.on = !!(d.data && d.data.on); bot.keepHosting = !!(d.data && d.data.keepHosting); }
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
      try { if (data && data.play) recordDecision(data); } catch (e){ post("error", "Recording: " + String(e && e.message || e)); }
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

  // ---------- Bot account mode: duels against people who chose to play the bot ----------
  // Plays against a person are only allowed when all of these hold: bot account mode is on, the account's
  // name says it's a bot, the duel is unrated, the opponent joined a duel the bot hosted under the label below,
  // and the bot has told them in the duel chat that it's a program. It only ever plays its own cards, on its own turn.
  const BOT_NOTE = "\u{1F916} BOT: you'll be playing YGO Duel Odds, a computer program. Unrated.";
  const BOT_HELLO = "Hi! I'm a bot: a computer program trained to play this format, run by its owner to test it. Good luck, have fun!";
  const bot = {on: false, keepHosting: false, hosted: false, consented: new Set(), announced: new Set(), lastLabel: "", acts: {}};
  const isBotAccount = () => /bot/i.test(G.me() || "");
  const duelKey = () => { const sd = sides(); return `${G.duelId()}|${sd ? sd.opp.username : ""}|${typeof games !== "undefined" ? games : ""}`; };
  function botLock(){
    const sd = sides();
    if (!bot.on) return "Bot account mode is off.";
    if (!isBotAccount()) return "The logged-in account's name has to say it's a bot (contain \"bot\").";
    if (!sd || sd.spectating) return "Not in a duel.";
    if (typeof rated === "undefined" || rated !== false) return "Bot account mode only plays unrated duels.";
    if (!bot.consented.has(sd.opp.username)) return "This opponent didn't join the bot's labeled duel, so it won't play them.";
    if (!bot.announced.has(duelKey())) return "Waiting to tell the opponent in chat that they're playing a bot.";
    return null;
  }
  // Why plays aren't allowed right now, or null when they are.
  function playLock(){
    if (isSolo()) return null;
    const why = botLock();
    return why === "Bot account mode is off." ? "Auto-play only runs in DuelingBook's Solo mode, or in bot account mode." : why;
  }
  const botMine = () => { const sd = sides(); return sd ? sd.mine : null; };
  const myTurnNow = () => typeof turn_player !== "undefined" && turn_player === botMine();
  const once = (key, fn) => { if (bot.acts[key]) return; bot.acts[key] = true; try { fn(); } catch (e){ post("error", "Bot: " + (e && e.message || e)); } };
  function duelChat(message){ if (typeof Send === "function") Send({action: "Duel", play: "Duel message", message, html: 0}); }
  // Hosts an unrated duel under the bot label, through the client's own Host form.
  function botHost(fmt){
    if (!bot.on || !isBotAccount()) return {ok: false, reason: "Turn on bot account mode, logged in as an account whose name says it's a bot."};
    if (G.label() !== "duel_room") return {ok: false, reason: "Open DuelingBook's Duel Room first."};
    if (typeof hostDuel !== "function" || typeof $ !== "function") return {ok: false, reason: "DuelingBook's Host form wasn't found."};
    const format = fmt === "edison" ? "eu" : "gu";
    $("#host .format_cb").val(format); $("#host .type_cb").val("m");
    $("#host .duel_note_txt").val(BOT_NOTE); $("#host .duel_password_txt").val("");
    bot.hosted = true;
    hostDuel();
    return {ok: true};
  }
  // Answers the parts of a duel around the plays: accepting a joiner, rock-paper-scissors, going first, the
  // announcement, and side decking (it keeps its deck as it is). Each happens once, a moment after it's asked for.
  function botTick(){
    if (!bot.on || !isBotAccount()) return;
    const label = G.label(), me = G.me();
    if (label !== bot.lastLabel){ bot.lastLabel = label; bot.acts = {}; bot.enteredAt = Date.now(); }
    const waited = Date.now() - (bot.enteredAt || 0) > 1500;
    if (!waited) return;
    const sd = sides(), consented = sd && bot.consented.has(sd.opp.username);
    // A tie resets the pick, so it picks again whenever the client is waiting for one.
    if (label === "rps_start" && consented && typeof pickedRPS !== "undefined" && !pickedRPS && typeof chooseRPS === "function" && Date.now() - (bot.lastRps || 0) > 3000){
      bot.lastRps = Date.now(); bot.dueled = true;
      try { const pick = [rock1, paper1, scissors1][Math.floor(Math.random() * 3)]; chooseRPS.call(pick[0]); } catch (e){ post("error", "Bot: " + (e && e.message || e)); }
    }
    if ((label === "tp_start" || label === "tp_start2") && consented && typeof rpsWinner !== "undefined" && rpsWinner === me && typeof pickFirst === "function")
      once("first", () => pickFirst.call(first.find(".content")[0]));
    if (/^duel_start/.test(label) && consented && !bot.announced.has(duelKey()))
      once("hello", () => { duelChat(BOT_HELLO); bot.announced.add(duelKey()); });
    if (label === "siding" && consented && typeof doneSiding === "function") once("side", () => doneSiding());
    // Hosts again only after a duel was actually played, never because hosting was cancelled.
    if (label === "duel_room" && bot.keepHosting && bot.dueled && !(typeof hosting !== "undefined" && hosting))
      once("rehost", () => { bot.dueled = false; botHost(bot.format); });
  }
  setInterval(() => { try { botTick(); } catch (e){} }, 1000);
  // Someone asked to join a duel: accept them only into the bot's own labeled duel.
  function wrapJoin(){
    if (typeof window.joinDuelResponse !== "function" || window.joinDuelResponse.__ygoOdds) return;
    const orig = window.joinDuelResponse;
    const wrapped = function(data){
      const r = orig.apply(this, arguments);
      try {
        const who = data && data.username;
        if (bot.on && isBotAccount() && bot.hosted && who && who !== G.me()) setTimeout(() => {
          if (!(typeof hosting !== "undefined" && hosting)) return;
          const cell = $("#joinlist .cell2").filter(function(){ return $(this).data("username") === who; }).first();
          bot.consented.add(who);
          if (cell.length && typeof acceptUser === "function"){ $("#joinlist .cell2").removeClass("selected"); cell.addClass("selected"); acceptUser(); }
          else Send({action: "Accept user", username: who});
        }, 2000);
      } catch (e){ post("error", "Bot: " + (e && e.message || e)); }
      return r;
    };
    wrapped.__ygoOdds = true; window.joinDuelResponse = wrapped;
  }
  wrapJoin(); setInterval(wrapJoin, 1000);
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
    const lock = playLock(), solo_ = isSolo();
    const base = {solo: solo_, allowed: !lock, lock, mode: solo_ ? "solo" : "bot", isBotAccount: isBotAccount(), botOn: bot.on, label: G.label(),
                  turn: G.turn(), turnPlayer: G.turnPlayer(), phase: G.phase(), me: p1 && p1.username, other: p2 && p2.username};
    if (lock || !p1 || !p2) return Object.assign(base, {cards: [], deck: [], globals: []});
    // In Solo you control both sides, so both are listed. Against a person, only the bot's own side.
    const mine = botMine(), mySide = mine === p2 ? "player2" : "player1";
    const sides_ = solo_ ? [[p1, "player1"], [p2, "player2"]] : [[mine, mySide]];
    const cards = sides_.flatMap(([p, side]) => ownCards(p, side)).map(c => Object.assign(describeCard(c), {options: menuFor(c.el)}));
    const deck = typeof showDeckMenu === "function" && list(p1.main_arr).length ? captureMenu(() => showDeckMenu()) : [];
    const targets = [];
    for (const [p, side] of [[p1, "player1"], [p2, "player2"]]) for (const z of ["m1","m2","m3","m4","m5"]) if (isCard(p[z])) targets.push(Object.assign(describeCard({el: p[z], zone: "monster", side})));
    // The decision record for whichever side's turn it is, for the play model.
    const tp = typeof turn_player !== "undefined" ? turn_player : null, turnSide = tp === p2 ? "player2" : "player1";
    if (!solo_ && tp !== mine) return Object.assign(base, {cards, deck, globals: [], monsters: targets, turnSide, myTurn: false, record: null});
    return Object.assign(base, {cards, deck, globals: [...GLOBAL_PLAYS], monsters: targets, turnSide, myTurn: true, record: buildRecord(tp === p2 ? p2 : p1, turnSide)});
  }
  function findCard(id){
    const p1 = G.p1(), p2 = G.p2();
    return ownCards(p1, "player1").concat(ownCards(p2, "player2")).find(c => String(c.el.data("id")) === String(id)) || null;
  }
  // ---------- Decision records, for training and running the play model ----------
  // The situation one side faced, every play it could make, and (when recording) which one it made.
  // Your own side carries card names and stats. The other side only carries what both players can see.
  const num = x => { const n = Number(x); return x === null || x === undefined || x === "" || n !== n ? null : n; };
  function cardRec(c, reveal){
    const el = c.el, fd = !!el.data("face_down");
    const pos = c.zone === "monster" ? (fd ? "FD" : el.data("inDEF") ? "DEF" : "ATK") : (fd ? "FD" : null);
    if (!reveal && (fd || c.zone === "hand")) return {zone: c.zone, pos: "FD"};
    const cf = el.data("cardfront"), get = k => cf && typeof cf.data === "function" ? cf.data(k) : null;
    return {name: get("name") || null, ctype: get("card_type") || null, zone: c.zone, pos,
            atk: num(el.data("new_atk") ?? get("atk")), def: num(el.data("new_def") ?? get("def")), level: num(get("level"))};
  }
  // LIGHT or DARK monsters in a graveyard, for Black Luster Soldier and Chaos Sorcerer.
  const gyAttr = (p, attr) => list(p.grave_arr).filter(el => { const cf = isCard(el) && el.data("cardfront"); return cf && typeof cf.data === "function" && String(cf.data("attribute") || "").toUpperCase() === attr; }).length;
  const turnStats = {};
  function statsFor(side){
    const t = G.turn(), k = side + "|" + t;
    return turnStats[k] || (turnStats[k] = {plays: 0, summons: 0, draws: 0, discards: 0, last: null, lastCard: null, history: []});
  }
  function buildRecord(me, side){
    const p1 = G.p1(), p2 = G.p2(), opp = me === p1 ? p2 : p1, oppSide = side === "player1" ? "player2" : "player1";
    const tp = typeof turn_player !== "undefined" ? turn_player : null;
    const mine = ownCards(me, side), theirs = ownCards(opp, oppSide);
    const zone = (cs, z) => cs.filter(c => c.zone === z);
    const st = cs => cs.filter(c => c.zone === "spell/trap" || c.zone === "field");
    const myTurn = tp === me, stats = statsFor(side);
    const rec = {v: 2, turn: G.turn(), phase: G.phase() || "", myTurn, playsThisTurn: stats.plays, summonsThisTurn: stats.summons,
      drawsThisTurn: stats.draws, discardsThisTurn: stats.discards, lastPlay: stats.last, lastCard: stats.lastCard, turnHistory: stats.history.slice(), solo: isSolo(),
      me: {lp: num(me.lifepoints), deck: list(me.main_arr).length, hand: zone(mine, "hand").map(c => cardRec(c, true)),
           mon: zone(mine, "monster").map(c => cardRec(c, true)), st: st(mine).map(c => cardRec(c, true)), gy: list(me.grave_arr).length,
           gyLight: gyAttr(me, "LIGHT"), gyDark: gyAttr(me, "DARK"), ban: list(me.banished_arr).length},
      opp: {lp: num(opp.lifepoints), deck: list(opp.main_arr).length, hand: list(opp.hand_arr).length,
            mon: zone(theirs, "monster").map(c => cardRec(c, false)), st: st(theirs).map(c => cardRec(c, false)), gy: list(opp.grave_arr).length, ban: list(opp.banished_arr).length},
      cands: []};
    const targets = zone(theirs, "monster");
    for (const c of mine){
      const info = cardRec(c, true), id = String(c.el.data("id"));
      for (const o of menuFor(c.el)){
        if (o === "Attack") for (const t of targets) rec.cands.push({key: `card|${id}|Attack|${t.el.data("id")}`, play: o, card: info, target: cardRec(t, false)});
        else rec.cands.push({key: `card|${id}|${o}`, play: o, card: info, target: null});
      }
    }
    if (me === p1 && typeof showDeckMenu === "function" && list(p1.main_arr).length)
      for (const o of captureMenu(() => showDeckMenu())) rec.cands.push({key: `deck|${o}`, play: o, card: {zone: "deck"}, target: null});
    if (myTurn) for (const g of GLOBAL_PLAYS) rec.cands.push({key: `global|${g}`, play: g, card: null, target: null});
    return rec;
  }
  // Called just before DuelingBook applies each of your plays, so the board is still as you saw it.
  // Always counts the play for this turn's totals; builds and sends the record only while recording.
  function recordDecision(d){
    const sd = sides(), p1 = G.p1(), p2 = G.p2();
    if (!sd || sd.spectating || !DUEL_LABELS.has(G.label()) || d.username !== sd.mine.username) return;
    // In Solo you play both sides: the play belongs to whichever side owns the card, or whose turn it is.
    let me = sd.mine, side = me === p1 ? "player1" : "player2";
    if (isSolo()){
      const id = d.attacking_id || d.id, owner = id && findCard(id);
      if (owner){ side = owner.side; me = side === "player1" ? p1 : p2; }
      else if (typeof turn_player !== "undefined" && turn_player){ me = turn_player; side = me === p1 ? "player1" : "player2"; }
    }
    const play = String(d.play), stats = statsFor(side);
    // The card's name is only kept for your own cards, which are the only ones you make plays with.
    const owned = d.id !== undefined && findCard(d.id), lastCard = owned ? front(owned.el).name : null;
    const count = () => {
      stats.plays++; if (play === "Normal Summon" || play === "Set monster") stats.summons++;
      if (play === "Draw card") stats.draws++;
      if (play === "To GY" && owned && owned.zone === "hand") stats.discards++;
      const h = `${play}:${lastCard || ""}`;
      if (!stats.history.includes(h)) stats.history.push(h);
      stats.last = play; stats.lastCard = lastCard;
    };
    if (!recording){ count(); return; }
    const rec = buildRecord(me, side), keys = rec.cands.map(c => c.key);
    let key = null;
    if (play === "Attack") key = `card|${d.attacking_id}|Attack|${d.attacked_id}`;
    else if (GLOBAL_PLAYS.has(play)) key = `global|${play}`;
    else if (d.id !== undefined && keys.includes(`card|${d.id}|${play}`)) key = `card|${d.id}|${play}`;
    else if (keys.includes(`deck|${play}`)) key = `deck|${play}`;
    const chosen = key === null ? -1 : keys.indexOf(key);
    count();
    if (chosen < 0){ post("decisionSkipped", play); return; }
    rec.chosen = chosen;
    post("decision", rec);
  }

  function execute(req){
    if (req.type === "moves") return {ok: true, moves: moves()};
    if (req.type === "botHost"){ bot.format = req.format; return botHost(req.format); }
    const lock = playLock();
    if (lock) return {ok: false, reason: lock};
    if (!isSolo() && !myTurnNow()) return {ok: false, reason: "It isn't the bot's turn."};
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
      if (!isSolo() && c.el.data("owner") !== botMine() && !ownCards(botMine(), "").some(x => x.el === c.el)) return {ok: false, reason: "The bot only plays its own cards."};
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
