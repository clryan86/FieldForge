import {MAX_GPX_BYTES, PLAN_KIND, downloadEstimate, validatePlan, parseGPX, projectTrace, waypointCSV} from "./desk-core.mjs";
import {createMBViewer} from "./mbtiles-viewer.mjs";
import {createVectorViewer} from "./vector-viewer.mjs";
import {createPlaces} from "./places.mjs";
import {GPX_SOURCE, IMAGE_SOURCE} from "./places-core.mjs";
import {createImageViewer} from "./image-viewer.mjs";
import {createRouteExplorer} from "./route-explorer.mjs";

const id = key => document.getElementById(key);
const node = (tag, text, className) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; if (className) element.className = className; return element; };
const offlineEdition = document.documentElement.dataset.edition === "offline";
const STORAGE_KEY = "fieldforge-source-plan-v1";
const regions = [...document.querySelectorAll("#usSourceLinks li")].map(row => {
  const link = row.querySelector("a"), size = row.textContent.match(/~([\d.]+)\s*(GB|MB)/);
  const url = new URL(link.dataset.sourceUrl || link.href), key = url.pathname.split("/").pop().replace(/-latest\.osm\.pbf$/, "");
  if (url.origin !== "https://download.geofabrik.de" || !size || !/^[a-z-]+$/.test(key)) throw new Error("Invalid source directory entry.");
  return {id:key, name:link.textContent.trim(), url:url.href, bytes:Number(size[1]) * (size[2] === "GB" ? 1e9 : 1e6)};
});
const regionIds = new Set(regions.map(region => region.id));
let selection = new Set(), trace = null, readGeneration = 0, planGeneration = 0;
function formatSize(bytes) { return bytes >= 1e9 ? (bytes / 1e9).toLocaleString(undefined, {maximumFractionDigits:2}) + " GB" : (bytes / 1e6).toLocaleString(undefined, {maximumFractionDigits:1}) + " MB"; }
function formatTime(seconds) { if (!seconds) return "—"; const minutes = Math.max(1, Math.ceil(seconds / 60)); return minutes < 60 ? `~${minutes} min` : `~${Math.floor(minutes / 60)} h ${minutes % 60} min`; }
function plan() { return validatePlan({kind:PLAN_KIND, schema_version:1, region_ids:[...selection].sort(), budget_gb:Number(id("deskBudget").value), speed_mbps:Number(id("deskSpeed").value)}, regionIds); }
function announcePlan(text) { id("deskPlanStatus").textContent = text; }
function storePlan() {
  if (offlineEdition || !id("deskRemember").checked) return;
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(plan())); }
  catch (error) { announcePlan("Could not save this plan on your device. Check the values and use Save source plan to keep a file."); }
}
function updateBrief(persist = true) {
  const selected = regions.filter(region => selection.has(region.id)), bytes = selected.reduce((sum, region) => sum + region.bytes, 0);
  id("deskTotal").textContent = formatSize(bytes);
  id("deskTotalCaption").textContent = selected.length ? `${selected.length} source ${selected.length === 1 ? "region" : "regions"} · estimated size` : "No regions selected";
  id("deskClear").disabled = !selection.size;
  const status = id("deskBudgetStatus");
  try {
    const data = plan(), estimate = downloadEstimate(bytes, data.budget_gb, data.speed_mbps);
    id("deskMeter").max = data.budget_gb; id("deskMeter").value = Math.min(bytes / 1e9, data.budget_gb);
    id("deskRemaining").textContent = (estimate.overBudget ? "−" : "") + formatSize(Math.abs(estimate.remainingBytes));
    id("deskTime").textContent = formatTime(estimate.seconds);
    status.textContent = !selected.length ? "Select regions to calculate your plan." : estimate.overBudget ? "Above your download budget. Reduce your selection or increase the budget." : "Within your download budget. Check your free disk space before downloading.";
    status.classList.toggle("over", estimate.overBudget);
    id("deskSave").disabled = !selected.length;
    if (persist) storePlan();
  } catch (error) {
    id("deskRemaining").textContent = "—"; id("deskTime").textContent = "—"; id("deskSave").disabled = true;
    status.textContent = error.message; status.classList.add("over"); id("deskMeter").value = 0;
  }
}
function renderRegions() {
  const query = id("deskRegionSearch").value.trim().toLocaleLowerCase();
  const shown = regions.filter(region => region.name.toLocaleLowerCase().includes(query) && (!id("deskSelectedOnly").checked || selection.has(region.id)));
  id("deskRegionCount").textContent = `${shown.length} of ${regions.length}`;
  const container = id("deskRegions"), fragment = document.createDocumentFragment();
  for (const region of shown) {
    const row = node("div", undefined, "region-row"), label = node("label"), check = node("input"), name = node("span", region.name, "region-name");
    check.type = "checkbox"; check.checked = selection.has(region.id); check.value = region.id; check.setAttribute("aria-label", "Include " + region.name + " in your source plan");
    check.addEventListener("change", () => {
      if (check.checked) selection.add(region.id); else selection.delete(region.id);
      if (id("deskSelectedOnly").checked) renderRegions();
      updateBrief();
    });
    name.append(node("small", "~" + formatSize(region.bytes) + " · PBF source")); label.append(check, name);
    const link = node("a", offlineEdition ? "Use portal" : "Source file", "region-source");
    if (offlineEdition) { link.href = "#offlineConnection"; }
    else { link.href = region.url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.dataset.sourceLink = ""; }
    const paused = !offlineEdition && document.documentElement.dataset.sourcesEnabled !== "true";
    link.setAttribute("aria-disabled", String(paused)); link.classList.toggle("source-disabled", paused);
    link.setAttribute("aria-label", offlineEdition ? "Go to the online portal controls to download " + region.name : "Open " + region.name + " source download at Geofabrik");
    row.append(label, link); fragment.append(row);
  }
  if (!shown.length) fragment.append(node("p", "No regions match. Change your search or turn off Show selected only.", "desk-fine"));
  container.replaceChildren(fragment);
}
function download(text, mime, filename) {
  const url = URL.createObjectURL(new Blob([text], {type:mime})), link = node("a");
  link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
const savedPlaces = createPlaces({download});
createMBViewer({onAddPoint:point => { id("mbStatus").textContent = savedPlaces.add([point],"MBTiles pixel"); selectTool("places"); }});
createVectorViewer({download, onAddPoint:point => { id("vectorStatus").textContent = savedPlaces.add([point],"GeoJSON vertex"); selectTool("places"); }});
function collectPlaces(points, source, label, statusId) {
  try {
    const entries = points.map((point,index) => ({name:point.name || `Waypoint ${index+1}`,lat:point.lat,lon:point.lon,source}));
    id(statusId).textContent = savedPlaces.add(entries,label); selectTool("places");
  } catch (error) { id(statusId).textContent = error.message; }
}
const routeExplorer = createRouteExplorer({onAddPoint:point => collectPlaces([point],GPX_SOURCE,"GPX point","deskTraceStatus"), onExportPoint:point => {
  download(waypointCSV([point]), "text/csv;charset=utf-8", "fieldforge-selected-place.csv");
  id("deskTraceStatus").textContent = "Selected point CSV saved. Import it into FieldForge’s local place catalog. The coordinate comes from your file and has not been independently verified.";
}});
const imageViewer = createImageViewer({download, onAddPoint:point => collectPlaces([point],IMAGE_SOURCE,"Image point","imageStatus"), onExportPoint:point => {
  download(waypointCSV([point], "User-supplied image bounds and projection; pixel center; exported by FieldForge preparation desk; WGS 84; not independently verified"), "text/csv;charset=utf-8", "fieldforge-image-point.csv");
}});
function applyPlan(data) {
  const checked = validatePlan(data, regionIds); // Atomic: reject first, then change UI.
  selection = new Set(checked.region_ids); id("deskBudget").value = checked.budget_gb; id("deskSpeed").value = checked.speed_mbps;
  renderRegions(); updateBrief();
}
id("deskRegionSearch").addEventListener("input", renderRegions);
id("deskSelectedOnly").addEventListener("change", renderRegions);
for (const key of ["deskBudget", "deskSpeed"]) id(key).addEventListener("input", () => updateBrief());
id("deskClear").addEventListener("click", () => { planGeneration++; selection.clear(); renderRegions(); updateBrief(); announcePlan("Selection cleared. Downloaded files are unchanged."); });
id("deskSave").addEventListener("click", () => {
  try { const data = plan(); download(JSON.stringify(data, null, 2), "application/json", "fieldforge-source-plan.json"); announcePlan("Source plan saved. Open it here to restore your selection. It contains region IDs and estimates, not map files or desktop install instructions."); }
  catch (error) { announcePlan(error.message); }
});
id("deskOpen").addEventListener("click", () => id("deskPlanFile").click());
id("deskPlanFile").addEventListener("change", async () => {
  const file = id("deskPlanFile").files[0], generation = ++planGeneration;
  if (!file) return;
  try {
    if (file.size > 100 * 1024) throw new Error("The plan is too large. Choose a source plan under 100 KiB.");
    const text = await file.text(); if (generation !== planGeneration) return;
    let data; try { data = JSON.parse(text); } catch { throw new Error("The plan file is not valid JSON."); }
    applyPlan(data); announcePlan("Source plan restored. No maps have been downloaded.");
  } catch (error) { if (generation === planGeneration) announcePlan(error.message + " Your existing selection was kept."); }
  finally { if (generation === planGeneration) id("deskPlanFile").value = ""; }
});
id("deskRemember").addEventListener("change", () => {
  if (offlineEdition) return;
  if (id("deskRemember").checked) { storePlan(); }
  else { try { localStorage.removeItem(STORAGE_KEY); announcePlan("Saved device preference removed. This tab still holds your selection."); } catch { announcePlan("Could not remove the saved plan. Clear this website’s browser storage to remove it."); } }
});
if (!offlineEdition) try {
  const remembered = localStorage.getItem(STORAGE_KEY);
  if (remembered) { const checked = validatePlan(JSON.parse(remembered), regionIds); id("deskRemember").checked = true; applyPlan(checked); announcePlan("Restored the source plan you chose to remember on this device. Route files are never stored."); }
} catch { announcePlan("A saved device plan could not be restored. Open a saved plan file or start a new selection."); }

function selectTool(kind) {
  for (const [tool, tab, panel] of [["packs", "packTab", "packPanel"], ["trace", "traceTab", "tracePanel"], ["image", "imageTab", "imagePanel"], ["places", "placesTab", "placesPanel"], ["vector", "vectorTab", "vectorPanel"], ["mbtiles", "mbTab", "mbPanel"]]) {
    id(panel).hidden = kind !== tool; id(tab).setAttribute("aria-pressed", String(kind === tool));
  }
  if (kind === "image") imageViewer.refresh();
}
id("packTab").addEventListener("click", () => selectTool("packs"));
id("traceTab").addEventListener("click", () => selectTool("trace"));
id("imageTab").addEventListener("click", () => selectTool("image"));
id("mbTab").addEventListener("click", () => selectTool("mbtiles"));
id("vectorTab").addEventListener("click", () => selectTool("vector"));
id("placesTab").addEventListener("click", () => selectTool("places"));
const svgNS = "http://www.w3.org/2000/svg";
function svg(tag, attrs) { const element = document.createElementNS(svgNS, tag); for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value); return element; }
function clearTrace(message = "File cleared from this page. Nothing was uploaded or saved.") {
  routeExplorer.clear();
  readGeneration++; trace = null; id("deskGpx").value = ""; id("deskTraceDrawing").replaceChildren(); id("deskTraceEmpty").hidden = false;
  id("deskTraceEmpty").removeAttribute("display"); id("deskSvgDesc").textContent = "Load a file to inspect its points. No basemap or directions.";
  id("deskFileName").textContent = "Coordinate trace";
  for (const key of ["deskDistance", "deskPointCount", "deskSegments", "deskWaypoints"]) id(key).textContent = "—";
  id("deskPlaces").replaceChildren(); id("deskPlacesPanel").hidden = true;
  id("deskClearTrace").disabled = true; id("deskExportPlaces").disabled = true; id("deskCollectWaypoints").disabled = true;
  id("deskTraceStatus").textContent = message; id("deskTraceStatus").classList.remove("error");
}
function renderTrace(data, filename) {
  const drawing = id("deskTraceDrawing"), projected = projectTrace(data), fragment = document.createDocumentFragment();
  for (const part of projected.parts) {
    if (part.length > 1) fragment.append(svg("polyline", {points:part.map(point => point.map(value => value.toFixed(2)).join(",")).join(" "), fill:"none", stroke:"#cdf091", "stroke-width":3, "stroke-linejoin":"round", "stroke-linecap":"round"}));
    else if (part.length) fragment.append(svg("circle", {cx:part[0][0], cy:part[0][1], r:4, fill:"#cdf091"}));
  }
  for (const [index, point] of projected.places.entries()) {
    const marker = svg("circle", {cx:point[0], cy:point[1], r:5, fill:"#f1bf7a", stroke:"#0e2921", "stroke-width":1.5});
    const title = svg("title", {}); title.textContent = data.waypoints[index].name || `Waypoint ${index + 1}`; marker.append(title); fragment.append(marker);
  }
  drawing.replaceChildren(fragment); id("deskTraceEmpty").setAttribute("display", "none");
  id("deskFileName").textContent = filename; id("deskDistance").textContent = data.geometryPoints ? (data.meters / 1000).toLocaleString(undefined, {maximumFractionDigits:2}) + " km" : "No track";
  id("deskPointCount").textContent = data.geometryPoints.toLocaleString(); id("deskSegments").textContent = data.segments.length.toLocaleString(); id("deskWaypoints").textContent = data.waypoints.length.toLocaleString();
  id("deskSvgDesc").textContent = `GPX coordinate plot with ${data.segments.length} separate segments and ${data.waypoints.length} waypoints. No basemap or directions.`;
  const rows = document.createDocumentFragment();
  for (const [index, p] of data.waypoints.slice(0, 100).entries()) {
    const row = node("tr"), cell = node("td"), button = node("button", p.name || `Waypoint ${index + 1}`, "waypoint-select");
    button.type = "button"; button.addEventListener("click", () => { routeExplorer.selectWaypoint(index); id("deskExplorePanel").scrollIntoView({block:"nearest"}); });
    cell.append(button); row.append(cell, node("td", p.lat.toFixed(7)), node("td", p.lon.toFixed(7))); rows.append(row);
  }
  id("deskPlaces").replaceChildren(rows); id("deskPlacesPanel").hidden = !data.waypoints.length;
  id("deskPlacesNote").textContent = `Showing ${Math.min(100, data.waypoints.length)} of ${data.waypoints.length} waypoints. CSV exports all waypoints, rounded to 7 decimal places.`;
  id("deskClearTrace").disabled = false; id("deskExportPlaces").disabled = !data.waypoints.length; id("deskCollectWaypoints").disabled = !data.waypoints.length;
  routeExplorer.load(data, projected);
}
async function readGPX(file) {
  if (!file) return;
  clearTrace("Reading your GPX file on this device…"); const generation = readGeneration;
  try {
    if (file.size > MAX_GPX_BYTES) throw new Error("Choose a GPX file no larger than 2 MiB.");
    const text = await file.text(); if (generation !== readGeneration) return;
    const parsed = parseGPX(text); trace = parsed; renderTrace(parsed, file.name);
    id("deskTraceStatus").textContent = "File inspected locally. Length follows the supplied track/route points; it excludes gaps between segments and is not a driving-distance calculation.";
  } catch (error) {
    if (generation !== readGeneration) return;
    clearTrace(error.message || "The file could not be opened."); id("deskTraceStatus").classList.add("error");
  }
}
id("deskGpx").addEventListener("change", () => readGPX(id("deskGpx").files[0]));
id("deskClearTrace").addEventListener("click", () => clearTrace());
id("deskExportPlaces").addEventListener("click", () => { if (trace) { download(waypointCSV(trace.waypoints), "text/csv;charset=utf-8", "fieldforge-gpx-places.csv"); id("deskTraceStatus").textContent = "Waypoint CSV saved. Import it into FieldForge’s local place catalog; verify the file’s coordinates before use."; } });
id("deskCollectWaypoints").addEventListener("click", () => { if (trace?.waypoints.length) collectPlaces(trace.waypoints,GPX_SOURCE,"GPX waypoints","deskTraceStatus"); });
const drop = id("deskDrop");
for (const name of ["dragenter", "dragover"]) drop.addEventListener(name, event => { event.preventDefault(); drop.classList.add("dragging"); });
for (const name of ["dragleave", "drop"]) drop.addEventListener(name, event => { event.preventDefault(); drop.classList.remove("dragging"); });
drop.addEventListener("drop", event => { if (event.dataTransfer.files.length !== 1) { id("deskTraceStatus").textContent = "Choose one GPX file at a time."; return; } readGPX(event.dataTransfer.files[0]); });
renderRegions(); updateBrief(false);
