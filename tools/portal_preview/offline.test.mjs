import test, {after} from "node:test";
import assert from "node:assert/strict";
import {readFileSync, mkdtempSync, rmSync, existsSync} from "node:fs";
import {tmpdir} from "node:os";
import {join, resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {execFileSync} from "node:child_process";
import {webcrypto} from "node:crypto";
import vm from "node:vm";
import {imageHeader} from "./image-core.mjs";

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
function boot({mbtiles=false,gpxParser=null}={}) {
  const elements = new Map(), opened = [], blobs = [], downloads = [], workers=[], bitmaps=[], draws=[], markers=[], overlays=[];
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
  if(gpxParser)sandbox.DOMParser=gpxParser;
  if(mbtiles) {
    id("mbWorkerPayload").textContent=source.match(/<div id="mbWorkerPayload" hidden>([A-Za-z0-9+/=]+)<\/div>/)[1];
    id("mbCanvas").getContext=()=>({clearRect(){draws.length=0;markers.length=0;overlays.length=0;},fillRect(){},strokeRect(){},fillText(){},drawImage(bitmap){draws.push(bitmap);},beginPath(){this.path=[];},arc(){},moveTo(x,y){this.lastMove=[x,y];this.path.push(["move",x,y]);},lineTo(x,y){this.path.push(["line",x,y]);},stroke(){if(this.strokeStyle==="#7fe3ff")markers.push(this.lastMove);if(this.strokeStyle==="#f7a5dd")overlays.push(this.path.slice());},save(){},restore(){},rect(){},clip(){},translate(){},closePath(){},fill(rule){draws.push({vector:true,rule});},setLineDash(){},measureText:text=>({width:text.length*6}),strokeText(){}});
    class Reader {
      readAsArrayBuffer(file){this.readyState=1;file.arrayBuffer().then(bytes=>{if(this.readyState!==1)return;this.readyState=2;this.result=bytes;this.onload?.();},()=>{this.readyState=2;this.onerror?.();});}
      abort(){this.readyState=2;this.onabort?.();}
    }
    class EmbeddedWorker {
      constructor(url) {
        workers.push(this);this.terminated=false;
        this.ready=blobs[Number(url.split("-").at(-1))-1].text().then(code=> {
          const worker={self:{postMessage:(value,transfer=[])=>{const data=structuredClone(value,{transfer});queueMicrotask(()=>{if(!this.terminated)this.onmessage?.({data});});}},Uint8Array,ArrayBuffer,crypto:webcrypto,Blob,DecompressionStream,TextEncoder,TextDecoder,setTimeout,clearTimeout,fetch:forbidden,XMLHttpRequest:forbidden,WebSocket:forbidden,console:{log(){},warn(){},error(){}}};
          vm.createContext(worker,{codeGeneration:{strings:false,wasm:false}});vm.runInContext(code,worker,{timeout:5000});return worker;
        });
      }
      postMessage(value,transfer){const data=structuredClone(value,{transfer});this.ready.then(worker=>{if(!this.terminated)return worker.self.onmessage({data});}).catch(error=>{if(!this.terminated)this.onerror?.(error);});}
      terminate(){this.terminated=true;}
    }
    Object.assign(sandbox,{FileReader:Reader,Worker:EmbeddedWorker,atob,Uint8Array,ArrayBuffer,setTimeout:(fn,ms)=>ms===30000 ? undefined : setTimeout(fn,ms),clearTimeout,createImageBitmap:async blob=> {
      const header=imageHeader(new Uint8Array(await blob.arrayBuffer()));
      const bitmap={width:header.width,height:header.height,closed:false,close(){this.closed=true;}};bitmaps.push(bitmap);return bitmap;
    }});
  }
  Object.defineProperty(sandbox,"localStorage",{get() { storageTouches++; throw Error("Storage unavailable for local file"); }});
  vm.runInNewContext(script,sandbox,{timeout:1000,filename:"fieldforge-offline.html"});
  return {id,opened,blobs,downloads,workers,bitmaps,draws,markers,overlays,get storageTouches() { return storageTouches; },get requests() { return requests; },confirm:choice => { confirmation = choice; }};
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
// Independent XML parsing via Python, adapted to the DOM shape the production
// GPX reader uses. This does not test a native browser DOMParser.
class FixtureXMLParser {
  parseFromString(text){
    const python="import json,sys,xml.etree.ElementTree as E\ndef item(e):\n tag=e.tag; ns=tag[1:].split('}')[0] if tag.startswith('{') else ''; name=tag.split('}')[-1]\n return dict(localName=name,namespaceURI=ns,attributes=e.attrib,textContent=''.join(e.itertext()),children=[item(c) for c in e])\nprint(json.dumps(item(E.fromstring(sys.stdin.read()))))";
    const raw=JSON.parse(execFileSync(process.env.FIELDFORGE_TEST_PYTHON||"python",["-c",python],{input:text,encoding:"utf8"}));
    const node=item=>({...item,children:item.children.map(node),getAttribute:key=>item.attributes[key]??null});return {documentElement:node(raw),getElementsByTagName:()=>[]};
  }
}
const overlayGPX='<gpx xmlns="http://www.topografix.com/GPX/1/1"><wpt lat="0" lon="100"><name>Camp &lt;b&gt;name&lt;/b&gt;</name></wpt><trk><trkseg><trkpt lat="38.12345678901234" lon="-90.12345678901234"/><trkpt lat="38.2" lon="-90"/></trkseg><trkseg><trkpt lat="-38" lon="-90"/><trkpt lat="-38.1" lon="-89.9"/></trkseg></trk></gpx>';
for(const mode of ["valid","vector"])test(`offline GPX overlays connect the inspector to ${mode} MBTiles while preserving gaps and original point coordinates`,{timeout:5000},async()=>{
  const app=boot({mbtiles:true,gpxParser:FixtureXMLParser}),raw=execFileSync(process.env.FIELDFORGE_TEST_PYTHON||"python",[resolve(root,"portal_preview/mbtiles-fixture.py"),mode]);
  const loadGPX=async(text=overlayGPX)=>{app.id("deskGpx").files=[{name:"track.gpx",size:text.length,text:async()=>text}];await app.id("deskGpx").fire("change");};
  const open=async()=>{app.id("mbFile").files=[{name:"map.mbtiles",size:raw.length,arrayBuffer:async()=>raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength)}];await app.id("mbFile").fire("change");};
  try{
    await loadGPX();assert.equal(app.id("deskViewMap").disabled,false);await app.id("deskViewMap").fire("click");assert.equal(app.id("mbPanel").hidden,false);assert.match(app.id("mbRouteSummary").textContent,/5 original points · 2 separate segments · 1 waypoints/);assert.equal(app.workers.length,0);
    await open();assert.equal(app.id("mbLatitude").value,"38.12345678901234");assert.equal(app.id("mbRouteCoordinates").textContent,"38.12345678901234, -90.12345678901234");assert.equal(app.id("mbAddPlace").disabled,true);assert.equal(app.overlays[0].filter(c=>c[0]==="line").length,2);assert.equal(app.overlays[0].filter(c=>c[0]==="move").length,2);
    app.id("mbRouteShow").checked=false;app.id("mbRouteShow").fire("change");assert.equal(app.overlays.length,0);app.id("mbRouteShow").checked=true;app.id("mbRouteShow").fire("change");assert.ok(app.overlays.length);
    app.id("mbRouteNext").fire("click");assert.match(app.id("mbRouteSelected").textContent,/Segment 1 · point 2/);app.id("mbRouteNext").fire("click");assert.match(app.id("mbRouteSelected").textContent,/Segment 2 · point 1/);
    app.id("mbRoutePoint").value="4";app.id("mbRoutePoint").fire("input");await app.id("mbRouteCentre").fire("click");assert.equal(app.id("mbLatitude").value,"0");assert.equal(app.id("mbLongitude").value,"100");assert.match(app.id("mbRouteState").textContent,/No decoded tile/);assert.equal(app.id("mbAddPlace").disabled,true);
    app.id("mbRouteAdd").fire("click");assert.equal(app.id("placesPanel").hidden,false);app.id("placesSaveJSON").fire("click");const point=JSON.parse(await app.blobs.at(-1).text()).places[0];assert.equal(point.name,"Camp <b>name</b>");assert.equal(point.lat,0);assert.equal(point.lon,100);assert.match(point.source,/GPX overlay; Waypoint 1/);
    await open();assert.equal(app.id("mbRouteCoordinates").textContent,"0, 100");assert.equal(app.id("mbRouteCard").hidden,false);
    app.id("mbRouteBack").fire("click");assert.equal(app.id("tracePanel").hidden,false);app.id("deskClearTrace").fire("click");assert.equal(app.id("mbRouteCard").hidden,true);assert.equal(app.overlays.length,0);assert.equal(app.id("mbControls").disabled,false);
    await loadGPX('<gpx><wpt lat="90" lon="0"/></gpx>');await app.id("deskViewMap").fire("click");assert.match(app.id("mbStatus").textContent,/Every overlay point needs Web Mercator/);assert.equal(app.id("mbRouteCard").hidden,true);
    await loadGPX();await app.id("deskViewMap").fire("click");app.id("mbRouteClear").fire("click");assert.equal(app.id("mbRouteCard").hidden,true);assert.equal(app.id("deskViewMap").disabled,false);
    await app.id("deskViewMap").fire("click");app.id("mbClose").fire("click");assert.equal(app.id("mbRouteCard").hidden,true);await open();assert.equal(app.id("mbRouteCard").hidden,true);
    assert.equal(app.requests,0);assert.equal(app.storageTouches,0);assert.deepEqual(app.opened,[]);
  }finally{app.id("mbClose").fire("click");}
});
for(const mode of ["valid","vector-mixed"])test(`offline download opens ${mode} MBTiles through its embedded worker and exports a selected coordinate`,{timeout:5000},async()=> {
  const app=boot({mbtiles:true});
  const raw=execFileSync(process.env.FIELDFORGE_TEST_PYTHON||"python",[resolve(root,"portal_preview/mbtiles-fixture.py"),mode]);
  try {
    app.id("mbTab").fire("click");assert.equal(app.id("mbPanel").hidden,false);assert.equal(app.id("packPanel").hidden,true);
    app.id("mbFile").files=[{name:"offline-fixture.mbtiles",size:raw.length,arrayBuffer:async()=>raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength)}];await app.id("mbFile").fire("change");
    assert.equal(app.id("mbControls").disabled,false,app.id("mbStatus").textContent);assert.ok(app.draws.length);assert.equal(app.id("mbAttribution").textContent,"<b>Fixture credit</b>");
    assert.equal(app.id("mbVectorNote").hidden,mode==="valid");
    if(mode!=="valid"){
      assert.equal(app.bitmaps.length,0);assert.ok(app.draws.some(draw=>draw.rule==="evenodd"));assert.match(app.id("mbTileSummary").textContent,/basic vector style/);assert.match(app.id("mbIssues").textContent,/Truncated protobuf/);
      app.id("mbPointNames").checked=false;app.id("mbPointNames").fire("change");assert.ok(app.draws.length);assert.equal(app.id("mbAddPlace").disabled,false);
    }
    app.id("mbAddPlace").fire("click");assert.equal(app.id("placesPanel").hidden,false);assert.match(app.id("placesCount").textContent,/1 total/);
    app.id("placesSaveJSON").fire("click");const place=JSON.parse(await app.blobs.at(-1).text()).places[0];assert.ok(place.lat<0&&place.lon<0);assert.match(place.source,/offline-fixture\.mbtiles/);
    assert.match(place.source,mode==="valid"?/raster MBTiles/:/vector MBTiles, basic preview style/);
    assert.equal(app.id("mbCoverageControls").disabled,false);assert.equal(app.id("mbCoverageResult").hidden,true);
    await app.id("mbCoverageScan").fire("click");assert.match(app.id("mbCoverageStatus").textContent,/2 indexed tile locations/);assert.match(app.id("mbCoverageStatus").textContent,/Complete index scan at this zoom/);
    assert.equal(app.id("mbCoverageDrawing").children.length,2);assert.equal(app.id("mbCoverageDrawing").children[0].attrs.height,"16");assert.equal(app.id("mbAddPlace").disabled,false);
    // The next scan's zoom selector must not change the report's jump target.
    app.id("mbCoverageZoom").value="2";app.id("mbCoverageAreas").value="0";app.id("mbCoverageAreas").fire("change");await app.id("mbCoverageOpen").fire("click");
    assert.ok(Number(app.id("mbLatitude").value)>0);assert.equal(app.id("mbZoom").value,"1");
    assert.equal(app.id("mbAddPlace").disabled,mode!=="valid"); // Northern vector tile is intentionally damaged.
    app.id("mbCoverageDrawing").children[1].fire("click");assert.match(app.id("mbCoverageSelected").textContent,/tile 1\/0\/1/);await app.id("mbCoverageOpen").fire("click");assert.ok(Number(app.id("mbLatitude").value)<0);assert.equal(app.id("mbAddPlace").disabled,false);
    app.id("mbClose").fire("click");assert.equal(app.id("mbAddPlace").disabled,true);assert.equal(app.draws.length,0);assert.ok(app.bitmaps.every(bitmap=>bitmap.closed));assert.ok(app.workers.every(worker=>worker.terminated));
    assert.match(app.id("placesCount").textContent,/1 total/);assert.equal(app.storageTouches,0);assert.equal(app.requests,0);assert.deepEqual(app.opened,[]);
    assert.equal(app.id("mbVectorNote").hidden,true);assert.equal(app.id("mbIssues").textContent,"");
    assert.equal(app.id("mbCoverageResult").hidden,true);assert.equal(app.id("mbCoverageDrawing").children.length,0);assert.equal(app.id("mbCoverageOpen").disabled,true);
  }finally{app.id("mbClose").fire("click");}
});

