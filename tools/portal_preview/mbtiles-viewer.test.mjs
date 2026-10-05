import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {execFileSync} from "node:child_process";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {createMBViewer} from "./mbtiles-viewer.mjs";
import {inspectMBDatabase,readMBFrame} from "./mbtiles-core.mjs";
import {imageHeader} from "./image-core.mjs";
import {createMBClient, createMBFileRead} from "./mbtiles-client.mjs";
const require=createRequire(import.meta.url),SQL=await require("./vendor/sql-asm-1.14.2.js")();
const raw=execFileSync(process.env.FIELDFORGE_TEST_PYTHON||"python",[fileURLToPath(new URL("./mbtiles-fixture.py",import.meta.url))]);
const bytes=raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength);
const deferred=()=> {let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
const settle=()=>new Promise(resolve=>setImmediate(resolve));

// Real SQLite and tile bytes, with DOM/bitmap doubles. Not native Canvas QA.
test("MBTiles UI collects decoded pixels and replacement opens do not wait for canceled reads or decodes",{timeout:5000},async()=> {
  const saved=new Map(["document","createImageBitmap","FileReader"].map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)])),elements=new Map(),draws=[],bitmaps=[],clients=[],collected=[],readers=[];
  class Reader {
    constructor(){this.readyState=0;this.aborted=false;readers.push(this);}
    readAsArrayBuffer(file){this.readyState=1;file.arrayBuffer().then(result=>{if(this.readyState!==1)return;this.result=result;this.readyState=2;this.onload?.();},()=>{if(this.readyState!==1)return;this.readyState=2;this.onerror?.();});}
    abort(){this.aborted=true;this.readyState=2;this.onabort?.();}
  }
  const make=()=>({children:[],handlers:new Map(),_value:"",get value(){return this._value;},set value(v){this._value=String(v);},textContent:"",disabled:false,files:[],classList:{toggle(){}},append(...items){this.children.push(...items);},replaceChildren(...items){this.children=[...items];},addEventListener(type,fn){this.handlers.set(type,fn);},fire(type,extra={}){return this.handlers.get(type)?.({preventDefault(){},...extra});}});
  for(const [,key] of readFileSync(new URL("./desk.html",import.meta.url),"utf8").matchAll(/id="(mb\w+)"/g))elements.set(key,make());
  const el=key=>{assert.ok(elements.has(key),key);return elements.get(key);};
  const ctx={clearRect(){draws.length=0;},fillRect(){},strokeRect(){},fillText(){},drawImage(bitmap){draws.push(bitmap);},beginPath(){},arc(){},moveTo(){},lineTo(){},stroke(){}};
  el("mbCanvas").getContext=()=>ctx;el("mbCanvas").getBoundingClientRect=()=>({width:768,height:512,left:0,top:0});
  const bitmap=()=>{const b={width:256,height:256,closed:false,close(){this.closed=true;}};bitmaps.push(b);return b;};
  let decode=async blob=>{assert.equal(imageHeader(new Uint8Array(await blob.arrayBuffer())).width,256);return bitmap();};
  const factory=()=>{let pack;const c={closed:false,async request(kind,data){if(kind==="open"){pack=inspectMBDatabase(SQL,new Uint8Array(data.bytes));return pack.info;}return readMBFrame(pack,data.lat,data.lon,data.zoom);},close(){pack?.db.close();this.closed=true;}};clients.push(c);return c;};
  const open=name=>{el("mbFile").files=[{name,size:bytes.byteLength,arrayBuffer:async()=>bytes.slice(0)}];return el("mbFile").fire("change");};
  try {
    Object.defineProperty(globalThis,"document",{value:{getElementById:el,createElement:make},configurable:true});
    Object.defineProperty(globalThis,"createImageBitmap",{value:(...args)=>decode(...args),configurable:true});
    Object.defineProperty(globalThis,"FileReader",{value:Reader,configurable:true});
    createMBViewer({clientFactory:factory,onAddPoint:p=>collected.push(p)});
    assert.equal(el("mbAddPlace").disabled,true);await open("test.mbtiles");assert.equal(el("mbControls").disabled,false);assert.ok(draws.length);assert.equal(el("mbAttribution").textContent,"<b>Fixture credit</b>");
    await el("mbAddPlace").fire("click");assert.equal(collected.length,1);assert.ok(collected[0].lat<0&&collected[0].lon<0);assert.match(collected[0].source,/test.mbtiles/);
    el("mbColumn").value="767";el("mbRow").value="256";await el("mbPixelForm").fire("submit");assert.equal(el("mbAddPlace").disabled,true);assert.match(el("mbSelected").textContent,/No decoded tile/);
    el("mbLatitude").value="";await el("mbGo").fire("submit");assert.match(el("mbStatus").textContent,/blank/);assert.ok(draws.length);
    el("mbLatitude").value="90";await el("mbGo").fire("submit");assert.match(el("mbStatus").textContent,/Mercator/);assert.ok(draws.length);
    const pending=deferred(),late=bitmap();decode=()=>pending.promise;
    const opening=open("cancelled.mbtiles");await settle();await el("mbClose").fire("click");pending.resolve(late);await opening;
    assert.equal(late.closed,true);assert.equal(draws.length,0);assert.equal(el("mbAddPlace").disabled,true);assert.ok(clients.every(client=>client.closed));assert.ok(bitmaps.every(b=>b.closed));
    // The replacement finishes while the old file read is still unresolved.
    const old=deferred();el("mbFile").files=[{name:"old.mbtiles",size:bytes.byteLength,arrayBuffer:()=>old.promise}];const first=el("mbFile").fire("change");await settle();const oldReader=readers.at(-1);decode=async()=>bitmap();await open("new.mbtiles");
    assert.equal(oldReader.aborted,true);assert.equal(el("mbControls").disabled,false);old.resolve(bytes.slice(0));await first;
    assert.equal(el("mbControls").disabled,false);await el("mbAddPlace").fire("click");assert.match(collected.at(-1).source,/new.mbtiles/);
    // A pending native decode also cannot hold a new generation in the queue.
    const slowDecode=deferred(),lateDecode=bitmap();decode=()=>slowDecode.promise;const decoding=open("old-decode.mbtiles");await settle();decode=async()=>bitmap();await open("replacement.mbtiles");
    assert.equal(el("mbControls").disabled,false);await el("mbAddPlace").fire("click");assert.match(collected.at(-1).source,/replacement.mbtiles/);
    slowDecode.resolve(lateDecode);await decoding;assert.equal(lateDecode.closed,true);assert.equal(el("mbControls").disabled,false);
    await el("mbClose").fire("click");assert.ok(bitmaps.every(b=>b.closed));
  } finally {for(const c of clients)if(!c.closed)c.close();for(const [key,value] of saved){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key];}}
});

