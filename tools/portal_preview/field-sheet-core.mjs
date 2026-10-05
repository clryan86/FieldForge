import {validatePlace} from "./places-core.mjs";

export const MAX_SHEET_PLACES = 100;
export const EARTH_RADIUS_M = 6371008.8;
export const GEOMETRY_NOTE = "Approximate great-circle distance on a sphere. Initial bearing is clockwise from true north; no magnetic declination is applied. This is not road distance, travel time, a magnetic compass heading or a safe-route assessment. Terrain, obstacles and access rights are not evaluated.";
export const COORDINATE_NOTE = "WGS 84 decimal degrees, latitude first. Coordinates and source labels are user supplied and not independently verified. Displayed decimal places do not establish accuracy.";

// Matches the desktop Places spherical model and its degeneracy thresholds.
export function comparePlaces(start, end) {
  const from = validatePlace(start), to = validatePlace(end), radians = Math.PI / 180;
  const lat1 = from.lat*radians, lat2 = to.lat*radians, lon1 = from.lon*radians, lon2 = to.lon*radians;
  const a = [Math.cos(lat1)*Math.cos(lon1),Math.cos(lat1)*Math.sin(lon1),Math.sin(lat1)];
  const b = [Math.cos(lat2)*Math.cos(lon2),Math.cos(lat2)*Math.sin(lon2),Math.sin(lat2)];
  const cross = [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const angle = Math.atan2(Math.hypot(...cross),a.reduce((sum,value,index) => sum+value*b[index],0));
  let bearing = null, reason = "";
  if (angle < 1e-10) reason = "Coincident or extremely close points: no meaningful direction.";
  else if (Math.PI-angle < 1e-8) reason = "Antipodal or nearly antipodal points: no stable unique initial bearing.";
  else if (Math.abs(Math.cos(lat1)) < 1e-10) reason = "Start at or extremely near a geographic pole: true north is undefined here.";
  else {
    const delta = lon2-lon1, x = Math.sin(delta)*Math.cos(lat2), y = Math.cos(lat1)*Math.sin(lat2)-Math.sin(lat1)*Math.cos(lat2)*Math.cos(delta);
    bearing = ((Math.atan2(x,y)/radians)%360+360)%360;
  }
  return {from,to,meters:angle*EARTH_RADIUS_M,bearing,reason};
}
export function distanceText(meters, units = "metric") {
  if (!Number.isFinite(meters) || meters < 0 || !["metric","imperial"].includes(units)) throw new Error("Invalid distance or display units.");
  if (meters === 0) return units === "metric" ? "0 m" : "0 ft";
  if (units === "metric") return meters < 1 ? "<1 m" : meters < 1000 ? `${meters.toFixed(0)} m` : `${(meters/1000).toFixed(2)} km`;
  const feet = meters/.3048; return feet < 1 ? "<1 ft" : meters < 1609.344 ? `${feet.toFixed(0)} ft` : `${(meters/1609.344).toFixed(2)} mi`;
}
export function bearingText(result) {
  return result.bearing === null ? "Unavailable" : `${((Math.round(result.bearing*10)%3600)/10).toFixed(1)}° true`;
}
export function coordinateText(point) { return `${point.lat.toFixed(7)}, ${point.lon.toFixed(7)}`; }
export function captureFieldSheet(points, {title = "FieldForge place sheet", includeSources = true, units = "metric", comparison = null, createdAt = new Date().toISOString()} = {}) {
  if (!Array.isArray(points) || !points.length || points.length > MAX_SHEET_PLACES) throw new Error("A field sheet holds 1 to 100 matching places. Narrow your search before preparing it.");
  if (typeof title !== "string" || !title.trim() || [...title].length > 100 || /[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069\ufffe\uffff\ud800-\udfff]/u.test(title)) throw new Error("Use a plain-text sheet title of 1 to 100 characters.");
  if (typeof includeSources !== "boolean" || !["metric","imperial"].includes(units)) throw new Error("Invalid field-sheet options.");
  if (typeof createdAt !== "string" || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(createdAt) || (!Number.isFinite(Date.parse(createdAt)) || new Date(createdAt).toISOString() !== createdAt)) throw new Error("Invalid preparation time.");
  const copies = points.map(point => Object.freeze(validatePlace(point)));
  let leg = null;
  if (comparison) {
    const from = validatePlace(comparison.from), to = validatePlace(comparison.to), key = point => JSON.stringify(point);
    if (![from,to].every(point => copies.some(copy => key(copy) === key(point)))) throw new Error("Both comparison endpoints must be among the places on this sheet.");
    const calculated = comparePlaces(from,to);
    leg = Object.freeze({...calculated,from:Object.freeze(calculated.from),to:Object.freeze(calculated.to)});
  }
  return Object.freeze({title:title.trim(),includeSources,units,createdAt,points:Object.freeze(copies),comparison:leg});
}
const PRINT_STYLE = `:root{color-scheme:light}*{box-sizing:border-box}body{margin:0 auto;padding:24px;max-width:950px;background:white;color:#17251d;font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}header{border-bottom:3px solid #17251d;padding-bottom:14px;margin-bottom:20px}.brand{text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:700}h1{font-size:28px;line-height:1.2;margin:10px 0;overflow-wrap:anywhere}h2{font-size:20px;margin:20px 0 8px}.meta,.note{font-size:14px;color:#394a3e}.note{border-left:3px solid #71856b;padding-left:12px}.instructions{border:1px solid #aab7a4;padding:12px;background:#f1f5ed}article{border:1px solid #aab7a4;margin:12px 0;padding:14px;break-inside:avoid;page-break-inside:avoid}article h2{font-size:17px;margin:0 0 8px;overflow-wrap:anywhere}.coordinates{font-family:ui-monospace,monospace;font-size:15px;overflow-wrap:anywhere}.source{font-size:14px;margin:8px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}.pair p{margin:4px 0;overflow-wrap:anywhere}.estimate{border:2px solid #71856b;padding:16px;break-inside:avoid}.numbers{display:flex;gap:30px;flex-wrap:wrap}.numbers strong{display:block;font-size:23px}.numbers span{font-size:14px}footer{border-top:1px solid #aab7a4;margin-top:24px;padding-top:12px;font-size:13px;overflow-wrap:anywhere}@media(max-width:600px){body{padding:16px}.pair{grid-template-columns:1fr}.numbers{gap:16px}}@page{size:auto;margin:14mm}@media print{body{max-width:none;padding:0;font-size:11pt}header{margin-bottom:14px}h1{font-size:22pt}.instructions{display:none}.meta,.note,.source{font-size:10pt}article{padding:10px}.coordinates{font-size:11pt}.numbers strong{font-size:17pt}footer{font-size:9pt}}`;
export function fieldSheetHTML(snapshot) {
  // Revalidate a caller-provided capture; never treat labels as markup.
  const sheet = captureFieldSheet(snapshot.points,snapshot);
  const escape = value => String(value).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
  const coordinateLine = point => `Latitude ${point.lat.toFixed(7)} · Longitude ${point.lon.toFixed(7)}`;
  const leg = sheet.comparison;
  const pair = leg ? `<section class="estimate"><h2>Point-to-point estimate</h2><div class="pair"><div><strong>From</strong><p>${escape(leg.from.name)}</p><p class="coordinates">${escape(coordinateLine(leg.from))}</p></div><div><strong>To</strong><p>${escape(leg.to.name)}</p><p class="coordinates">${escape(coordinateLine(leg.to))}</p></div></div><div class="numbers"><p><span>Approximate great-circle distance</span><strong>${escape(distanceText(leg.meters,sheet.units))}</strong></p><p><span>Initial true bearing</span><strong>${escape(bearingText(leg))}</strong></p></div>${leg.reason ? `<p>${escape(leg.reason)}</p>` : ""}<p class="note">${GEOMETRY_NOTE}</p></section>` : "";
  const rows = sheet.points.map((point,index) => `<article><h2>${index+1}. ${escape(point.name)}</h2><div class="coordinates">${escape(coordinateLine(point))}</div>${sheet.includeSources ? `<p class="source"><strong>Source note:</strong> ${escape(point.source)}</p>` : ""}</article>`).join("\n");
  return `<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'"><title>${escape(sheet.title)}</title><style>${PRINT_STYLE}</style></head><body><header><div class="brand">FieldForge / field sheet</div><h1>${escape(sheet.title)}</h1><p class="meta">${sheet.points.length} places · Prepared ${escape(sheet.createdAt)} (device UTC)</p><p class="meta">Source notes ${sheet.includeSources ? "included" : "omitted by choice"}. This is a fixed snapshot; later collection edits do not update this file.</p></header><p class="instructions">Open your browser’s Print command to print this sheet or save a PDF where available. This file opens offline and contains no scripts or external resources.</p><p class="note">${COORDINATE_NOTE}</p>${pair}<section aria-label="Place coordinates">${rows}</section><footer>Contains precise locations in plain text. Keep or share this copy only as intended. Coordinates are printed to seven decimal places; keep collection JSON for original numeric precision.</footer></body></html>\n`;
}
