// Browser-local calculations only. No network or storage dependencies.
export const MAX_GPX_BYTES = 2 * 1024 * 1024;
export const MAX_POINTS = 25000;
export const MAX_WAYPOINTS = 1000;
export const PLAN_KIND = "fieldforge-source-plan";
const radians = value => value * Math.PI / 180;

export function downloadEstimate(bytes, budgetGB, speedMbps) {
  if (!Number.isFinite(bytes) || bytes < 0 || bytes > 1e15) throw new Error("Invalid download size.");
  if (!Number.isFinite(budgetGB) || budgetGB < 0.1 || budgetGB > 1000) throw new Error("Enter a download budget from 0.1 to 1,000 GB.");
  if (!Number.isFinite(speedMbps) || speedMbps < 0.1 || speedMbps > 10000) throw new Error("Enter a connection speed from 0.1 to 10,000 Mbps.");
  return {bytes, remainingBytes: budgetGB * 1e9 - bytes, seconds: bytes * 8 / (speedMbps * 1e6), overBudget: bytes > budgetGB * 1e9};
}

export function validatePlan(data, knownIds) {
  if (!data || typeof data !== "object" || Array.isArray(data) || data.kind !== PLAN_KIND || data.schema_version !== 1) throw new Error("Choose a FieldForge source plan saved by this preparation desk.");
  if (!Array.isArray(data.region_ids) || data.region_ids.length > 53 || data.region_ids.some(id => typeof id !== "string" || !knownIds.has(id))) throw new Error("This plan contains regions that are not in the current source directory.");
  if (new Set(data.region_ids).size !== data.region_ids.length) throw new Error("The plan contains duplicate regions.");
  downloadEstimate(0, data.budget_gb, data.speed_mbps);
  return {kind: PLAN_KIND, schema_version: 1, region_ids: [...data.region_ids], budget_gb: data.budget_gb, speed_mbps: data.speed_mbps};
}

export function coordinate(raw, limit) {
  if (typeof raw !== "string" || raw.length > 80 || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(raw.trim())) throw new Error("The GPX file contains an invalid coordinate.");
  const value = Number(raw);
  if (!Number.isFinite(value) || Math.abs(value) > limit) throw new Error("The GPX file contains an out-of-range coordinate.");
  return value;
}

function children(element, name) { return [...element.children].filter(node => node.localName === name && node.namespaceURI === element.namespaceURI); }
function readPoint(element) {
  const name = children(element, "name")[0]?.textContent?.trim() || "";
  return {lat: coordinate(element.getAttribute("lat"), 90), lon: coordinate(element.getAttribute("lon"), 180), name: [...name].slice(0, 160).join("")};
}

export function parseGPX(text, Parser = globalThis.DOMParser) {
  if (typeof text !== "string" || new TextEncoder().encode(text).length > MAX_GPX_BYTES) throw new Error("Choose a GPX file no larger than 2 MiB.");
  // Do not resolve entities or accept document type declarations from files.
  if (/<!DOCTYPE|<!ENTITY/i.test(text)) throw new Error("GPX files with document types or entity declarations are not supported.");
  const document = new Parser().parseFromString(text, "application/xml");
  const root = document.documentElement;
  if (!root || root.localName !== "gpx" || document.getElementsByTagName("parsererror").length) throw new Error("This file is not valid GPX XML.");
  if (![null, "", "http://www.topografix.com/GPX/1/0", "http://www.topografix.com/GPX/1/1"].includes(root.namespaceURI)) throw new Error("This GPX namespace is not supported.");
  const segments = [], waypoints = [];
  let count = 0;
  function points(elements) {
    count += elements.length;
    if (count > MAX_POINTS) throw new Error("This file exceeds 25,000 points. Use a smaller GPX file.");
    return elements.map(readPoint);
  }
  waypoints.push(...points(children(root, "wpt")));
  if (waypoints.length > MAX_WAYPOINTS) throw new Error("This file exceeds 1,000 waypoints. Split it into smaller files.");
  for (const route of children(root, "rte")) { const part = points(children(route, "rtept")); if (part.length) segments.push(part); }
  for (const track of children(root, "trk")) for (const segment of children(track, "trkseg")) { const part = points(children(segment, "trkpt")); if (part.length) segments.push(part); }
  if (!count) throw new Error("No waypoints, route points or track points were found in this GPX file.");
  return analyzeGeometry({segments, waypoints});
}

