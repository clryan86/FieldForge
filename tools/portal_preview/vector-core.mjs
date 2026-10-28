export const MAX_VECTOR_BYTES = 4 * 1024 * 1024;
export const MAX_VECTOR_FEATURES = 1000;
export const MAX_VECTOR_POSITIONS = 10000;
export const VECTOR_SOURCE = "User-supplied GeoJSON vertex; WGS 84; not independently verified";

export function vectorLabel(value, fallback, limit = 120) {
  const text = typeof value === "string" || typeof value === "number" ? String(value) : "";
  return [...text.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069\ufffe\uffff\ud800-\udfff]/gu," ").trim()].slice(0,limit).join("") || fallback;
}
export function parseGeoJSON(text) {
  if (typeof text !== "string" || new TextEncoder().encode(text).length > MAX_VECTOR_BYTES) throw new Error("Choose a GeoJSON file no larger than 4 MiB.");
  let root; try { root = JSON.parse(text.replace(/^\uFEFF/,""),(key,value) => { if (typeof value === "number" && !Number.isFinite(value)) throw new Error("Number overflow"); return value; }); } catch { throw new Error("The file must contain valid JSON with finite numbers."); }
  const object = (value,label) => { if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${label} must be a GeoJSON object.`); if (Object.hasOwn(value,"crs")) throw new Error("Legacy or projected CRS is not supported. Re-export as WGS 84 GeoJSON (RFC 7946)."); };
  object(root,"Document");
  const input = root.type === "FeatureCollection" ? root.features : [root.type === "Feature" ? root : {type:"Feature",geometry:root,properties:null}];
  if (!Array.isArray(input) || !input.length || input.length > MAX_VECTOR_FEATURES) throw new Error("Choose 1 to 1,000 GeoJSON features.");
  let count = 0, parts = 0;
  const list = (value,min,label) => { if (!Array.isArray(value) || value.length < min) throw new Error(`${label} is empty or incomplete.`); return value; };
  const position = value => {
    if (!Array.isArray(value) || ![2,3].includes(value.length) || !value.every(Number.isFinite) || Math.abs(value[0]) > 180 || Math.abs(value[1]) > 90) throw new Error("Positions need longitude, latitude and optionally altitude, as finite WGS 84 numbers.");
    if (++count > MAX_VECTOR_POSITIONS) throw new Error("This viewer accepts up to 10,000 coordinate positions. Export a smaller area.");
    return value;
  };
  const path = (value,ring) => {
    const points = list(value,ring ? 4 : 2,ring ? "Polygon ring" : "LineString").map(position);
    if (ring && (points[0].length !== points.at(-1).length || points[0].some((v,i) => v !== points.at(-1)[i]))) throw new Error("Polygon rings must close with an identical first and last position.");
    for (let i=1;i<points.length;i++) if (Math.abs(points[i][0]-points[i-1][0]) > 180) throw new Error("An edge spans more than 180° longitude. Split date-line crossings into separate parts before opening this file.");
    return points;
  };
  const features = input.map((raw,index) => {
    object(raw,"Feature");
    if (raw.type !== "Feature" || !Object.hasOwn(raw,"geometry") || !Object.hasOwn(raw,"properties") || (raw.properties !== null && (typeof raw.properties !== "object" || Array.isArray(raw.properties)))) throw new Error("Each Feature needs geometry and object-or-null properties.");
    if (Object.hasOwn(raw,"id") && typeof raw.id !== "string" && !(typeof raw.id === "number" && Number.isFinite(raw.id))) throw new Error("Feature IDs must be strings or finite numbers.");
    const shapes = [], vertices = [];
    const add = (kind,coordinates) => {
      if (++parts > 2000) throw new Error("This viewer accepts up to 2,000 geometry parts. Export a smaller layer.");
      shapes.push({kind,coordinates});
      if (kind === "point") vertices.push(coordinates);
      else if (kind === "line") vertices.push(...coordinates);
      else for (const ring of coordinates) vertices.push(...ring);
    };
    function geometry(value,depth = 0) {
      if (value === null && depth === 0) return;
      object(value,"Geometry"); if (depth > 8) throw new Error("Geometry collections are nested too deeply (maximum 8).");
      const coords = value.coordinates;
      switch(value.type) {
        case "Point": add("point",position(coords)); break;
        case "MultiPoint": for (const p of list(coords,1,"MultiPoint")) add("point",position(p)); break;
        case "LineString": add("line",path(coords,false)); break;
        case "MultiLineString": for (const line of list(coords,1,"MultiLineString")) add("line",path(line,false)); break;
        case "Polygon": add("polygon",list(coords,1,"Polygon").map(ring => path(ring,true))); break;
        case "MultiPolygon": for (const polygon of list(coords,1,"MultiPolygon")) add("polygon",list(polygon,1,"Polygon").map(ring => path(ring,true))); break;
        case "GeometryCollection": for (const child of list(value.geometries,1,"GeometryCollection")) geometry(child,depth+1); break;
        default: throw new Error("Unsupported geometry. Use GeoJSON points, lines, polygons or geometry collections.");
      }
    }
    geometry(raw.geometry);
    const feature = {type:"Feature",properties:raw.properties,geometry:raw.geometry}; if (Object.hasOwn(raw,"id")) feature.id = raw.id;
    return {label:vectorLabel(raw.properties?.name,`Feature ${index+1}`),type:raw.geometry?.type || "No geometry",shapes,vertices,feature};
  });
  if (!count) throw new Error("The file has no drawable coordinates.");
  return {features,positions:count,parts,unlocated:features.filter(feature => !feature.vertices.length).length};
}
export function projectVectors(data) {
  let west=180,east=-180,south=90,north=-90;
  for (const feature of data.features) for (const [lon,lat] of feature.vertices) { west=Math.min(west,lon);east=Math.max(east,lon);south=Math.min(south,lat);north=Math.max(north,lat); }
  const scale = Math.min(752/Math.max(east-west,1e-5),332/Math.max(north-south,1e-5));
  const point = ([lon,lat]) => [400+(lon-(west+east)/2)*scale,190-(lat-(south+north)/2)*scale];
  return {bounds:{west,east,south,north},features:data.features.map(feature => ({vertices:feature.vertices.map(point),shapes:feature.shapes.map(shape => ({kind:shape.kind,coordinates:shape.kind === "point" ? point(shape.coordinates) : shape.kind === "line" ? shape.coordinates.map(point) : shape.coordinates.map(ring => ring.map(point))}))}))};
}
export function vectorPath(shape) {
  const line = points => points.map(([x,y],i) => `${i ? "L" : "M"}${x.toFixed(3)},${y.toFixed(3)}`).join(" ");
  return shape.kind === "polygon" ? shape.coordinates.map(ring => line(ring)+" Z").join(" ") : line(shape.coordinates);
}
export function vectorPlace(feature,index,filename) {
  const point = feature.vertices[index]; if (!point) throw new Error("Choose a coordinate vertex first.");
  return {name:vectorLabel(`${feature.label} · vertex ${index+1}`,"GeoJSON vertex",160),lat:point[1],lon:point[0],source:`${VECTOR_SOURCE}; file: ${vectorLabel(filename,"unnamed file",160)}`};
}
export function selectedGeoJSON(feature) { return JSON.stringify(feature.feature,null,2)+"\n"; }
