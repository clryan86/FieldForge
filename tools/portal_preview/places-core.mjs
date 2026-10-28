export const MAX_PLACES = 1000;
export const MAX_PLACE_BYTES = 4 * 1024 * 1024;
export const PLACES_KIND = "fieldforge-place-collection";
export const MANUAL_SOURCE = "User-entered coordinates; WGS 84; not independently verified";
export const GPX_SOURCE = "User-supplied GPX; WGS 84; not independently verified";
export const IMAGE_SOURCE = "User-supplied image bounds and projection; pixel center; WGS 84; not independently verified";

function plainText(value, label, limit) {
  if (typeof value !== "string" || !value.trim() || [...value].length > limit || /[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069\ufffe\uffff\ud800-\udfff]/u.test(value)) throw new Error(`${label} must be nonempty plain text, at most ${limit} characters, without control characters.`);
  return value.trim();
}
export function validatePlace(value) {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).some(key => !["name", "lat", "lon", "source"].includes(key))) throw new Error("Each place needs only name, lat, lon and source fields.");
  if (![value.lat, value.lon].every(number => typeof number === "number" && Number.isFinite(number)) || Math.abs(value.lat) > 90 || Math.abs(value.lon) > 180) throw new Error("Use finite WGS 84 latitude within ±90° and longitude within ±180°.");
  return {name:plainText(value.name,"Place name",160),lat:value.lat,lon:value.lon,source:plainText(value.source,"Source note",512)};
}
export function manualPlace(name, latitude, longitude, source = "") {
  const coordinate = (text,limit,label) => {
    if (typeof text !== "string" || text.length > 400 || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text.trim())) throw new Error(`${label} requires decimal degrees; blanks, direction letters and scientific notation are not accepted.`);
    const value = Number(text); if (!Number.isFinite(value) || Math.abs(value) > limit) throw new Error(`${label} must be within ±${limit}°.`); return value;
  };
  return validatePlace({name,lat:coordinate(latitude,90,"Latitude"),lon:coordinate(longitude,180,"Longitude"),source:source.trim() || MANUAL_SOURCE});
}
export function placeCoordinateText(value) {
  const raw = String(value); if (!raw.includes("e")) return raw;
  const [coefficient,exponent] = raw.split("e"), sign = coefficient.startsWith("-") ? "-" : "", unsigned = coefficient.replace("-", ""), digits = unsigned.replace(".", "");
  const position = (unsigned.indexOf(".") < 0 ? unsigned.length : unsigned.indexOf(".")) + Number(exponent);
  return sign + (position <= 0 ? "0." + "0".repeat(-position) + digits : position >= digits.length ? digits + "0".repeat(position-digits.length) : digits.slice(0,position) + "." + digits.slice(position));
}
function collection(points, allowEmpty = false) {
  if (!Array.isArray(points) || points.length > MAX_PLACES || (!points.length && !allowEmpty)) throw new Error("Use a collection of 1 to 1,000 places.");
  return points.map(validatePlace);
}
export function mergePlaces(existing, incoming) {
  collection(existing,true); const checked = collection(incoming);
  const key = point => JSON.stringify([point.name,point.lat,point.lon,point.source]);
  const seen = new Set(existing.map(key)), added = [];
  for (const point of checked) { const fingerprint = key(point); if (!seen.has(fingerprint)) { seen.add(fingerprint); added.push(point); } }
  if (existing.length + added.length > MAX_PLACES) throw new Error("This would exceed 1,000 places. Nothing was added; remove places or choose a smaller collection.");
  return {places:[...existing,...added],added:added.length,duplicates:incoming.length-added.length};
}
export function matchingPlaces(points, query) {
  const fold = text => text.normalize("NFKD").replace(/\p{M}/gu,"").toLocaleLowerCase();
  const terms = fold(query.trim()).split(/\s+/).filter(Boolean);
  return points.filter(point => { const text = fold(point.name + " " + point.source); return terms.every(term => text.includes(term)); });
}
function boundedText(text) {
  if (typeof text !== "string" || new TextEncoder().encode(text).length > MAX_PLACE_BYTES || !text.trim()) throw new Error("Choose a nonempty UTF-8 collection no larger than 4 MiB.");
  return text.replace(/^\uFEFF/,"");
}
export function parsePlacesJSON(text) {
  let data; try { data = JSON.parse(boundedText(text)); } catch (error) { throw new Error("The collection is not valid JSON: " + error.message); }
  if (!data || data.kind !== PLACES_KIND || data.schema_version !== 1 || Object.keys(data).some(key => !["kind","schema_version","places"].includes(key))) throw new Error("Choose a FieldForge place-collection JSON file, not a source plan or map-bounds file.");
  return collection(data.places);
}
export function parsePlacesCSV(text) {
  text = boundedText(text);
  const rows = []; let row = [], field = "", quoted = false, closed = false;
  const endField = () => { row.push(field); field = ""; closed = false; if (row.length > 4) throw new Error("CSV supports name,latitude,longitude and optional source columns only."); };
  const endRow = () => { endField(); if (!(row.length === 1 && row[0] === "")) rows.push(row); row = []; if (rows.length > MAX_PLACES + 1) throw new Error("The CSV exceeds 1,000 places."); };
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (quoted) { if (char === '"') { if (text[index+1] === '"') { field += '"'; index++; } else { quoted = false; closed = true; } } else field += char; }
    else if (char === ",") endField();
    else if (char === "\n" || char === "\r") { if (char === "\r" && text[index+1] === "\n") index++; endRow(); }
    else if (char === '"' && field === "" && !closed) quoted = true;
    else { if (closed || char === '"') throw new Error("Malformed CSV quoting. Quote entire fields and double any quotation marks inside them."); field += char; }
    if (field.length > 4096) throw new Error("A CSV field is too long.");
  }
  if (quoted) throw new Error("The CSV ends inside a quoted field.");
  if (field || row.length || closed) endRow();
  const header = rows.shift()?.map(value => value.trim().toLowerCase());
  if (!header || new Set(header).size !== header.length || !["name","latitude","longitude"].every(key => header.includes(key)) || header.some(key => !["name","latitude","longitude","source"].includes(key))) throw new Error("CSV requires unique name,latitude,longitude columns and optional source. Other columns are not supported here.");
  const points = rows.map((values,index) => {
    if (values.length !== header.length) throw new Error(`CSV record ${index+1} has a different field count from its header.`);
    const record = Object.fromEntries(header.map((key,i) => [key,values[i]]));
    try { return manualPlace(record.name,record.latitude,record.longitude,record.source || "Imported CSV; source unspecified; WGS 84; not independently verified"); }
    catch (error) { throw new Error(`CSV record ${index+1}: ${error.message}`); }
  });
  return collection(points);
}
export function placesJSON(points) {
  return JSON.stringify({kind:PLACES_KIND,schema_version:1,places:collection(points)},null,2) + "\n";
}
function decimal(value) { return value.toFixed(7).replace(/\.?0+$/,"").replace(/^-0$/,"0"); }
export function placesCSV(points) {
  const checked = collection(points);
  const quote = value => '"' + value.replace(/"/g,'""') + '"';
  const safe = (text, limit) => { if (!/^[=+@-]/.test(text)) return text; if ([...text].length >= limit) throw new Error("Shorten a formula-like label by one character for safe CSV export, or use collection JSON."); return "'" + text; };
  return "name,latitude,longitude,source\r\n" + checked.map(point => [safe(point.name,160),decimal(point.lat),decimal(point.lon),safe(point.source,512)].map(quote).join(",")).join("\r\n") + "\r\n";
}
export function placesGPX(points) {
  const checked = collection(points);
  if (checked.length > 200) throw new Error("GPX export supports up to 200 matching places for the desktop importer. Narrow your search or use CSV/JSON.");
  const names = new Set();
  for (const point of checked) { const name = point.name.toLocaleLowerCase(); if (names.has(name)) throw new Error("GPX needs distinct place names for desktop import. Rename duplicates or narrow your search."); names.add(name); }
  const xml = text => text.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&apos;");
  const records = checked.map(point => { const longitude = decimal(point.lon); return `  <wpt lat="${decimal(point.lat)}" lon="${Number(longitude) === 180 ? "-180" : longitude}"><name>${xml(point.name)}</name><desc>${xml(point.source)}</desc><type>waypoint</type></wpt>`; });
  return '<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="FieldForge preparation desk" xmlns="http://www.topografix.com/GPX/1/1">\n' + records.join("\n") + "\n</gpx>\n";
}