export function pointDistance(a, b) {
  const dLat = radians(b.lat - a.lat), dLon = radians(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(radians(a.lat)) * Math.cos(radians(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 6371008.8 * 2 * Math.asin(Math.sqrt(Math.max(0, Math.min(1, h))));
}

export function analyzeGeometry({segments, waypoints}) {
  const all = [...segments.flat(), ...waypoints];
  if (!all.length || all.length > MAX_POINTS || waypoints.length > MAX_WAYPOINTS) throw new Error("Unsupported point count.");
  for (const p of all) if (![p.lat, p.lon].every(Number.isFinite) || Math.abs(p.lat) > 90 || Math.abs(p.lon) > 180) throw new Error("Invalid coordinate.");
  let meters = 0;
  for (const segment of segments) for (let i = 1; i < segment.length; i++) meters += pointDistance(segment[i - 1], segment[i]);
  return {segments, waypoints, meters, geometryPoints: segments.reduce((sum, part) => sum + part.length, 0)};
}

export function projectTrace(data) {
  const first = data.segments.find(part => part.length)?.[0] || data.waypoints[0];
  const wrap = delta => ((delta + 180) % 360 + 360) % 360 - 180;
  const parts = data.segments.map(part => {
    let previous = first.lon, unwrapped = first.lon;
    return part.map(p => { unwrapped += wrap(p.lon - previous); previous = p.lon; return [unwrapped, p.lat]; });
  });
  const places = data.waypoints.map(p => [first.lon + wrap(p.lon - first.lon), p.lat]);
  const all = [...parts.flat(), ...places];
  const lats = all.map(p => p[1]);
  const mean = (Math.min(...lats) + Math.max(...lats)) / 2;
  const xFactor = Math.max(0.01, Math.cos(radians(mean)));
  const projected = all.map(([x, y]) => [x * xFactor, -y]);
  const minX = Math.min(...projected.map(p => p[0])), maxX = Math.max(...projected.map(p => p[0]));
  const minY = Math.min(...projected.map(p => p[1])), maxY = Math.max(...projected.map(p => p[1]));
  const scale = Math.min(700 / Math.max(maxX - minX, 1e-9), 270 / Math.max(maxY - minY, 1e-9));
  const project = ([x, y]) => [400 + (x * xFactor - (minX + maxX) / 2) * scale, 190 + (-y - (minY + maxY) / 2) * scale];
  return {parts: parts.map(part => part.map(project)), places: places.map(project)};
}

export function waypointCSV(waypoints) {
  if (!waypoints.length || waypoints.length > MAX_WAYPOINTS) throw new Error("No exportable waypoints.");
  const quote = value => '"' + String(value).replace(/"/g, '""') + '"';
  // Protect a spreadsheet opening the exported CSV from formulas in GPX names.
  const safeName = (value, index) => {
    let name = (value || "").replace(/[\u0000-\u001f\u007f]/g, " ").trim() || `Waypoint ${index + 1}`;
    if (/^[=+@-]/.test(name)) name = "'" + name;
    return [...name].slice(0, 160).join("");
  };
  return "name,latitude,longitude,source\r\n" + waypoints.map((p, index) => [safeName(p.name, index), p.lat.toFixed(7).replace(/\.?0+$/, ""), p.lon.toFixed(7).replace(/\.?0+$/, ""), "User-supplied GPX; exported by FieldForge preparation desk; WGS 84; not independently verified"].map(quote).join(",")).join("\r\n") + "\r\n";
}
