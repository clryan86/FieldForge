import test from "node:test";
import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import vm from "node:vm";
import {ADDRESS_MAX_BYTES, addressQuery, addressURL, parseAddressResults} from "./address-core.mjs";
import {createAddressService} from "./address-service.mjs";
import {createAddressSearch} from "./address-search.mjs";
import {placesJSON, parsePlacesJSON, placesCSV, parsePlacesCSV} from "./places-core.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const timestamp = "2026-10-05T23:00:00.000Z";
const fixture = (name = "Example town hall", coordinates = [-95.9896891234567, 36.1554223123456]) => ({type:"FeatureCollection", features:[{type:"Feature", properties:{name, street:"Main Street", housenumber:"12", city:"Example City", state:"Oklahoma", country:"United States", countrycode:"US", type:"house", osm_type:"N", osm_id:12345}, geometry:{type:"Point", coordinates}}]});
const response = (value = fixture(), init = {}) => new Response(JSON.stringify(value), {headers:{"content-type":"application/json"}, ...init});
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };

test("address query is explicit, bounded and encoded to a fixed provider with a U.S. scope", () => {
  const url = new URL(addressURL("  A & B / Hall ?  ", "US"));
  assert.equal(url.origin, "https://photon.komoot.io"); assert.equal(url.pathname, "/api/");
  assert.equal(url.searchParams.get("q"), "A & B / Hall ?");
  assert.equal(url.searchParams.get("countrycode"), "US"); assert.equal(url.searchParams.get("limit"), "5");
  assert.deepEqual([...url.searchParams.keys()].sort(), ["countrycode", "lang", "limit", "q"]);
  assert.equal(new URL(addressURL("Berlin", "world")).searchParams.has("countrycode"), false);
  for (const input of ["", "ab", "x".repeat(301), "City\nStreet", "City\u202eStreet", "\ud800xxx"]) assert.throws(() => addressQuery(input, "US"));
  assert.throws(() => addressQuery("Tulsa", "https://elsewhere.test"));
});

test("provider longitude/latitude order, full precision and source notes survive offline exchange", () => {
  const result = parseAddressResults(fixture("<img src=x onerror=alert(1)>\u202e"), timestamp)[0];
  assert.equal(result.point.lon, -95.9896891234567); assert.equal(result.point.lat, 36.1554223123456);
  assert.match(result.label, /<img src=x onerror=alert\(1\)>/); assert.doesNotMatch(result.label, /\u202e/);
  assert.match(result.point.source, /OpenStreetMap contributors \(ODbL\)/);
  assert.match(result.point.source, /OSM N\/12345/); assert.match(result.point.source, /retrieved 2026-10-05/);
  assert.deepEqual(parsePlacesJSON(placesJSON([result.point])), [result.point]);
  const csv = parsePlacesCSV(placesCSV([result.point]))[0];
  assert.equal(csv.lon, -95.9896891); assert.equal(csv.lat, 36.1554223); assert.equal(csv.source, result.point.source);
  for (const coordinates of [[90, 181], [181, 0], [0, 91], ["0", 0], [null, 1], [Infinity, 1], [1, 2, 3]]) assert.throws(() => parseAddressResults(fixture("bad", coordinates), timestamp));
  const mixed = fixture(); mixed.features.push({...mixed.features[0], geometry:{type:"LineString", coordinates:[[1, 2], [3, 4]]}});
  assert.throws(() => parseAddressResults(mixed, timestamp));
  assert.throws(() => parseAddressResults({features:Array(6).fill(fixture().features[0])}, timestamp));
});

test("service requires connection, has no startup requests, caches copies and limits new queries", async () => {
  let time = Date.parse(timestamp), calls = [];
  const service = createAddressService({now:() => time, fetchImpl:async (url, options) => { calls.push({url, options}); return response(); }});
  assert.equal(calls.length, 0); await assert.rejects(service.search("Example Hall", "US"), /Connect/);
  service.setConnected(true); assert.equal(calls.length, 0);
  const first = await service.search("Example Hall", "US");
  assert.equal(first.cached, false); assert.equal(calls.length, 1);
  assert.equal(calls[0].options.credentials, "omit"); assert.equal(calls[0].options.redirect, "error"); assert.equal(calls[0].options.referrerPolicy, "no-referrer");
  first.results[0].point.lat = 0;
  const cached = await service.search("Example Hall", "US");
  assert.equal(cached.cached, true); assert.equal(cached.results[0].point.lat, 36.1554223123456); assert.equal(calls.length, 1);
  await assert.rejects(service.search("Another Hall", "US"), /wait 2 seconds/);
  time += 2000; await service.search("Another Hall", "US"); assert.equal(calls.length, 2);
  service.clear(); await assert.rejects(service.search("Example Hall", "US"), /wait/);
  service.setConnected(false); await assert.rejects(service.search("Another Hall", "US"), /Connect/);
});

