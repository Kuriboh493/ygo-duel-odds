// Opens the panel from the toolbar button, using whatever the browser offers:
// Chromium side panel (Chrome, Edge, Brave), Firefox sidebar, or a small window (or tab) everywhere else, like Safari.
// Also shows "OFF" on the toolbar icon while tracking is switched off.
const api = globalThis.browser || globalThis.chrome;

if (api.sidePanel && api.sidePanel.setPanelBehavior){
  api.sidePanel.setPanelBehavior({openPanelOnActionClick:true}).catch(() => {});
}
api.action.onClicked.addListener(() => {
  if (api.sidebarAction && api.sidebarAction.toggle) return api.sidebarAction.toggle();
  if (api.sidePanel && api.sidePanel.setPanelBehavior) return;
  const url = api.runtime.getURL("panel.html");
  // Safari and some others may not open pop-up windows for extensions; a tab always works.
  Promise.resolve().then(() => api.windows.create({url, type:"popup", width:460, height:900})).catch(() => api.tabs.create({url}));
});

function badge(settings){
  const off = settings && settings.enabled === false;
  api.action.setBadgeText({text: off ? "OFF" : ""}).catch(() => {});
  if (off) api.action.setBadgeBackgroundColor({color:"#596476"}).catch(() => {});
}
api.storage.local.get(["settings"]).then(r => badge(r.settings)).catch(() => {});
api.storage.onChanged.addListener((ch, area) => { if (area === "local" && ch.settings) badge(ch.settings.newValue); });