for(const mode of ["valid","vector"])test(`saved places open in ${mode} MBTiles without rounding records or treating markers as tile data`,{timeout:5000},async()=> {
  const app=boot({mbtiles:true}),lat="38.12345678901234",lon="-90.12345678901234",name="Camp <b>reference</b>";
  const raw=execFileSync(process.env.FIELDFORGE_TEST_PYTHON||"python",[resolve(root,"portal_preview/mbtiles-fixture.py"),mode]);
  const open=async()=>{app.id("mbFile").files=[{name:"places.mbtiles",size:raw.length,arrayBuffer:async()=>raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength)}];await app.id("mbFile").fire("change");};
  const view=index=>app.id("placesRows").children[index].children[3].children[2].fire("click");
  try{
    addManual(app,name,lat,lon,"Original source");await view(0);
    assert.equal(app.id("mbPanel").hidden,false);assert.equal(app.id("placesPanel").hidden,true);assert.equal(app.id("mbTargetCard").hidden,false);assert.equal(app.id("mbTargetName").textContent,name);assert.match(app.id("mbTargetState").textContent,/Choose a local MBTiles/);assert.equal(app.workers.length,0);
    await open();assert.equal(app.id("mbLatitude").value,lat);assert.equal(app.id("mbLongitude").value,lon);assert.equal(app.id("mbTargetCoordinates").textContent,`${lat}, ${lon}`);assert.match(app.id("mbTargetState").textContent,/within a decoded tile/);
    assert.equal(app.id("mbAddPlace").disabled,true);assert.equal(app.markers.length,1);assert.ok(Math.abs(app.markers[0][0]-384)<1e-7&&Math.abs(app.markers[0][1]-246)<1e-7);
    app.id("mbBackPlaces").fire("click");assert.equal(app.id("placesPanel").hidden,false);app.id("placesSaveJSON").fire("click");
    assert.deepEqual(JSON.parse(await app.blobs.at(-1).text()).places,[{name,lat:Number(lat),lon:Number(lon),source:"Original source"}]);
    // The map keeps an explicitly labelled snapshot; opening the edited row uses its new coordinates.
    app.id("placesRows").children[0].children[3].children[0].fire("click");app.id("placesLatitude").value="39.25";app.id("placesForm").fire("submit");assert.equal(app.id("mbTargetCoordinates").textContent,`${lat}, ${lon}`);
    await view(0);assert.equal(app.id("mbLatitude").value,"39.25");assert.equal(app.id("mbTargetCoordinates").textContent,`39.25, ${lon}`);
    // The pack has zoom 2, but no usable tile at this place at that zoom.
    app.id("mbZoom").value="2";await app.id("mbGo").fire("submit");await view(0);assert.equal(app.id("mbZoom").value,"2");assert.match(app.id("mbTargetState").textContent,/No decoded tile/);assert.equal(app.id("mbAddPlace").disabled,true);assert.equal(app.markers.length,1);
    addManual(app,"Polar place","90","0");await view(1);assert.match(app.id("mbStatus").textContent,/Mercator/);assert.equal(app.id("mbLatitude").value,"39.25");assert.equal(app.id("mbTargetName").textContent,name);
    // Returning to a marker recentres at the currently displayed zoom.
    app.id("mbLatitude").value="-60";app.id("mbLongitude").value="100";await app.id("mbGo").fire("submit");assert.match(app.id("mbTargetState").textContent,/outside this view/);assert.equal(app.markers.length,0);
    await app.id("mbTargetCentre").fire("click");assert.equal(app.id("mbLatitude").value,"39.25");assert.equal(app.id("mbZoom").value,"2");assert.equal(app.markers.length,1);
    app.id("mbTargetClear").fire("click");assert.equal(app.id("mbTargetCard").hidden,true);assert.equal(app.markers.length,0);assert.equal(app.id("mbControls").disabled,false);
    addManual(app,"Zero coordinate","0","0");await view(2);assert.equal(app.id("mbLatitude").value,"0");assert.equal(app.id("mbLongitude").value,"0");assert.equal(app.id("mbTargetCoordinates").textContent,"0, 0");assert.match(app.id("mbTargetState").textContent,/No decoded tile/);
    app.id("mbClose").fire("click");assert.equal(app.id("mbTargetCard").hidden,true);await open();assert.equal(app.id("mbTargetCard").hidden,true);assert.ok(Number(app.id("mbLatitude").value)<0);
    assert.equal(app.requests,0);assert.equal(app.storageTouches,0);assert.deepEqual(app.opened,[]);
  }finally{app.id("mbClose").fire("click");}
});

