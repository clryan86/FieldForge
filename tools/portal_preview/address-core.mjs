import {validatePlace} from "./places-core.mjs";

export const ADDRESS_ENDPOINT = "https://photon.komoot.io/api/";
export const ADDRESS_LIMIT = 5;
export const ADDRESS_MAX_BYTES = 256 * 1024;

export function addressQuery(value, scope) {
  if (typeof value !== "string" || /[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069\ud800-\udfff]/u.test(value)) throw new Error("Enter an address or place name without control characters.");
  const query = value.trim().replace(/\s+/gu, " ");
  if ([...query].length < 3 || [...query].length > 300) throw new Error("Use between 3 and 300 characters. Include a town and country for a clearer match.");
  if (!["US", "world"].includes(scope)) throw new Error("Choose United States or Worldwide.");
  return {query, scope};
}

export function addressURL(query, scope) {
  const checked = addressQuery(query, scope), url = new URL(ADDRESS_ENDPOINT);
  url.searchParams.set("q", checked.query);
  url.searchParams.set("limit", String(ADDRESS_LIMIT));
  url.searchParams.set("lang", "en");
  if (checked.scope === "US") url.searchParams.set("countrycode", "US");
  return url.href;
}

function clean(value, limit = 180) {
  if (value === undefined || value === null) return "";
  if (typeof value !== "string" || value.length > 4096) throw new Error("The address service returned an invalid label.");
  return [...value.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069\ufffe\uffff\ud800-\udfff]/gu, "").trim().replace(/\s+/gu, " ")].slice(0, limit).join("");
}

export function parseAddressResults(data, retrievedAt) {
  if (!data || typeof data !== "object" || Array.isArray(data) || (data.type !== undefined && data.type !== "FeatureCollection") || !Array.isArray(data.features) || data.features.length > ADDRESS_LIMIT) throw new Error("The address service returned an unexpected result format.");
  if (typeof retrievedAt !== "string" || !Number.isFinite(Date.parse(retrievedAt))) throw new Error("The lookup time could not be recorded.");
  return data.features.map(feature => {
    const coordinates = feature?.geometry?.coordinates, props = feature?.properties;
    if (feature?.type !== "Feature" || feature.geometry?.type !== "Point" || !Array.isArray(coordinates) || coordinates.length !== 2 || !coordinates.every(value => typeof value === "number" && Number.isFinite(value)) || Math.abs(coordinates[0]) > 180 || Math.abs(coordinates[1]) > 90 || !props || typeof props !== "object" || Array.isArray(props)) throw new Error("The address service returned an invalid coordinate. No results were added.");
    const street = [clean(props.housenumber, 40), clean(props.street)].filter(Boolean).join(" ");
    const parts = [clean(props.name), street, clean(props.city || props.locality || props.district), clean(props.state), clean(props.postcode, 32), clean(props.country)];
    const label = [...new Set(parts.filter(Boolean))].join(", ") || "Unnamed search result";
    const name = [...label].slice(0, 160).join("");
    const matchType = clean(props.type || props.osm_value, 60) || "unspecified";
    const osmIdentity = ["N", "W", "R"].includes(props.osm_type) && Number.isSafeInteger(props.osm_id) && props.osm_id > 0 ? `OSM ${props.osm_type}/${props.osm_id}` : "OSM identifier unavailable";
    const point = validatePlace({name, lat:coordinates[1], lon:coordinates[0], source:`Photon / Komoot; OpenStreetMap contributors (ODbL); https://www.openstreetmap.org/copyright; ${osmIdentity}; retrieved ${retrievedAt}; match type: ${matchType}; WGS 84; not independently verified`});
    return {label, matchType, osmIdentity, retrievedAt, point};
  });
}