test("local MBTiles file reads abort on timeout and release their handlers",async()=> {
  const keys=["FileReader","setTimeout","clearTimeout"],saved=new Map(keys.map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)])),readers=[],timers=new Map();let next=0;
  class Reader {constructor(){readers.push(this);this.readyState=0;}readAsArrayBuffer(){this.readyState=1;}abort(){this.readyState=2;this.aborted=true;this.onabort?.();}}
  try {
    for(const [key,value] of Object.entries({FileReader:Reader,setTimeout:(fn,ms)=>{assert.equal(ms,15000);timers.set(++next,fn);return next;},clearTimeout:id=>timers.delete(id)}))Object.defineProperty(globalThis,key,{value,configurable:true});
    const read=createMBFileRead({}),rejected=assert.rejects(read.promise,/15 seconds/);[...timers.values()][0]();await rejected;
    assert.equal(readers[0].aborted,true);assert.equal(readers[0].onload,null);assert.equal(timers.size,0);
    const nextRead=createMBFileRead({}),cancelled=assert.rejects(nextRead.promise,/cancelled/);nextRead.cancel();await cancelled;
    assert.equal(readers[1].aborted,true);assert.equal(timers.size,0);
  }finally{for(const [key,value] of saved){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key];}}
});

test("worker client transfers local bytes, discards late replies and terminates on timeout",async()=> {
  const keys=["document","Worker","URL","setTimeout","clearTimeout"],saved=new Map(keys.map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)])),workers=[],timers=new Map();let next=0;
  class FakeWorker {constructor(){workers.push(this);this.terminated=false;}postMessage(message,transfer){this.message=message;this.transfer=transfer;}terminate(){this.terminated=true;}}
  class LocalURL extends URL {static createObjectURL(){return "blob:test";}static revokeObjectURL(){}}
  try {
    for(const [key,value] of Object.entries({document:{getElementById:()=>({textContent:btoa("self.onmessage=()=>{}")})},Worker:FakeWorker,URL:LocalURL,setTimeout:(fn,ms)=>{assert.equal(ms,15000);timers.set(++next,fn);return next;},clearTimeout:id=>timers.delete(id)}))Object.defineProperty(globalThis,key,{value,configurable:true});
    const client=createMBClient(),buffer=new ArrayBuffer(8),job=client.request("open",{bytes:buffer},[buffer]);assert.equal(workers[0].transfer[0],buffer);workers[0].onmessage({data:{id:1,result:{name:"Read"}}});assert.deepEqual(await job,{name:"Read"});assert.equal(timers.size,0);
    const pending=client.request("frame"),rejected=assert.rejects(pending,/cancelled/);client.close();await rejected;workers[0].onmessage({data:{id:2,result:{late:true}}});assert.equal(workers[0].terminated,true);
    const slow=createMBClient(),timeout=assert.rejects(slow.request("open"),/15 seconds/);[...timers.values()][0]();await timeout;assert.equal(workers[1].terminated,true);assert.equal(timers.size,0);
  } finally {for(const [key,value] of saved){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key];}}
});
