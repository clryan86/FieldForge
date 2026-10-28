import test from "node:test";
import assert from "node:assert/strict";
import {validatePlace, manualPlace, placeCoordinateText, mergePlaces, matchingPlaces, parsePlacesJSON, parsePlacesCSV, placesJSON, placesCSV, placesGPX, MANUAL_SOURCE, MAX_PLACE_BYTES} from "./places-core.mjs";
const place = (name = "Example", lat = 0, lon = 0, source = "User-supplied test coordinates") => ({name,lat,lon,source});

test("places distinguish zero from blank and validate text and WGS 84 coordinates", () => {
  assert.deepEqual(manualPlace(" Zero ","0","-180"),place("Zero",0,-180,MANUAL_SOURCE));
  for (const value of [""," ","1e2","20 N","NaN","Infinity","90.0001","1+2"]) assert.throws(() => manualPlace("Point",value,"0"));
  for (const edit of [{lat:true},{lat:NaN},{lon:181},{name:""},{name:"a".repeat(161)},{source:"x".repeat(513)},{source:"a\nb"},{name:"\ud800"},{name:"invisible\u202e"},{notes:"silently dropped?"}]) assert.throws(() => validatePlace({...place(),...edit}));
  assert.equal(validatePlace(place("خيمة 🧭")).name,"خيمة 🧭");
});
test("editing tiny coordinates does not introduce scientific notation or rounding", () => {
  for (const value of [0,90,-90,1e-10,-1.25e-9,5e-324]) {
    const text = placeCoordinateText(value); assert.ok(!text.includes("e")); assert.equal(Number(text),value);
    assert.equal(manualPlace("Point",text,"0").lat,value);
  }
});
test("merge skips exact duplicates and preserves distinct sources, names and existing objects", () => {
  const original = place(), existing = [original];
  const merged = mergePlaces(existing,[place(),place("Another"),place("Example",0,0,"Different source")]);
  assert.equal(merged.added,2); assert.equal(merged.duplicates,1); assert.equal(merged.places[0],original); assert.equal(existing.length,1);
  const full = Array.from({length:1000},(_,i) => place(`Place ${i}`));
  assert.throws(() => mergePlaces(full,[place("Overflow")]),/exceed/); assert.equal(full.length,1000);
  assert.throws(() => mergePlaces(existing,[place("Valid"),place("Invalid",91)])); assert.equal(existing.length,1);
});
test("collection JSON preserves full precision and rejects unrelated formats and oversized input", () => {
  const points = [place("=Original",1e-10,179.99999999,"Source & note")];
  assert.deepEqual(parsePlacesJSON(placesJSON(points)),points);
  for (const data of [{kind:"fieldforge-source-plan"},{kind:"fieldforge-place-collection",schema_version:2,places:points},{kind:"fieldforge-place-collection",schema_version:1,places:[]},{kind:"fieldforge-place-collection",schema_version:1,places:points,unknown:true}]) assert.throws(() => parsePlacesJSON(JSON.stringify(data)));
  assert.throws(() => parsePlacesJSON(" ".repeat(MAX_PLACE_BYTES+1)),/4 MiB/);
});
test("CSV handles BOM, reordered headers, escaped quotes, Unicode and empty lines", () => {
  const text = '\uFEFFsource,LONGITUDE,name,latitude\r\n"A, B",-75,"Camp ""East""",0\r\n\r\n';
  assert.deepEqual(parsePlacesCSV(text),[place('Camp "East"',0,-75,"A, B")]);
  const points = [place("خيمة",0,180),place("Café",-45.1234567,23)]; assert.deepEqual(parsePlacesCSV(placesCSV(points)),points);
  assert.match(parsePlacesCSV("name,latitude,longitude\nZero,0,0")[0].source,/unspecified/);
});
test("CSV rejects malformed quotes, extra columns, missing coordinates and invalid later rows", () => {
  const bad = ['name,latitude,longitude\na,0,','name,latitude,latitude\na,0,0','name,latitude,longitude,notes\na,0,0,x','name,latitude,longitude\n"a,0,0','name,latitude,longitude\n"a"x,0,0','name,latitude,longitude\na"b,0,0','name,latitude,longitude\na,0,0\nb,91,0','name,latitude,longitude\n"multi\nline",0,0','name,latitude,longitude\na,0'];
  for (const text of bad) assert.throws(() => parsePlacesCSV(text));
});
test("CSV protects formula-like names AND sources without exceeding desktop text limits", () => {
  const csv = placesCSV([place("=Name",0,-75,"@Source")]);
  assert.match(csv,/"'=Name","0","-75","'@Source"/);
  assert.throws(() => placesCSV([place("="+"a".repeat(159))]),/Shorten/);
  assert.throws(() => placesCSV([place("Name",0,0,"="+"a".repeat(511))]),/Shorten/);
});
test("GPX exports escaped waypoint-only XML, source descriptions and valid date-line values", () => {
  const xml = placesGPX([place('A & <"B">',0,180,'Source "note" & more'),place("Near date line",-90,179.99999999)]);
  assert.match(xml,/version="1.1" creator="FieldForge preparation desk"/); assert.match(xml,/xmlns="http:\/\/www.topografix.com\/GPX\/1\/1"/);
  assert.equal((xml.match(/lon="-180"/g)||[]).length,2); assert.match(xml,/<name>A &amp; &lt;&quot;B&quot;&gt;<\/name>/);
  assert.match(xml,/<desc>Source &quot;note&quot; &amp; more<\/desc>/); assert.ok(!xml.includes("<trk"));
  assert.throws(() => placesGPX([place("Same"),place("same",1)]),/distinct/);
  assert.throws(() => placesGPX(Array.from({length:201},(_,i) => place(String(i)))),/200/);
});
test("local search is literal, accent-insensitive and requires every word", () => {
  const points = [place("Café",0,0,"Field survey"),place("A.*B",0,0,"GPX"),place("خيمة",0,0,"من الملف")];
  assert.deepEqual(matchingPlaces(points,"cafe field"),[points[0]]); assert.deepEqual(matchingPlaces(points,".*"),[points[1]]); assert.deepEqual(matchingPlaces(points,"خيمة الملف"),[points[2]]);
  assert.deepEqual(matchingPlaces(points,"missing"),[]);
});
