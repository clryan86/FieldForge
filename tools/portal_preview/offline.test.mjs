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
  const rows = [...source.matchAll(/<li><a data-source-url="([^"]+)"[^>]*>([^<]+)<\/a>\s*<span[^>]*>\(~([\d.]+) (GB|MB)\)<\/span><\/li>/g)].map(([,url,name,size,unit]) => {
    const row = new Element("li"),link = new Element("a"); link.dataset.sourceUrl = url; link.textContent = name;
    row._text = `(~${size} ${unit})`; row.append(link); return row;
  });
  const createElement = tag => { const element = new Element(tag); element.onClick = () => { if (element.download) downloads.push({name:element.download,href:element.href}); }; return element; };
  const document = {getElementById:id,documentElement:{dataset:{edition:"offline",sourcesEnabled:"false"}},body:new Element("body"),createElement,createElementNS:(_,tag) => createElement(tag),createDocumentFragment:() => new Element("#fragment"),querySelectorAll:query => { assert.equal(query,"#usSourceLinks li"); return rows; }};
  class LocalURL extends URL { static createObjectURL(blob) { blobs.push(blob); return `blob:local-${blobs.length}`; } static revokeObjectURL() {} }
  const forbidden = () => { requests++; throw Error("Network access is forbidden"); };
  const sandbox = {document,window:{devicePixelRatio:1,addEventListener() {},confirm:() => confirmation,open:(...args) => opened.push(args)},URL:LocalURL,Blob,setTimeout() {},fetch:forbidden,XMLHttpRequest:forbidden,WebSocket:forbidden,navigator:{sendBeacon:forbidden}};
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
