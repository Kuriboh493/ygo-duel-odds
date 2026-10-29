"use strict";
// Auto-play for the panel. A strategy looks at the plays available and picks one; the executor in page-hook.js
// performs it through DuelingBook's own menus. Everything runs only in Solo Mode (the executor refuses otherwise).
//
// Writing a strategy: add an entry to STRATEGIES with decide(state), returning an action or null to wait.
//   state.moves   what page-hook.js reports: turn, turnPlayer, phase, me (player 1's name), other (player 2's),
//                 cards [{id, name, ctype, zone, side, faceDown, position, options:[menu items]}],
//                 deck [deck menu items], globals [phase and turn plays], monsters [cards on both fields]
//   state.memory  an object kept between calls while auto-play runs; cleared when it starts
// Actions:
//   {type:"card", card:<id>, play:<one of that card's options>}       e.g. "Normal Summon", "Set ST", "Activate"
//   {type:"card", card:<id>, play:"Attack", target:<monster id>}       attack a monster on the other side
//   {type:"deck", play:"Draw card"}                                     any item on the deck's menu
//   {type:"global", play:"Enter BP"}                                    Enter DP/SP/M1/BP/M2/EP, End turn
// Add why:"..." to any action and it shows in the log. Add remember:{...} to have those values merged into
// state.memory only once the play goes through, so a refused play is simply tried again next time.

const Autoplay = {
  async request(req){
    if (tabId === null) return {ok:false, reason:"Open DuelingBook first."};
    try { return (await api.tabs.sendMessage(tabId, {type:"exec", req})) || {ok:false, reason:"The DuelingBook page didn't answer. Reload it."}; }
    catch (e){ return {ok:false, reason:"Lost the DuelingBook tab. Reload it."}; }
  },
  async moves(){ const r = await this.request({type:"moves"}); return r.ok ? r.moves : null; },
  perform(action){ return this.request(action); },
};

const myTurn = m => m.turnPlayer === m.me;
const STRATEGIES = {
  none: {
    label: "Nothing (just watch)",
    desc: "Runs the loop but never makes a play. Use it to check auto-play can see the duel.",
    decide: () => null,
  },
  pass: {
    label: "Test: draw, then end the turn",
    desc: "On player 1's turns, draws one card and ends the turn. A quick check that plays go through.",
    decide({moves: m, memory}){
      if (!myTurn(m)) return null;
      if (memory.turn !== m.turn){ memory.turn = m.turn; memory.drew = false; memory.ended = false; }
      if (!memory.drew && m.deck.includes("Draw card")) return {type:"deck", play:"Draw card", why:"Start of turn", remember:{drew:true}};
      if (!memory.ended) return {type:"global", play:"End turn", why:"Test strategy ends every turn", remember:{ended:true}};
      return null;
    },
  },
};

