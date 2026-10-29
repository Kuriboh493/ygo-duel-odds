"use strict";
// Turns one recorded decision point into features for the play model, one list per candidate play.
// tools/train_policy.py has a line-for-line Python copy of this (featurize); tools/test_features.py checks
// the two agree. Change both together, and bump FEATURES_VERSION so old models aren't used with new features.
//
// A record (built by page-hook.js) looks like:
//   {phase, myTurn, turn, playsThisTurn, summonsThisTurn, drawsThisTurn, discardsThisTurn, lastPlay, lastCard (your previous play this turn),
//    turnHistory:["play:card", ...] (every distinct play you've made earlier this turn),
//    me:  {lp, deck, hand:[card], mon:[card], st:[card], gy, gyLight, gyDark, ban},
//    opp: {lp, deck, hand:<count>, mon:[card], st:[card], gy, ban},
//    cands:[{key, play, card:{name, ctype, zone, pos, atk, def, level}, target:{...} or null}], chosen:<index>}
// Opponent cards only carry names and stats when they're face-up; face-down ones have pos "FD" and nothing else.
const FEATURES_VERSION = 4;

function fBucket(x, edges){
  if (x === null || x === undefined || x !== x) return "na";
  let b = 0;
  for (let i = 0; i < edges.length; i++) if (x >= edges[i]) b = i;
  return String(edges[b]);
}
function fNum(x){ const n = Number(x); return x === null || x === undefined || x === "" || n !== n ? null : n; }
// What a battle with this target would look like for the attacker: win, tie, lose, or unknown (face-down).
function fBattle(card, target){
  if (!target) return "none";
  if (target.pos === "FD") return "unknown";
  const a = fNum(card && card.atk), d = fNum(target.pos === "DEF" ? target.def : target.atk);
  if (a === null || d === null) return "unknown";
  return a > d ? "win" : a === d ? "tie" : "lose";
}
function fLevel(card){
  const l = fNum(card && card.level);
  if (l === null || l === 0) return "na";
  return l <= 4 ? "low" : l <= 6 ? "mid" : "high";
}
function featurize(rec, cand){
  const p = "p:" + cand.play, c = cand.card || {}, me = rec.me || {}, opp = rec.opp || {};
  const out = [
    p,
    p + "|z:" + (c.zone || "none"),
    p + "|ct:" + (c.ctype || "none"),
    p + "|ph:" + (rec.phase || "none"),
    p + "|my:" + (rec.myTurn ? 1 : 0),
    p + "|ns:" + Math.min(fNum(rec.summonsThisTurn) || 0, 2),
    p + "|k:" + fBucket(fNum(rec.playsThisTurn) || 0, [0, 1, 3, 6, 10]),
    p + "|h:" + fBucket((me.hand || []).length, [0, 1, 3, 5, 7]),
    p + "|mm:" + Math.min((me.mon || []).length, 3),
    p + "|om:" + Math.min((opp.mon || []).length, 3),
    p + "|ost:" + Math.min((opp.st || []).length, 3),
    p + "|oh:" + fBucket(fNum(opp.hand) || 0, [0, 1, 3, 5]),
    p + "|olp:" + fBucket(fNum(opp.lp), [0, 1000, 2000, 4000, 8000]),
    p + "|mlp:" + fBucket(fNum(me.lp), [0, 1000, 2000, 4000, 8000]),
    p + "|lv:" + fLevel(c),
  ];
  // What you just did, so it can learn sequences: two draws after Pot of Greed, discards after Graceful Charity.
  const last = rec.lastPlay || "none";
  out.push(p + "|last:" + last);
  if (rec.lastCard) out.push(p + "|last:" + last + "|ln:" + rec.lastCard);
  out.push(p + "|dr:" + Math.min(fNum(rec.drawsThisTurn) || 0, 5));
  out.push(p + "|dc:" + Math.min(fNum(rec.discardsThisTurn) || 0, 3));
  // Everything done earlier this turn, so it can finish what an effect started (Graceful Charity's discards, say).
  for (const h of rec.turnHistory || []) out.push(p + "|did:" + h);
  // More or fewer set cards than them, for cards like Heavy Storm.
  const myst = (me.st || []).filter(x => x && x.pos === "FD").length, ostn = (opp.st || []).length;
  out.push(p + "|stc:" + (ostn > myst ? "more" : ostn === myst ? "same" : "fewer"));
  // A monster against their strongest face-up monster.
  if (c.ctype === "Monster"){
    const ups = (opp.mon || []).filter(x => x && x.pos !== "FD").map(x => fNum(x.atk)).filter(x => x !== null);
    const a = fNum(c.atk);
    out.push(p + "|vs:" + (a === null ? "na" : !ups.length ? "empty" : a > Math.max(...ups) ? "win" : "lose"));
  }
  const ofd = Math.min((opp.mon || []).filter(x => x && x.pos === "FD").length, 2);
  const gyld = ((fNum(me.gyLight) || 0) > 0 ? "L" : "-") + ((fNum(me.gyDark) || 0) > 0 ? "D" : "-");
  out.push(p + "|ofd:" + ofd);
  if (c.name){
    // The card itself against the board, so it can learn when each card is worth playing:
    // Nobleman of Crossout into a face-down monster, Black Luster Soldier once the graveyard has LIGHT and DARK.
    const n = p + "|n:" + c.name;
    out.push(n);
    out.push(n + "|ph:" + (rec.phase || "none"));
    out.push(n + "|om:" + Math.min((opp.mon || []).length, 3));
    out.push(n + "|ofd:" + ofd);
    out.push(n + "|ost:" + Math.min((opp.st || []).length, 3));
    out.push(n + "|oh:" + fBucket(fNum(opp.hand) || 0, [0, 1, 3, 5]));
    out.push(n + "|gy:" + gyld);
  }
  if (cand.target){
    const b = fBattle(c, cand.target);
    out.push(p + "|bt:" + b);
    out.push(p + "|bt:" + b + "|ost:" + Math.min((opp.st || []).length, 3));
    if (cand.target.name) out.push(p + "|tn:" + cand.target.name);
  }
  return out;
}
// Scores every candidate with a trained model ({weights:{feature: weight}}) and returns them best first.
// known counts the candidate's features the model has a weight for; 0 means it never saw a play like it.
function scoreCandidates(model, rec){
  const w = model.weights || {};
  return rec.cands.map((cand, i) => {
    let s = 0, known = 0;
    for (const f of featurize(rec, cand)) if (f in w){ s += w[f]; known++; }
    return {i, cand, score: s, known};
  }).sort((a, b) => b.score - a.score);
}
