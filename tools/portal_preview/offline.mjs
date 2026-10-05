// Only an explicit, confirmed action may open the online portal. Nothing is sent
// from local files, and the destination is fixed rather than supplied by a file.
const portalURL = "https://fieldforge-portal.chris1986ryan.chatgpt.site";
const element = key => document.getElementById(key);
element("offlineOpenPortal").addEventListener("click", () => {
  if (!window.confirm("Open the online FieldForge portal?\n\nThis will contact our website in a new tab and requires an internet connection. Your local map images, GPX files and coordinates will not be sent.\n\nKeep this tab open to preserve unsaved work.")) {
    element("offlineConnectionStatus").textContent = "Cancelled. No online page was opened.";
    element("offlinePortalFallback").hidden = true; element("offlinePortalLink").removeAttribute("href"); return;
  }
  element("offlinePortalLink").href = portalURL;
  element("offlinePortalFallback").hidden = false;
  element("offlineConnectionStatus").textContent = "Portal opening requested. This local page remains open; no local files were sent.";
  window.open(portalURL, "_blank", "noopener,noreferrer");
});