test("offline coverage exposes a partial index scan without claiming unreadable tiles can be used",{timeout:5000},async()=> {
  const app=boot({mbtiles:true}),raw=execFileSync(process.env.FIELDFORGE_TEST_PYTHON||"python",[resolve(root,"portal_preview/mbtiles-fixture.py"),"coverage-limit"],{maxBuffer:4*1024*1024});
  try{
    app.id("mbFile").files=[{name:"partial.mbtiles",size:raw.length,arrayBuffer:async()=>raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength)}];await app.id("mbFile").fire("change");
    assert.equal(app.id("mbAddPlace").disabled,true);await app.id("mbCoverageScan").fire("click");
    assert.match(app.id("mbCoverageStatus").textContent,/50,000 indexed tile locations/);assert.match(app.id("mbCoverageStatus").textContent,/Partial scan: first 50,000 rows only; more remain/);
    assert.ok(app.id("mbCoverageAreas").children.length>0&&app.id("mbCoverageAreas").children.length<=1024);assert.equal(app.id("mbCoverageOpen").disabled,false);
    await app.id("mbCoverageOpen").fire("click");assert.equal(app.id("mbZoom").value,"8");assert.equal(app.id("mbAddPlace").disabled,true);assert.match(app.id("mbIssues").textContent,/Unsupported tile size/);
    assert.equal(app.requests,0);assert.equal(app.storageTouches,0);
  }finally{app.id("mbClose").fire("click");}
});

