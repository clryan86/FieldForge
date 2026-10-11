import test from "node:test";
import assert from "node:assert/strict";
import {downloadEstimate, validatePlan, coordinate, analyzeGeometry, projectTrace, waypointCSV, parseGPX, MAX_GPX_BYTES, PLAN_KIND, readElevation, elevationProfile, projectElevation, nearestDistanceSample, nearestPlotSample, clampView} from "./desk-core.mjs";

test("download estimates use decimal GB/Mbps and report an exceeded budget", () => {
  const estimate = downloadEstimate(1e9, 0.5, 10);
  assert.equal(estimate.seconds, 800); assert.equal(estimate.remainingBytes, -5e8); assert.equal(estimate.overBudget, true);
  for (const input of [0, -1, Infinity, NaN, 1001]) assert.throws(() => downloadEstimate(1, input, 10));
  assert.throws(() => downloadEstimate(-1, 1, 10)); assert.throws(() => downloadEstimate(100, 1, 0));
});
test("saved plans accept only known regions and finite settings", () => {
  const original = {kind:PLAN_KIND, schema_version:1, region_ids:["alaska"], budget_gb:4, speed_mbps:10};
  const known = new Set(["alaska", "kansas"]), result = validatePlan(original, known);
  assert.deepEqual(result, original); result.region_ids.push("kansas"); assert.equal(original.region_ids.length, 1);
  for (const edit of [{kind:"map-download-list"}, {region_ids:["unknown"]}, {region_ids:["alaska", "alaska"]}, {speed_mbps:"10"}, {budget_gb:Infinity}]) assert.throws(() => validatePlan({...original, ...edit}, known));
});
test("coordinate validation accepts zero and edges but rejects blanks and expressions", () => {
  assert.equal(coordinate("0", 90), 0); assert.equal(coordinate(" -180 ", 180), -180); assert.equal(coordinate("+.5", 90), .5);
  for (const input of ["", " ", "NaN", "Infinity", "1e2", "40 N", "91", null, "2+2"]) assert.throws(() => coordinate(input, 90));
});
test("separate track segments do not acquire a fictitious connecting distance", () => {
  const data = analyzeGeometry({segments:[[{lat:0,lon:0},{lat:0,lon:1}],[{lat:45,lon:100},{lat:45,lon:100}]], waypoints:[]});
  assert.ok(Math.abs(data.meters - 111195.08) < 1); assert.equal(data.geometryPoints, 4);
  const projected = projectTrace(data); assert.equal(projected.parts.length, 2);
  for (const part of projected.parts) for (const [x, y] of part) assert.ok(x >= 49.99 && x <= 750.01 && y >= 54.99 && y <= 325.01);
});
test("date-line crossing follows the short geographic distance", () => {
  const data = analyzeGeometry({segments:[[{lat:0,lon:179},{lat:0,lon:-179}]], waypoints:[]});
  assert.ok(data.meters > 222000 && data.meters < 223000);
  const {parts} = projectTrace(data); assert.ok(parts[0][1][0] > parts[0][0][0]);
});
test("single waypoint and polar coordinates still make finite plots", () => {
  const single = analyzeGeometry({segments:[], waypoints:[{lat:90,lon:180,name:"Pole"}]});
  assert.deepEqual(projectTrace(single).places, [[400,190]]); assert.equal(single.meters, 0);
  assert.throws(() => analyzeGeometry({segments:[[{lat:91,lon:0}]], waypoints:[]}));
});
test("waypoint CSV preserves zero, quotes, decimal coordinates and neutralizes formulas", () => {
  const csv = waypointCSV([{lat:0,lon:0,name:'=HYPERLINK("x")'},{lat:-4.123456789,lon:180,name:"Line\nname"}]);
  assert.ok(csv.startsWith("name,latitude,longitude,source\r\n"));
  assert.ok(csv.includes('"\'=HYPERLINK(""x"")","0","0"')); assert.ok(csv.includes('"Line name","-4.1234568","180"'));
  assert.throws(() => waypointCSV([]));
});
test("GPX rejects document types, entities and oversized input before parsing", () => {
  class NeverParse { constructor() { throw new Error("Parser should not be constructed"); } }
  assert.throws(() => parseGPX('<!DOCTYPE gpx><gpx/>', NeverParse), /document types/);
  assert.throws(() => parseGPX('<!ENTITY x "secret"><gpx/>', NeverParse), /entity/);
  assert.throws(() => parseGPX("x".repeat(MAX_GPX_BYTES + 1), NeverParse), /2 MiB/);
});
// The injected XML DOM fixture verifies traversal independent of browser APIs.
// Browser DOMParser performs XML syntax parsing at runtime.
const NS = "http://www.topografix.com/GPX/1/1";
function element(localName, attributes = {}, children = [], textContent = "", namespaceURI = NS) { return {localName, namespaceURI, children, textContent, getAttribute:key => attributes[key] ?? null}; }
function parserFor(root, error = false) { return class { parseFromString() { return {documentElement:root, getElementsByTagName:() => error ? [{}] : []}; } }; }
test("GPX traversal preserves separate tracks, explicit waypoints and namespaces", () => {
  const point = (name, lat, lon) => element(name, {lat,lon});
  const root = element("gpx", {}, [element("wpt", {lat:"0",lon:"0"}, [element("name", {}, [], "Start")]),element("trk", {}, [element("trkseg", {}, [point("trkpt","0","179"), point("trkpt","0","-179")]), element("trkseg", {}, [point("trkpt","40","-75")])]),element("wpt", {lat:"not a coordinate",lon:"0"}, [], "", "urn:untrusted-extension")]);
  const data = parseGPX("<gpx/>", parserFor(root));
  assert.equal(data.segments.length, 2); assert.equal(data.waypoints.length, 1); assert.equal(data.waypoints[0].name, "Start"); assert.ok(data.meters < 223000);
  assert.throws(() => parseGPX("<gpx/>", parserFor(root, true)), /valid GPX XML/);
  assert.throws(() => parseGPX("<gpx/>", parserFor(element("gpx", {}, [], "", "urn:unsupported"))), /namespace/);
});
test("GPX rejects empty documents, invalid coordinates and point-count excess", () => {
  assert.throws(() => parseGPX("<gpx/>", parserFor(element("gpx"))), /No waypoints/);
  const bad = element("gpx", {}, [element("wpt", {lat:"",lon:"0"})]);
  assert.throws(() => parseGPX("<gpx/>", parserFor(bad)), /invalid coordinate/);
  const many = element("gpx", {}, [element("rte", {}, Array.from({length:25001}, () => element("rtept", {lat:"0",lon:"0"})))]);
  assert.throws(() => parseGPX("<gpx/>", parserFor(many)), /25,000/);
});