test("cancellation and deadlines discard late provider results without blocking another search", async () => {
  let time = Date.parse(timestamp), calls = 0, options, timeout;
  const pending = deferred();
  const service = createAddressService({now:() => time, fetchImpl:async (_, opts) => { calls++; options = opts; return calls === 1 ? pending.promise : response(fixture("New result")); }});
  service.setConnected(true); const old = service.search("Old query", "US");
  await assert.rejects(service.search("Concurrent query", "US"), /already running/);
  service.cancel(); assert.equal(options.signal.aborted, true); await assert.rejects(old, {name:"AbortError"});
  time += 2000; const next = await service.search("New query", "US"); assert.match(next.results[0].label, /New result/);
  pending.resolve(response(fixture("Old result"))); await Promise.resolve();
  const stuck = createAddressService({fetchImpl:() => new Promise(() => {}), schedule:fn => { timeout = fn; return 1; }, unschedule() {}});
  stuck.setConnected(true); const waiting = stuck.search("Stuck query", "US"); timeout();
  await assert.rejects(waiting, /timed out/);
});

test("service bounds streaming responses and rejects malformed content atomically", async () => {
  const checks = [
    () => new Response("not json", {headers:{"content-type":"text/html"}}),
    () => new Response("{}", {headers:{"content-type":"application/json", "content-length":String(ADDRESS_MAX_BYTES + 1)}}),
    () => new Response(new Uint8Array(ADDRESS_MAX_BYTES + 1), {headers:{"content-type":"application/json"}}),
    () => new Response(new Uint8Array([0xc3, 0x28]), {headers:{"content-type":"application/json"}}),
    () => new Response("{", {headers:{"content-type":"application/json"}}),
    () => response({features:[{geometry:{type:"Point", coordinates:[1, 2]}}]}),
  ];
  for (const make of checks) {
    let signal;
    const service = createAddressService({fetchImpl:async (_, options) => { signal = options.signal; return make(); }}); service.setConnected(true);
    await assert.rejects(service.search("Example Hall", "US"));
    assert.equal(signal.aborted, true, "Rejected responses must stop the underlying fetch, including preflight failures");
  }
});

test("provider throttling and hourly caps stop requests without retries or a fallback", async () => {
  let time = Date.parse(timestamp), calls = 0;
  const service = createAddressService({now:() => time, fetchImpl:async () => { calls++; return response({}, {status:429, headers:{"retry-after":"120"}}); }});
  service.setConnected(true); await assert.rejects(service.search("Example Hall", "US"), /limiting requests/);
  service.setConnected(false); service.clear(); service.setConnected(true); time += 2000;
  await assert.rejects(service.search("Different Hall", "US"), /wait 118 seconds/); assert.equal(calls, 1);
  let cappedCalls = 0;
  const capped = createAddressService({now:() => time, fetchImpl:async () => { cappedCalls++; return response(); }}); capped.setConnected(true);
  for (let i = 0; i < 30; i++) { await capped.search(`Hall ${i}`, "US"); time += 2000; }
  await assert.rejects(capped.search("Hall 31", "US"), /hourly preview limit/); assert.equal(cappedCalls, 30);
});

class Element {
  constructor(tag = "div") { this.tag = tag; this.handlers = new Map(); this.children = []; this.attrs = {}; this.value = ""; this.checked = false; this.disabled = false; this.classList = {toggle() {}, add() {}, remove() {}}; this._text = ""; }
  set innerHTML(_) { throw Error("Provider markup must never be parsed"); }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  append(...nodes) { for (const node of nodes) this.children.push(...(node.tag === "fragment" ? node.children : [node])); }
  replaceChildren(...nodes) { this.children = []; this._text = ""; this.append(...nodes); }
  addEventListener(type, handler) { const rows = this.handlers.get(type) || []; rows.push(handler); this.handlers.set(type, rows); }
  fire(type) { const values = (this.handlers.get(type) || []).map(handler => handler({type, preventDefault() {}})); return Promise.all(values); }
  click() { if (!this.disabled) return this.fire("click"); }
  focus() {} scrollIntoView() {}
}

