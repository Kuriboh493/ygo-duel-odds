"use strict";
// Report page. Gathers the panel's and the DuelingBook tab's diagnostics, lets the user describe the problem,
// and hands it off as a prefilled GitHub issue, the clipboard, or a downloaded file. Nothing is sent automatically.
const ISSUES = "https://github.com/Kuriboh493/ygo-duel-odds/issues/new";
const URL_MAX = 7500;   // GitHub rejects much longer prefilled issue links
const DB_ORIGINS = ["https://www.duelingbook.com/*","https://duelingbook.com/*"];
const $ = id => document.getElementById(id);
let raw = null;

function browserName(){
  const ua = navigator.userAgent;
  const m = (re) => (ua.match(re) || [])[1];
  if (navigator.brave) return `Brave ${m(/Chrome\/([\d.]+)/) || ""}`.trim();
  if (/Edg\//.test(ua)) return `Edge ${m(/Edg\/([\d.]+)/)}`;
  if (/OPR\//.test(ua)) return `Opera ${m(/OPR\/([\d.]+)/)}`;
  if (/Vivaldi\//.test(ua)) return `Vivaldi ${m(/Vivaldi\/([\d.]+)/)}`;
  if (/Firefox\//.test(ua)) return `Firefox ${m(/Firefox\/([\d.]+)/)}`;
  if (/Chrome\//.test(ua)) return `Chrome ${m(/Chrome\/([\d.]+)/)}`;
  if (/Safari\//.test(ua)) return `Safari ${m(/Version\/([\d.]+)/) || ""}`.trim();
  return ua;
}
function osName(){
  const ua = navigator.userAgent;
  if (/Windows NT/.test(ua)) return "Windows";
  if (/Mac OS X/.test(ua)) return "macOS";
  if (/CrOS/.test(ua)) return "ChromeOS";
  if (/Android/.test(ua)) return "Android";
  if (/Linux/.test(ua)) return "Linux";
  return "Unknown";
}

async function gather(){
  const out = {extension:"?", browser:browserName(), os:osName(), language:navigator.language, time:new Date().toISOString()};
  try { out.extension = api.runtime.getManifest().version; } catch (e){}
  try { out.access = api.permissions ? await api.permissions.contains({origins:DB_ORIGINS}) : "n/a"; } catch (e){ out.access = "unknown"; }
  try { const r = await api.storage.local.get(["panel-diag"]); out.panel = r["panel-diag"] || null; } catch (e){ out.panel = {error:String(e)}; }
  out.tab = null;
  try {
    let tabs;
    try { tabs = await api.tabs.query({url:DB_ORIGINS}); }
    catch (e){ tabs = (await api.tabs.query({})).filter(t => /^https:\/\/(www\.)?duelingbook\.com\//.test(t.url || "")); }
    tabs.sort((a,b) => (b.active - a.active) || (b.lastAccessed||0) - (a.lastAccessed||0));
    out.duelingbookTabs = tabs.length;
    for (const t of tabs){
      try { const d = await api.tabs.sendMessage(t.id, {type:"diag"}); if (d){ out.tab = d; break; } } catch (e){ out.tabError = String(e.message || e); }
    }
  } catch (e){ out.tabError = String(e.message || e); }
  return out;
}

// Player names are swapped for roles, everywhere they appear, unless the user opts in.
function prepared(){
  if (!raw) return null;
  const d = JSON.parse(JSON.stringify(raw));
  if (!$("withlog").checked && d.tab){ delete d.tab.recentEvents; if (d.tab.tracker) delete d.tab.tracker.log; }
  let text = JSON.stringify(d, null, 1);
  if ($("hide").checked){
    const snap = raw.tab && raw.tab.snapshot || {};
    for (const [name, role] of [[snap.opp, "Opponent"], [snap.me, "Me"]]){
      if (!name || name.length < 3) continue;
      text = text.split(name).join(role);
    }
  }
  return text;
}

function facts(){
  const d = raw, rows = [];
  const tag = (cls, txt) => `<span class="${cls}">${txt}</span>`;
  rows.push(["Extension", d.extension]);
  rows.push(["Browser", `${d.browser} on ${d.os}`]);
  rows.push(["DuelingBook access", d.access === false ? tag("bad", "Not allowed. Allow it from the panel.") : d.access === true ? tag("ok", "Allowed") : String(d.access)]);
  if (!d.duelingbookTabs) rows.push(["DuelingBook tab", tag("warn", "None open. Open the duel the problem happened in, then press Collect again.")]);
  else if (!d.tab) rows.push(["DuelingBook tab", tag("bad", "Open, but the extension isn't running in it. Reload the tab.")]);
  else {
    const t = d.tab;
    rows.push(["Duel events", t.hooked ? tag("ok", `${t.events} received`) : tag("bad", "Not coming through")]);
    rows.push(["Board reads", t.snapshot && t.snapshot.ok === false ? tag("warn", t.snapshot.error ? "Failing" : "No duel open") : tag("ok", `${t.snapshots} received`)]);
    rows.push(["DuelingBook client", t.client || "unknown"]);
    rows.push(["Errors", t.errors.length || (d.panel && d.panel.errors.length) ? tag("warn", `${t.errors.length} in the tab, ${d.panel ? d.panel.errors.length : 0} in the panel`) : tag("ok", "None")]);
  }
  if (d.panel && d.panel.model) rows.push(["Model", `${d.panel.format}, ${d.panel.mode === "list" ? "pasted list" : d.panel.learned ? "learned archetypes" : "sketches"}, ${d.panel.model.simMs} ms per update`]);
  $("facts").innerHTML = rows.map(([k,v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

function refresh(){ const t = prepared(); $("diag").textContent = t || ""; }

function body(diagText, note){
  const what = $("what").value.trim(), exp = $("expected").value.trim();
  return [
    "**What happened**", what || "_(not filled in)_", "",
    ...(exp ? ["**What I expected**", exp, ""] : []),
    `**When:** ${$("when").value}`,
    `**Browser:** ${raw.browser} on ${raw.os}`,
    `**Extension:** ${raw.extension}`, "",
    ...(note ? [note, ""] : []),
    "<details><summary>Diagnostics</summary>", "", "```json", diagText, "```", "</details>",
  ].join("\n");
}
function title(){ return $("title").value.trim() || ($("what").value.trim().split("\n")[0] || "Problem report").slice(0, 90); }
function needWhat(){
  if ($("what").value.trim()) { $("f-what").classList.remove("err-field"); return true; }
  $("f-what").classList.add("err-field"); $("what").focus();
  status("Describe what went wrong first.", "bad");
  return false;
}
function status(msg, cls){ $("status").className = cls || ""; $("status").textContent = msg; }

async function copyText(text){
  try { await navigator.clipboard.writeText(text); return true; }
  catch (e){
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy"); ta.remove(); return ok;
  }
}

$("b-issue").addEventListener("click", async () => {
  if (!needWhat()) return;
  const full = prepared();
  let url = `${ISSUES}?title=${encodeURIComponent(title())}&body=${encodeURIComponent(body(full))}`;
  if (url.length <= URL_MAX){
    window.open(url, "_blank", "noopener");
    return status("Opened the issue form in a new tab. Review it and press Submit.", "ok");
  }
  // Too long for a link: send a short version and put the full diagnostics on the clipboard to paste in.
  // The tab opens before anything is awaited, or the browser may block it as a pop-up.
  const short = JSON.parse(full);
  if (short.tab){ delete short.tab.recentEvents; if (short.tab.tracker) delete short.tab.tracker.log; }
  const copying = copyText(full);
  const note = "_The full diagnostics were too long for the link. If they're on my clipboard, I'll paste them below._";
  window.open(`${ISSUES}?title=${encodeURIComponent(title())}&body=${encodeURIComponent(body(JSON.stringify(short, null, 1).slice(0, 4000), note))}`, "_blank", "noopener");
  status(await copying ? "Opened the issue form. The full diagnostics are on your clipboard: paste them at the end before submitting." : "Opened the issue form with shortened diagnostics. Use Download report to keep the full version.", "ok");
});
$("b-copy").addEventListener("click", async () => {
  if (!needWhat()) return;
  const ok = await copyText(`# ${title()}\n\n` + body(prepared()));
  status(ok ? "Report copied. Paste it into a message to the developer." : "Couldn't copy. Use Download report instead.", ok ? "ok" : "bad");
});
$("b-save").addEventListener("click", () => {
  if (!needWhat()) return;
  const blob = new Blob([JSON.stringify({title:title(), what:$("what").value, expected:$("expected").value, when:$("when").value, diagnostics:JSON.parse(prepared())}, null, 1)], {type:"application/json"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = `ygo-duel-odds-report-${new Date().toISOString().slice(0,19).replace(/[:T]/g, "-")}.json`;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  status("Report downloaded.", "ok");
});
for (const id of ["hide","withlog"]) $(id).addEventListener("change", refresh);
$("b-refresh").addEventListener("click", () => { status(""); load().then(() => status("Collected again.", "ok")); });
$("what").addEventListener("input", () => $("f-what").classList.remove("err-field"));

async function load(){
  raw = await gather();
  facts(); refresh();
}
load().catch(e => { status("Couldn't collect diagnostics: " + (e.message || e), "bad"); });