// ---------- Loop ----------
let apRunning = false, apBusy = false, apTimer = 0, apMemory = {}, apLast = null;
const apSettings = {strategy:"none", delay:900};
const apLogLines = [];
function apLog(msg, cls){
  apLogLines.push({t:new Date().toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"}), msg, cls});
  if (apLogLines.length > 100) apLogLines.shift();
  $("ap-log").innerHTML = apLogLines.slice().reverse().map(l => `<li class="${l.cls || ""}"><span>${l.t.slice(-5)}</span><div>${esc(l.msg)}</div></li>`).join("");
}
function describeAction(a, m){
  if (a.type === "card"){
    const c = m && m.cards.find(x => x.id === String(a.card)), t = a.target && m && m.monsters.find(x => x.id === String(a.target));
    const nm = c ? (c.name || "a face-down card") : "a card";
    return a.play === "Attack" ? `Attack ${t ? t.name || "a face-down monster" : "a monster"} with ${nm}` : `${a.play}: ${nm}`;
  }
  return a.play;
}
const TOO_SOON = "Too soon after the last play.";
async function apPerform(action, m, quietRetry){
  const {why, remember, ...req} = action;
  const r = await Autoplay.perform(req);
  const what = describeAction(action, m) + (why ? ` (${why})` : "");
  if (r.ok){ apLog(what, "auto"); if (remember) Object.assign(apMemory, remember); }
  else if (!(quietRetry && r.reason === TOO_SOON)) apLog(`Couldn't ${what}: ${r.reason}`);
  return r;
}
async function apTick(){
  if (!apRunning || apBusy) return;
  apBusy = true;
  try {
    const m = await Autoplay.moves(); apLast = m; renderMoves(m);
    if (!m || !m.solo){ apStop("Stopped: auto-play only runs in a Solo Mode duel."); return; }
    const strat = STRATEGIES[apSettings.strategy] || STRATEGIES.none;
    let action = null;
    try { action = strat.decide({moves:m, memory:apMemory}); } catch (e){ apStop("Stopped: the strategy hit an error: " + (e.message || e)); return; }
    if (action) await apPerform(action, m, true);
  } finally {
    apBusy = false;
    if (apRunning) apTimer = setTimeout(apTick, apSettings.delay);
  }
}
function apStart(){
  if (!apLast || !apLast.solo) return toast("Open a Solo Mode duel on DuelingBook first.");
  apRunning = true; apMemory = {};
  $("ap-run").textContent = "Stop"; $("ap-run").classList.add("running");
  apLog(`Started: ${STRATEGIES[apSettings.strategy].label}.`);
  apTick();
}
function apStop(why){
  const was = apRunning;
  apRunning = false; clearTimeout(apTimer);
  $("ap-run").textContent = "Start"; $("ap-run").classList.remove("running");
  if (was) apLog(why || "Stopped.");
}

// ---------- Status and the list of plays ----------
function renderLock(m){
  const dot = $("ap-dot"), st = $("ap-status");
  if (tabId === null){ dot.className = "dot"; st.textContent = "Open DuelingBook to use auto-play."; return; }
  if (!m){ dot.className = "dot wait"; st.textContent = "Can't reach the DuelingBook page. Reload it."; return; }
  if (!m.solo){ dot.className = "dot wait"; st.textContent = "Locked. Start a Solo Mode duel on DuelingBook to use auto-play."; return; }
  dot.className = "dot on"; st.textContent = `Ready: Solo Mode duel, turn ${m.turn || "–"}${m.phase ? `, ${m.phase}` : ""}.`;
}
const ZONE_ORDER = ["hand","monster","spell/trap","field","graveyard","banished"];
function renderMoves(m){
  renderLock(m);
  const box = $("ap-moves");
  if (!m || !m.solo){ box.innerHTML = `<p class="empty">Open a Solo Mode duel to see plays here.</p>`; return; }
  const btn = (action, label) => `<button class="btn small" data-ap='${esc(JSON.stringify(action))}'>${esc(label)}</button>`;
  let h = `<div class="apgroup">Turn</div><div class="row">${m.deck.map(p => btn({type:"deck", play:p}, p)).join("")}${m.globals.map(p => btn({type:"global", play:p}, p)).join("")}</div>`;
  for (const side of ["player1","player2"]){
    const cards = m.cards.filter(c => c.side === side && c.options.length).sort((a,b) => ZONE_ORDER.indexOf(a.zone) - ZONE_ORDER.indexOf(b.zone));
    if (!cards.length) continue;
    h += `<div class="apgroup">${esc(side === "player1" ? m.me || "Player 1" : m.other || "Player 2")}</div>`;
    h += cards.map(c => {
      const opts = c.options.flatMap(o => o !== "Attack" ? [btn({type:"card", card:c.id, play:o}, o)]
        : m.monsters.filter(t => t.side !== c.side).map(t => btn({type:"card", card:c.id, play:"Attack", target:t.id}, `Attack ${t.name || "face-down"}`)));
      return `<div class="apcard"><div class="apcard-head"><b>${esc(c.name || "Face-down card")}</b><span>${esc(c.zone)}${c.position ? " · " + c.position : ""}</span></div><div class="row">${opts.join("")}</div></div>`;
    }).join("");
  }
  box.innerHTML = h;
}
document.addEventListener("click", async ev => {
  const b = ev.target.closest("[data-ap]"); if (!b) return;
  let action; try { action = JSON.parse(b.dataset.ap); } catch (e){ return; }
  b.disabled = true;
  await apPerform(action, apLast);
  setTimeout(apRefresh, 500);
});
async function apRefresh(){
  if ($("pane-auto").hidden || apRunning || apBusy) return;
  const m = await Autoplay.moves(); apLast = m; renderMoves(m);
}
setInterval(apRefresh, 2000);
document.querySelector(".tabs").addEventListener("click", ev => { if (ev.target.closest("[data-tab=auto]")) apRefresh(); });

// ---------- Controls ----------
$("ap-strategy").innerHTML = Object.entries(STRATEGIES).map(([k, s]) => `<option value="${k}">${esc(s.label)}</option>`).join("");
function apSyncControls(){
  $("ap-strategy").value = apSettings.strategy; $("ap-strategy-desc").textContent = STRATEGIES[apSettings.strategy].desc;
  $("ap-delay").value = apSettings.delay; $("ap-delay-out").textContent = (apSettings.delay / 1000).toFixed(1) + " s";
}
function apSave(){ api.storage.local.set({autoplay:apSettings}).catch(() => {}); }
$("ap-strategy").addEventListener("change", () => { apSettings.strategy = $("ap-strategy").value; apSyncControls(); apSave(); if (apRunning){ apStop("Stopped: strategy changed."); } });
$("ap-delay").addEventListener("input", () => { apSettings.delay = +$("ap-delay").value; apSyncControls(); });
$("ap-delay").addEventListener("change", apSave);
$("ap-run").addEventListener("click", () => apRunning ? apStop() : apStart());
api.storage.local.get(["autoplay"]).then(r => { if (r.autoplay) Object.assign(apSettings, r.autoplay); if (!STRATEGIES[apSettings.strategy]) apSettings.strategy = "none"; apSyncControls(); }).catch(() => apSyncControls());
