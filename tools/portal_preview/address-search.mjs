import {createAddressService} from "./address-service.mjs";
import {placeCoordinateText} from "./places-core.mjs";

export function createAddressSearch({document:doc = document, window:win = window, navigator:nav = navigator, service = createAddressService(), onAdd, onShow} = {}) {
  const id = key => doc.getElementById(key);
  const node = (tag, text, className) => { const item = doc.createElement(tag); if (text !== undefined) item.textContent = text; if (className) item.className = className; return item; };
  let connected = false, busy = false, generation = 0, records = [];
  const announce = (text, error = false) => { id("addressStatus").textContent = text; id("addressStatus").classList.toggle("error", error); };
  function controls() {
    id("addressQuery").disabled = !connected; id("addressScope").disabled = !connected;
    id("addressSubmit").disabled = !connected || busy; id("addressCancel").disabled = !busy;
    id("addressEnable").disabled = connected || nav.onLine === false; id("addressPause").disabled = !connected;
    id("addressConnectionState").textContent = nav.onLine === false ? "Device offline" : connected ? "Connected · searches on request" : "Disconnected";
    id("addressSearchForm").setAttribute("aria-busy", String(busy));
  }
  function cancel(message) { generation++; busy = false; service.cancel(); controls(); if (message) announce(message); }
  function synchronize() {
    const wasConnected = connected;
    connected = doc.documentElement.dataset.sourcesEnabled === "true" && nav.onLine !== false;
    service.setConnected(connected);
    if (!connected) { cancel(); if (wasConnected || nav.onLine === false) announce("Search disconnected. Previously returned coordinates can still be added to Saved places."); }
    else if (!wasConnected) announce("Connected. Enter an address and choose Find coordinates; typing does not contact the provider.");
    controls();
  }
  function render(value) {
    records = value.results;
    const fragment = doc.createDocumentFragment();
    for (const result of records) {
      const row = node("article", undefined, "address-result"), details = node("div");
      details.append(node("h3", result.label));
      const coordinates = node("div", undefined, "address-coordinates");
      coordinates.append(node("span", `Latitude ${placeCoordinateText(result.point.lat)}`), node("span", `Longitude ${placeCoordinateText(result.point.lon)}`));
      details.append(coordinates, node("p", `Source type: ${result.matchType} · ${result.osmIdentity} · Retrieved ${result.retrievedAt}`, "address-note"));
      const button = node("button", "Add to Saved places"); button.type = "button"; button.setAttribute("aria-label", `Add ${result.point.name} to Saved places`);
      button.addEventListener("click", () => {
        if (!records.includes(result)) return;
        try { announce(onAdd({...result.point})); }
        catch (error) { announce(error.message || "This result could not be added.", true); }
      });
      row.append(details, button); fragment.append(row);
    }
    id("addressResults").replaceChildren(fragment);
    const scope = value.scope === "US" ? "United States" : "Worldwide";
    announce(records.length ? `${records.length} ${records.length === 1 ? "match" : "matches"} for “${value.query}” · ${scope}${value.cached ? " · Reused from this tab’s recent search" : ""}. Check the address before adding a place.` : `No matches for “${value.query}” · ${scope}. Try the street, city and country, or change the search area.`);
  }
  id("addressSearchForm").addEventListener("submit", async event => {
    event.preventDefault();
    if (!connected || nav.onLine === false) { synchronize(); announce("Connect before submitting an address search.", true); return; }
    if (busy) return;
    const token = ++generation; busy = true; records = []; id("addressResults").replaceChildren(); controls(); announce("Searching Photon for your submitted address…");
    try {
      const value = await service.search(id("addressQuery").value, id("addressScope").value);
      if (token !== generation || !connected) return;
      render(value);
    } catch (error) { if (token === generation) announce(error.name === "AbortError" ? "Address search cancelled." : error.message, error.name !== "AbortError"); }
    finally { if (token === generation) { busy = false; controls(); } }
  });
  id("addressEnable").addEventListener("click", () => id("connect").click());
  id("addressPause").addEventListener("click", () => id("disconnect").click());
  id("addressCancel").addEventListener("click", () => cancel("Address search cancelled. No new coordinates were added."));
  id("addressClear").addEventListener("click", () => { cancel(); service.clear(); records = []; id("addressResults").replaceChildren(); id("addressQuery").value = ""; announce("Search text, results and recent-query memory cleared. Saved places are unchanged."); });
  for (const [key, event] of [["addressQuery", "input"], ["addressScope", "change"]]) id(key).addEventListener(event, () => { cancel(); records = []; id("addressResults").replaceChildren(); announce("Search changed. Choose Find coordinates when ready."); });
  doc.addEventListener("fieldforgeconnectionchange", synchronize);
  win.addEventListener("offline", synchronize); win.addEventListener("online", synchronize);
  win.addEventListener("pagehide", () => { connected = false; cancel(); service.setConnected(false); service.clear(); });
  for (const key of ["openAddressSearch", "openAddressControls"]) id(key)?.addEventListener("click", () => { onShow(); id("addressTab").focus(); });
  synchronize();
  return {synchronize};
}