test("offline vector layers draw polygon holes, inspect vertices and collect selected coordinates",async()=> {
  const app=boot(), shape={type:"Feature",properties:{name:"Area <b>text</b>",note:"<img src=x>"},geometry:{type:"Polygon",coordinates:[[[0,0],[4,0],[4,4],[0,4],[0,0]],[[1,1],[2,1],[2,2],[1,2],[1,1]]]}};
  app.id("vectorTab").fire("click"); assert.equal(app.id("vectorPanel").hidden,false); assert.equal(app.id("packPanel").hidden,true);
  app.id("vectorFile").files=[collectionFile("area.geojson",JSON.stringify(shape))]; await app.id("vectorFile").fire("change");
  assert.match(app.id("vectorOverview").textContent,/1 features · 10 positions/);
  const path=app.id("vectorDrawing").children[0].children[1]; assert.equal(path.attrs["fill-rule"],"evenodd"); assert.equal((path.attrs.d.match(/Z/g)||[]).length,2);
  assert.equal(app.id("vectorSelectedName").textContent,"Area <b>text</b>"); assert.ok(app.id("vectorProperties").textContent.includes("<img src=x>"));
  app.id("vectorVertex").value="6"; app.id("vectorVertex").fire("input"); assert.equal(app.id("vectorLatitude").textContent,"1.0000000"); assert.equal(app.id("vectorLongitude").textContent,"2.0000000");
  app.id("vectorZoomIn").fire("click"); assert.equal(app.id("vectorZoomLevel").textContent,"1.5×"); app.id("vectorFit").fire("click"); assert.equal(app.id("vectorSvg").attrs.viewBox,"0 0 800 380");
  app.id("vectorSaveFeature").fire("click"); assert.deepEqual(JSON.parse(await app.blobs.at(-1).text()),shape);
  app.id("vectorAddPlace").fire("click"); assert.equal(app.id("placesPanel").hidden,false); assert.match(app.id("placesRows").textContent,/vertex 7/); assert.match(app.id("placesRows").textContent,/area.geojson/);
  app.id("placesSaveJSON").fire("click"); const place=JSON.parse(await app.blobs.at(-1).text()).places[0]; assert.equal(place.lat,1); assert.equal(place.lon,2);
  app.id("vectorClear").fire("click"); assert.equal(app.id("vectorAddPlace").disabled,true); assert.match(app.id("placesCount").textContent,/1 total/);
  assert.equal(app.storageTouches,0); assert.equal(app.requests,0); assert.deepEqual(app.opened,[]);
});
test("offline vector selection is cleared for failed, cancelled and superseded reads",async()=> {
  const app=boot(), geo=name=>JSON.stringify({type:"Feature",properties:{name},geometry:{type:"Point",coordinates:[0,0]}});
  app.id("vectorFile").files=[collectionFile("point.json",geo("Current"))]; await app.id("vectorFile").fire("change");
  app.id("vectorSearch").value="missing"; app.id("vectorSearch").fire("input"); assert.equal(app.id("vectorAddPlace").disabled,true);
  app.id("vectorDrawing").children[0].fire("click"); assert.equal(app.id("vectorSearch").value,""); assert.equal(app.id("vectorAddPlace").disabled,false);
  app.id("vectorFile").files=[collectionFile("invalid.json",'{"type":"Point","coordinates":[0,91]}')]; await app.id("vectorFile").fire("change"); assert.equal(app.id("vectorAddPlace").disabled,true); assert.equal(app.id("vectorDrawing").children.length,0);
  for(const replacement of [false,true]) {
    let release; const pending=new Promise(resolve=>{release=resolve;});
    app.id("vectorFile").files=[{name:"late.json",size:100,arrayBuffer:()=>pending}]; const reading=app.id("vectorFile").fire("change");
    if(replacement) { app.id("vectorFile").files=[collectionFile("new.json",geo("Replacement"))]; await app.id("vectorFile").fire("change"); } else app.id("vectorClear").fire("click");
    release(new TextEncoder().encode(geo("Late stale result")).buffer); await reading;
    assert.ok(!app.id("vectorSelectedName").textContent.includes("Late")); assert.equal(app.id("vectorAddPlace").disabled,!replacement);
  }
  app.id("vectorFile").files=[{name:"bad-utf8.json",size:1,arrayBuffer:async()=>new Uint8Array([255]).buffer}]; await app.id("vectorFile").fire("change"); assert.match(app.id("vectorStatus").textContent,/UTF-8/);
  assert.equal(app.id("vectorSaveFeature").disabled,true); assert.equal(app.storageTouches,0); assert.equal(app.requests,0);
});
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