test("optional elevation retains real zero and rejects absent or malformed heights", () => {
  assert.equal(readElevation("0"), 0); assert.equal(readElevation(" -430.5 "), -430.5);
  for (const raw of [null, "", " ", "NaN", "1e2", "1000001", "10 m"]) assert.equal(readElevation(raw), null);
  const root = element("gpx", {}, [element("rte", {}, [element("rtept", {lat:"0",lon:"0"}, [element("ele", {}, [], "0")]),element("rtept", {lat:"0",lon:"1"}, [element("ele", {}, [], "bad")]),element("rtept", {lat:"0",lon:"2"})])]);
  const points = parseGPX("<gpx/>", parserFor(root)).segments[0];
  assert.equal(points[0].ele, 0); assert.equal(points[0].invalidElevation, false);
  assert.equal(points[1].ele, null); assert.equal(points[1].invalidElevation, true);
  assert.equal(points[2].ele, null); assert.equal(points[2].invalidElevation, false);
});

test("elevation changes never bridge missing values or separate track segments", () => {
  const p = (lon,ele) => ({lat:0,lon,ele});
  const data = analyzeGeometry({segments:[[p(0,100),p(.01,120),p(.02,null),p(.03,1000),p(.04,990)],[p(40,5000),p(40.01,5005)]],waypoints:[]});
  const profile = elevationProfile(data);
  assert.equal(profile.ascent,25); assert.equal(profile.descent,10); assert.equal(profile.knownPairs,3);
  assert.deepEqual(profile.runs.map(run => run.length),[2,2,2]); assert.equal(profile.validCount,6);
  assert.ok(Math.abs(profile.meters-data.meters)<1e-7); assert.ok(profile.knownMeters<profile.meters);
  assert.equal(profile.samples[5].distance,profile.samples[4].distance); // No gap distance.
  assert.equal(profile.samples[5].segmentIndex,1);
  for (const run of projectElevation(profile)) for (const sample of run) assert.ok(sample.x>=50 && sample.x<=750 && sample.y>=25 && sample.y<=165);
});

