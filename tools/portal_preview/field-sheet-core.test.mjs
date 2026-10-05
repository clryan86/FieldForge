import test from "node:test";
import assert from "node:assert/strict";
import {comparePlaces, distanceText, bearingText, captureFieldSheet, fieldSheetHTML, EARTH_RADIUS_M} from "./field-sheet-core.mjs";
const place = (name,lat = 0,lon = 0,source = "Test source") => ({name,lat,lon,source});
const close = (actual,expected,tolerance = 1e-7) => assert.ok(Math.abs(actual-expected)<tolerance,`${actual} ≈ ${expected}`);

test("spherical estimates give cardinal directions, symmetric distance and the short date-line crossing", () => {
  const origin = place("Origin");
  for (const [lat,lon,bearing] of [[1,0,0],[0,1,90],[-1,0,180],[0,-1,270]]) {
    const destination = place("Destination",lat,lon), leg = comparePlaces(origin,destination);
    close(leg.meters,Math.PI*EARTH_RADIUS_M/180); close(leg.bearing,bearing);
    close(comparePlaces(destination,origin).meters,leg.meters);
  }
  const leg = comparePlaces(place("West",0,179),place("East",0,-179));
  close(leg.meters,2*Math.PI*EARTH_RADIUS_M/180); close(leg.bearing,90);
  close(comparePlaces(leg.to,leg.from).bearing,270);
});
test("coincident, near-antipodal and polar starts suppress unstable bearings", () => {
  for (const [a,b,reason] of [[place("A"),place("B"),/close/],[place("A"),place("B",0,180),/antipodal/i],[place("A"),place("B",0,179.9999999),/antipodal/i],[place("A",90),place("B",0,30),/pole/],[place("A",-90),place("B",0,30),/pole/]]) {
    const leg = comparePlaces(a,b); assert.equal(leg.bearing,null); assert.match(leg.reason,reason); assert.ok(Number.isFinite(leg.meters));
  }
  assert.throws(() => comparePlaces(place("A",91),place("B")));
});
test("distance units and bearing display preserve small values and normalize rounded north", () => {
  assert.equal(distanceText(1609.344,"imperial"),"1.00 mi"); assert.equal(distanceText(.3048,"imperial"),"1 ft");
  assert.equal(distanceText(.01),"<1 m"); assert.equal(distanceText(0,"imperial"),"0 ft");
  assert.equal(distanceText(1000),"1.00 km"); assert.equal(bearingText({bearing:359.999}),"0.0° true");
  assert.equal(bearingText({bearing:90}),"90.0° true"); assert.equal(bearingText({bearing:270}),"270.0° true");
  assert.equal(bearingText({bearing:null}),"Unavailable"); assert.throws(() => distanceText(-1));
});
test("sheet capture freezes copies, checks endpoints and recomputes untrusted estimates", () => {
  const a = place("A"), b = place("B",0,1);
  const sheet = captureFieldSheet([a,b],{comparison:{from:a,to:b,meters:0,bearing:0}});
  close(sheet.comparison.bearing,90); assert.ok(sheet.comparison.meters>111000);
  a.name = "Edited"; b.lon = 4; assert.equal(sheet.points[0].name,"A"); assert.equal(sheet.comparison.to.lon,1);
  assert.throws(() => { sheet.points[0].name = "Mutation"; },TypeError);
  assert.throws(() => captureFieldSheet([a],{comparison:{from:a,to:b}}),/endpoints/);
});
test("sheet rejects empty, oversized or malformed captures without silently truncating", () => {
  for (const points of [[],Array.from({length:101},(_,i) => place(String(i)))]) assert.throws(() => captureFieldSheet(points),/1 to 100/);
  for (const title of [" ","x".repeat(101),"Bad\u202etitle","\ud800"]) assert.throws(() => captureFieldSheet([place("A")],{title}));
  assert.equal(captureFieldSheet([place("A")],{title:"خيمة 🧭"}).title,"خيمة 🧭");
  assert.throws(() => captureFieldSheet([place("A")],{createdAt:"2026-02-31T00:00:00.000Z"}),/time/);
  assert.throws(() => captureFieldSheet([place("A")],{units:"unknown"}));
});
test("printable HTML escapes every user field and actually omits optional sources and comparison", () => {
  const a = place('<img src=x onerror="alert(1)">',1.23456789,180,"PRIVATE_SOURCE"), b = place("Second",2,3,"Another note");
  const options = {title:'</title><script>alert("x")</script>',includeSources:false,comparison:{from:a,to:b}};
  const html = fieldSheetHTML(captureFieldSheet([a,b],options));
  assert.ok(!html.includes("PRIVATE_SOURCE")); assert.ok(!html.includes("Another note"));
  assert.ok(!/<(?:script|img|iframe|link)\b/i.test(html)); assert.ok(!/\b(?:src|href)="/i.test(html));
  assert.match(html,/&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/); assert.match(html,/&lt;\/title&gt;&lt;script&gt;/);
  assert.match(html,/1\.2345679/); assert.match(html,/script-src 'none'/); assert.match(html,/Initial true bearing/);
  assert.match(html,/no magnetic declination/); assert.match(html,/@media print/);
  const plain = fieldSheetHTML(captureFieldSheet([a])); assert.match(plain,/PRIVATE_SOURCE/); assert.ok(!plain.includes("Initial true bearing"));
});
