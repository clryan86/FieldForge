import test, {after} from "node:test";
import assert from "node:assert/strict";
import {readFileSync, mkdtempSync, rmSync, existsSync} from "node:fs";
import {tmpdir} from "node:os";
import {join, resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {execFileSync} from "node:child_process";
import vm from "node:vm";

// Execute the actual downloadable script with a DOM double and forbidden network
// and storage APIs. This is an integration check, not native browser/device QA.
const root = fileURLToPath(new URL("../",import.meta.url));
const output = mkdtempSync(join(tmpdir(),"fieldforge-offline-test-"));
after(() => rmSync(output,{recursive:true,force:true}));
const repositoryPortal = resolve(root,"../fieldforge/online/portal.html");
const portal = existsSync(repositoryPortal) ? repositoryPortal : resolve(root,"snapshot/fieldforge/online/portal.html");
execFileSync(process.env.FIELDFORGE_TEST_PYTHON || "python",["-c", "from pathlib import Path; import sys; from build_offline_desk import export_offline; from build_hosted_preview import FAVICON; export_offline(Path('portal_preview'), Path(sys.argv[2]), Path(sys.argv[1]).read_text(), '0' * 40, FAVICON)",portal,output],{cwd:root});
const source = readFileSync(join(output,"fieldforge-offline.html"),"utf8");
const script = source.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element {
  constructor(tag, attrs = {}) {
    this.tag = tag; this.attrs = {...attrs}; this.children = []; this.handlers = new Map(); this.dataset = {};
    this.value = attrs.value || ""; this.checked = "checked" in attrs; this.disabled = "disabled" in attrs; this.hidden = "hidden" in attrs;
    this.classList = {toggle() {},add() {},remove() {}}; this._text = "";
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  append(...items) { for (const item of items) { if (item.tag === "#fragment") this.children.push(...item.children); else this.children.push(item); } }
  replaceChildren(...items) { this.children = []; this._text = ""; this.append(...items); }
  setAttribute(key,value) { this.attrs[key] = String(value); }
  removeAttribute(key) { delete this.attrs[key]; if (key === "href") delete this.href; }
  addEventListener(type,listener) { this.handlers.set(type,listener); }
  fire(type) { return this.handlers.get(type)?.({preventDefault() {}}); }
  querySelector(tag) { return this.children.find(child => child.tag === tag); }
  scrollIntoView() {} focus() {} remove() {} reset() {} click() { this.onClick?.(); }
  getBoundingClientRect() { return {width:800,height:500,left:0,top:0}; }
  getContext() { return {setTransform() {},clearRect() {}}; }
}
function boot() {
  const elements = new Map(), opened = [], blobs = [], downloads = [];
  let storageTouches = 0, requests = 0, confirmation = false;
  for (const match of source.matchAll(/<([a-zA-Z][\w-]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const attrs = Object.fromEntries([...match[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)].map(([_,key,value]) => [key,value ?? ""]));
    elements.set(match[3],new Element(match[1],attrs));
  }
  const id = key => { assert.ok(elements.has(key),`Missing DOM id ${key}`); return elements.get(key); };
  id("placesForm").reset = () => { for (const key of ["placesName","placesLatitude","placesLongitude","placesSource"]) id(key).value = ""; };
  const rows = [...source.matchAll(/<li><a data-source-url="([^"]+)"[^>]*>([^<]+)<\/a>\s*<span[^>]*>\(~([\d.]+) (GB|MB)\)<\/span><\/li>/g)].map(([,url,name,size,unit]) => {
    const row = new Element("li"),link = new Element("a"); link.dataset.sourceUrl = url; link.textContent = name;
    row._text = `(~${size} ${unit})`; row.append(link); return row;
  });
  const createElement = tag => { const element = new Element(tag); element.onClick = () => { if (element.download) downloads.push({name:element.download,href:element.href}); }; return element; };
  const document = {getElementById:id,documentElement:{dataset:{edition:"offline",sourcesEnabled:"false"}},body:new Element("body"),createElement,createElementNS:(_,tag) => createElement(tag),createDocumentFragment:() => new Element("#fragment"),querySelectorAll:query => { assert.equal(query,"#usSourceLinks li"); return rows; }};
  class LocalURL extends URL { static createObjectURL(blob) { blobs.push(blob); return `blob:local-${blobs.length}`; } static revokeObjectURL() {} }
  const forbidden = () => { requests++; throw Error("Network access is forbidden"); };
  const sandbox = {document,window:{devicePixelRatio:1,addEventListener() {},confirm:() => confirmation,open:(...args) => opened.push(args)},URL:LocalURL,Blob,TextEncoder,TextDecoder,setTimeout() {},fetch:forbidden,XMLHttpRequest:forbidden,WebSocket:forbidden,navigator:{sendBeacon:forbidden}};
  Object.defineProperty(sandbox,"localStorage",{get() { storageTouches++; throw Error("Storage unavailable for local file"); }});
  vm.runInNewContext(script,sandbox,{timeout:1000,filename:"fieldforge-offline.html"});
  return {id,opened,blobs,downloads,get storageTouches() { return storageTouches; },get requests() { return requests; },confirm:choice => { confirmation = choice; }};
}

test("downloaded desk boots without storage or network and can save/reopen a source plan", async () => {
  const app = boot(); assert.match(app.id("offlineReady").textContent,/Ready on this device/);
  assert.equal(app.id("offlineTools").disabled,false); assert.equal(app.id("deskRegions").children.length,53);
  assert.equal(app.storageTouches,0); assert.equal(app.requests,0); assert.deepEqual(app.opened,[]);
  const alaska = app.id("deskRegions").children[1]; assert.equal(alaska.children[1].href,"#offlineConnection");
  const check = alaska.children[0].children[0]; check.checked = true; check.fire("change");
  assert.equal(app.id("deskSave").disabled,false); app.id("deskSave").fire("click");
  const saved = JSON.parse(await app.blobs[0].text()); assert.deepEqual(saved.region_ids,["alaska"]); assert.equal(saved.kind,"fieldforge-source-plan");
  assert.equal(app.downloads[0].name,"fieldforge-source-plan.json");
  app.id("deskClear").fire("click"); assert.equal(app.id("deskSave").disabled,true);
  app.id("deskPlanFile").files = [{size:200,text:async () => JSON.stringify(saved)}]; await app.id("deskPlanFile").fire("change");
  assert.equal(app.id("deskRegions").children[1].children[0].children[0].checked,true);
  assert.match(app.id("deskPlanStatus").textContent,/restored/);
  app.id("traceTab").fire("click"); assert.equal(app.id("tracePanel").hidden,false); assert.equal(app.id("packPanel").hidden,true);
  app.id("imageTab").fire("click"); assert.equal(app.id("imagePanel").hidden,false); assert.equal(app.id("tracePanel").hidden,true);
  assert.equal(app.storageTouches,0); assert.equal(app.requests,0);
});

test("opening the portal requires confirmation and uses a fixed URL without local data", () => {
  const app = boot(); app.id("offlineOpenPortal").fire("click");
  assert.deepEqual(app.opened,[]); assert.match(app.id("offlineConnectionStatus").textContent,/Cancelled/);
  assert.equal(app.id("offlinePortalFallback").hidden,true); assert.equal(app.id("offlinePortalLink").href,undefined);
  app.confirm(true); app.id("offlineOpenPortal").fire("click");
  assert.deepEqual(app.opened,[["https://fieldforge-portal.chris1986ryan.chatgpt.site","_blank","noopener,noreferrer"]]);
  assert.equal(app.id("offlinePortalLink").href,app.opened[0][0]); assert.equal(app.id("offlinePortalFallback").hidden,false);
  app.confirm(false); app.id("offlineOpenPortal").fire("click"); assert.equal(app.opened.length,1); assert.equal(app.id("offlinePortalLink").href,undefined);
  assert.equal(app.requests,0); assert.equal(app.storageTouches,0);
});

function addManual(app,name,lat = "0",lon = "0",source = "") {
  for (const [key,value] of Object.entries({placesName:name,placesLatitude:lat,placesLongitude:lon,placesSource:source})) app.id(key).value = value;
  app.id("placesForm").fire("submit");
}
function collectionFile(name,text) { const bytes = new TextEncoder().encode(text); return {name,size:bytes.length,arrayBuffer:async () => bytes.buffer}; }
test("offline field sheets include all filtered matches, selected estimates and chosen source notes", async () => {
  const app = boot();
  addManual(app,"Camp west","0","179","PRIVATE_WEST"); addManual(app,"Camp east","0","-179","PRIVATE_EAST"); addManual(app,"Excluded site","1","2");
  app.id("placesSearch").value = "Camp"; app.id("placesSearch").fire("input");
  assert.equal(app.id("sheetFrom").children.length,3);
  app.id("sheetFrom").value = "0"; app.id("sheetFrom").fire("change"); app.id("sheetTo").value = "1"; app.id("sheetTo").fire("change");
  app.id("sheetCalculate").fire("click"); assert.match(app.id("sheetComparison").textContent,/90\.0° true/);
  app.id("sheetUnits").value = "imperial"; app.id("sheetUnits").fire("change"); assert.match(app.id("sheetComparison").textContent,/138\.19 mi/);
  app.id("sheetIncludeComparison").checked = true; app.id("sheetIncludeComparison").fire("change");
  app.id("sheetSources").checked = false; app.id("sheetSources").fire("change");
  app.id("sheetPrepare").fire("click"); assert.equal(app.id("sheetDownload").disabled,false);
  assert.ok(!app.id("sheetPreview").textContent.includes("PRIVATE_")); assert.ok(!app.id("sheetPreview").textContent.includes("Excluded"));
  app.id("sheetDownload").fire("click"); const html = await app.blobs.at(-1).text();
  assert.equal(app.downloads.at(-1).name,"fieldforge-place-sheet.html"); assert.match(html,/2 places/); assert.match(html,/138\.19 mi/);
  assert.ok(!html.includes("PRIVATE_")); assert.ok(!html.includes("Excluded"));
  app.id("sheetSwap").fire("click"); assert.equal(app.id("sheetDownload").disabled,true); assert.equal(app.id("sheetPreview").hidden,true);
  app.id("sheetCalculate").fire("click"); assert.match(app.id("sheetComparison").textContent,/270\.0° true/);
  assert.equal(app.storageTouches,0); assert.equal(app.requests,0); assert.deepEqual(app.opened,[]);
});
test("prepared sheets survive pagination but are cleared after edits, options or changed matches", async () => {
  const app = boot(), places = Array.from({length:101},(_,i) => ({name:`Point ${i}`,lat:0,lon:i,source:"Test fixture"}));
  app.id("placesFile").files = [collectionFile("places.json",JSON.stringify({kind:"fieldforge-place-collection",schema_version:1,places}))];
  await app.id("placesFile").fire("change"); assert.equal(app.id("sheetPrepare").disabled,true); assert.match(app.id("sheetScope").textContent,/101 matches/);
  app.id("placesRows").children[0].children[3].children[1].fire("click"); assert.equal(app.id("sheetPrepare").disabled,false);
  app.id("sheetPrepare").fire("click"); assert.match(app.id("sheetStatus").textContent,/100 matching/);
  app.id("placesNext").fire("click"); assert.equal(app.id("sheetDownload").disabled,false);
  app.id("sheetDownload").fire("click"); const html = await app.blobs.at(-1).text(); assert.equal((html.match(/<article>/g)||[]).length,100);
  const invalidates = action => { app.id("sheetPrepare").fire("click"); assert.equal(app.id("sheetDownload").disabled,false); action(); assert.equal(app.id("sheetDownload").disabled,true); assert.equal(app.id("sheetPreview").textContent,""); const count = app.blobs.length; app.id("sheetDownload").fire("click"); assert.equal(app.blobs.length,count); };
  invalidates(() => { app.id("sheetTitle").value = "Updated title"; app.id("sheetTitle").fire("input"); });
  invalidates(() => { app.id("sheetSources").checked = false; app.id("sheetSources").fire("change"); });
  invalidates(() => { app.id("placesRows").children[0].children[3].children[0].fire("click"); app.id("placesLatitude").value = "5"; app.id("placesForm").fire("submit"); });
  invalidates(() => { app.id("placesSearch").value = "Point 99"; app.id("placesSearch").fire("input"); });
  app.id("sheetPrepare").fire("click"); assert.match(app.id("sheetStatus").textContent,/1 matching/);
  app.confirm(true); app.id("placesClear").fire("click"); assert.equal(app.id("sheetDownload").disabled,true); assert.equal(app.id("sheetPrepare").disabled,true);
  assert.equal(app.storageTouches,0); assert.equal(app.requests,0);
});
test("offline places support edit, removal undo, filtered export and full-collection backup", async () => {
  const app = boot(); app.id("placesTab").fire("click"); assert.equal(app.id("placesPanel").hidden,false);
  addManual(app,"Café","0","180","Field notes"); addManual(app,"Other","1","2","GPX");
  assert.match(app.id("placesCount").textContent,/2 matching \/ 2 total/);
  app.id("placesRows").children[0].children[3].children[0].fire("click");
  app.id("placesName").value = "Café renamed"; app.id("placesForm").fire("submit");
  assert.match(app.id("placesRows").textContent,/Café renamed/);
  app.id("placesRows").children[0].children[3].children[1].fire("click"); assert.match(app.id("placesCount").textContent,/1 total/);
  app.id("placesUndo").fire("click"); assert.match(app.id("placesRows").textContent,/Café renamed/);
  app.id("placesSearch").value = "cafe"; app.id("placesSearch").fire("input");
  app.id("placesSaveCSV").fire("click"); const csv = await app.blobs.at(-1).text(); assert.ok(csv.includes("Café renamed")); assert.ok(!csv.includes("Other"));
  app.id("placesSaveGPX").fire("click"); assert.match(await app.blobs.at(-1).text(),/lon="-180"/);
  app.id("placesSaveJSON").fire("click"); const saved = await app.blobs.at(-1).text(); assert.equal(JSON.parse(saved).places.length,2);
  app.confirm(true); app.id("placesClear").fire("click"); assert.equal(app.id("placesUndo").disabled,true); assert.equal(app.id("placesSaveJSON").disabled,true);
  app.id("placesFile").files = [collectionFile("collection.json",saved)]; await app.id("placesFile").fire("change"); assert.match(app.id("placesCount").textContent,/2 total/);
  app.id("placesFile").files = [collectionFile("collection.json",saved)]; await app.id("placesFile").fire("change"); assert.match(app.id("placesStatus").textContent,/0 added; 2 exact duplicates/);
  assert.equal(app.storageTouches,0); assert.equal(app.requests,0);
});
test("offline places reject a whole invalid import and discard reads after cancellation or edits", async () => {
  const app = boot(); addManual(app,"Existing");
  app.id("placesFile").files = [collectionFile("bad.csv","name,latitude,longitude\nGood,1,2\nBad,91,2")]; await app.id("placesFile").fire("change");
  assert.match(app.id("placesStatus").textContent,/Existing places were kept/); assert.match(app.id("placesCount").textContent,/1 total/);
  const delayed = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise,resolve}; };
  const bytes = new TextEncoder().encode("name,latitude,longitude\nLate,1,2").buffer;
  for (const action of [() => app.id("placesCancelRead").fire("click"),() => addManual(app,"New during read")]) {
    const job = delayed(); app.id("placesFile").files = [{name:"slow.csv",size:100,arrayBuffer:() => job.promise}];
    const reading = app.id("placesFile").fire("change"); action(); job.resolve(bytes); await reading;
    assert.ok(!app.id("placesRows").textContent.includes("Late"));
  }
  assert.match(app.id("placesCount").textContent,/2 total/); assert.equal(app.id("placesCancelRead").disabled,true);
  assert.equal(app.storageTouches,0); assert.equal(app.requests,0);
});