test("flat elevations and stationary routes produce finite profiles", () => {
  const profile = elevationProfile({segments:[[{lat:0,lon:0,ele:0},{lat:0,lon:0,ele:0}]],waypoints:[]});
  assert.equal(profile.min,0); assert.equal(profile.max,0); assert.equal(profile.knownPairs,1);
  assert.deepEqual(projectElevation(profile)[0].map(p => [p.x,p.y]),[[400,95],[400,95]]);
  const changing = elevationProfile({segments:[[{lat:0,lon:0,ele:10},{lat:0,lon:0,ele:20}]],waypoints:[]});
  assert.equal(changing.ascent,10); assert.equal(changing.knownMeters,0); assert.equal(changing.knownPairs,1);
});

test("all missing heights and isolated valid points do not create ascent", () => {
  const p = ele => ({lat:0,lon:0,ele});
  const empty = elevationProfile({segments:[[p(null),p(null)]],waypoints:[]});
  assert.equal(empty.min,null); assert.equal(empty.max,null); assert.deepEqual(projectElevation(empty),[]);
  const sparse = elevationProfile({segments:[[p(0),p(null),p(100)]],waypoints:[]});
  assert.equal(sparse.knownPairs,0); assert.equal(sparse.ascent,0); assert.equal(sparse.runs.length,2);
});

test("profile selection clamps endpoints and handles repeated segment distances", () => {
  const samples=[{distance:0},{distance:10},{distance:10},{distance:30}];
  assert.equal(nearestDistanceSample(samples,-10),0); assert.equal(nearestDistanceSample(samples,100),3);
  assert.equal(nearestDistanceSample(samples,10),1); assert.equal(nearestDistanceSample(samples,28),3);
  assert.equal(nearestDistanceSample([],10),-1); assert.equal(nearestDistanceSample(samples,NaN),-1);
});

test("zoom and pan remain bounded, including malformed view values", () => {
  assert.deepEqual(clampView(1,0,0).box,[0,0,800,380]);
  const zoom = clampView(50,-1e6,1e6);
  assert.equal(zoom.zoom,8); assert.equal(zoom.box[0],0); assert.equal(zoom.box[1]+zoom.height,380);
  assert.deepEqual(clampView(NaN,NaN,NaN).box,[0,0,800,380]);
  for (const z of [1,1.5,2.25,8]) for (const x of [-100,0,400,800,900]) { const view=clampView(z,x,x); assert.ok(view.box.every(Number.isFinite)); assert.ok(view.box[0]>=0 && view.box[1]>=0 && view.box[0]+view.width<=800 && view.box[1]+view.height<=380); }
});

test("profile clicks distinguish heights at the same route distance", () => {
  const points=[{x:400,y:25,index:3},{x:400,y:165,index:5}];
  assert.equal(nearestPlotSample(points,402,164,18),5);
  assert.equal(nearestPlotSample(points,398,26,18),3);
  assert.equal(nearestPlotSample(points,100,100,18),-1);
  assert.equal(nearestPlotSample(points,NaN,100,18),-1);
});