const previewScript = execFileSync(process.env.FIELDFORGE_TEST_PYTHON || "python", ["-c", "from build_hosted_preview import SCRIPT; print(SCRIPT)"], {cwd:root, encoding:"utf8"});
function bootUI(fetchImpl) {
  const elements = new Map();
  for (const match of readFileSync(new URL("./address-search.html", import.meta.url), "utf8").matchAll(/id="([^"]+)"/g)) elements.set(match[1], new Element());
  for (const key of ["connect", "disconnect", "connectionBadge", "addressTab", "previewSkills", "regionalFilter", "openAddressSearch", "openAddressControls"]) elements.set(key, new Element());
  const id = key => elements.get(key) || null;
  id("addressScope").value = "US";
  const doc = new Element(), win = new Element(), nav = {onLine:true}, saved = [];
  let confirmation = false, time = Date.parse(timestamp), calls = 0;
  doc.documentElement = {dataset:{}}; doc.getElementById = id; doc.createElement = tag => new Element(tag); doc.createDocumentFragment = () => new Element("fragment"); doc.querySelectorAll = () => [];
  doc.dispatchEvent = event => { doc.fire(event.type); return true; };
  win.confirm = () => confirmation;
  vm.runInNewContext(previewScript, {document:doc, window:win, navigator:nav, Event});
  const service = createAddressService({now:() => time, fetchImpl:async (...args) => { calls++; return fetchImpl(...args); }});
  createAddressSearch({document:doc, window:win, navigator:nav, service, onAdd:point => { saved.push(point); return "Place added."; }, onShow() {}});
  return {id, doc, win, nav, saved, get calls() { return calls; }, advance() { time += 2000; }, confirm(value) { confirmation = value; }};
}

test("actual portal connection script requires consent and confirmation; results render as text and remain saveable after disconnect", async () => {
  const app = bootUI(async () => response(fixture("<script>alert(1)</script>")));
  assert.equal(app.id("addressQuery").disabled, true); assert.equal(app.calls, 0);
  await app.id("addressEnable").click(); assert.equal(app.id("addressQuery").disabled, true);
  app.id("consent").checked = true; await app.id("addressEnable").click(); assert.equal(app.id("addressQuery").disabled, true);
  app.confirm(true); await app.id("addressEnable").click(); assert.equal(app.id("addressQuery").disabled, false); assert.equal(app.calls, 0);
  app.id("addressQuery").value = "Example Hall"; await app.id("addressQuery").fire("input"); assert.equal(app.calls, 0);
  await app.id("addressSearchForm").fire("submit"); assert.equal(app.calls, 1);
  assert.match(app.id("addressResults").textContent, /<script>alert\(1\)<\/script>/);
  await app.id("addressPause").click(); assert.equal(app.id("addressQuery").disabled, true);
  await app.id("addressResults").children[0].children[1].click(); assert.equal(app.saved.length, 1);
  assert.equal(app.saved[0].lat, 36.1554223123456); assert.match(app.saved[0].source, /Photon \/ Komoot/);
  await app.id("addressClear").click(); assert.equal(app.id("addressResults").children.length, 0); assert.equal(app.saved.length, 1);
});

test("UI drops stale searches on edit, consent revocation and offline events; reconnection never auto-searches", async () => {
  const pending = deferred(); let signal;
  const app = bootUI(async (_, options) => { signal = options.signal; return pending.promise; });
  app.id("consent").checked = true; app.confirm(true); await app.id("addressEnable").click();
  app.id("addressQuery").value = "Old address"; const work = app.id("addressSearchForm").fire("submit");
  app.id("addressQuery").value = "New address"; await app.id("addressQuery").fire("input");
  assert.equal(signal.aborted, true); pending.resolve(response(fixture("Late result"))); await work;
  assert.equal(app.id("addressResults").children.length, 0); assert.match(app.id("addressStatus").textContent, /Search changed/);
  app.id("consent").checked = false; await app.id("consent").fire("change"); assert.equal(app.id("addressQuery").disabled, true);
  app.id("consent").checked = true; await app.id("addressEnable").click();
  app.nav.onLine = false; await app.win.fire("offline"); assert.equal(app.id("addressQuery").disabled, true);
  assert.equal(app.id("addressConnectionState").textContent, "Device offline");
  app.nav.onLine = true; await app.win.fire("online"); assert.equal(app.id("addressQuery").disabled, true); assert.equal(app.calls, 1);
});
