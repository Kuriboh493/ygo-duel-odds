// Opens the panel from the toolbar button, using whatever the browser offers:
// Chromium side panel (Chrome, Edge, Brave), Firefox sidebar, or a small window everywhere else.
const api = globalThis.browser || globalThis.chrome;

if (api.sidePanel && api.sidePanel.setPanelBehavior){
  api.sidePanel.setPanelBehavior({openPanelOnActionClick:true}).catch(() => {});
}
api.action.onClicked.addListener(() => {
  if (api.sidebarAction && api.sidebarAction.toggle) return api.sidebarAction.toggle();
  if (api.sidePanel && api.sidePanel.setPanelBehavior) return;
  api.windows.create({url:api.runtime.getURL("panel.html"), type:"popup", width:460, height:900});
});
