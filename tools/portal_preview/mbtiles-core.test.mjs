import test from "node:test";
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {execFileSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {readFileSync} from "node:fs";
import {createHash,webcrypto} from "node:crypto";
import vm from "node:vm";
import {inspectMBDatabase,readMBFrame,mbFrame,mbUnproject,checkMBHeader} from "./mbtiles-core.mjs";
import {imageHeader} from "./image-core.mjs";
const require=createRequire(import.meta.url),SQL=await require("./vendor/sql-asm-1.14.2.js")();
const fixture=mode=>new Uint8Array(execFileSync(process.env.FIELDFORGE_TEST_PYTHON||"python",[fileURLToPath(new URL("./mbtiles-fixture.py",import.meta.url)),mode||"valid"],{maxBuffer:4*1024*1024}));

test("real SQLite reads indexed MBTiles, observed zooms and stored-tile centre without changing bytes",()=> {
  const bytes=fixture(),before=createHash("sha256").update(bytes).digest("hex"),pack=inspectMBDatabase(SQL,bytes);
  try {assert.deepEqual(pack.info.zooms,[1,2]);assert.equal(pack.info.initial.zoom,1);assert.equal(pack.info.initial.lon,-90);assert.ok(pack.info.initial.lat<0);assert.equal(pack.info.attribution,"<b>Fixture credit</b>");
    const south=readMBFrame(pack,pack.info.initial.lat,-90,1),north=readMBFrame(pack,-pack.info.initial.lat,-90,1);
    const a=south.tiles.find(tile=>tile.x===0&&tile.y===1),b=north.tiles.find(tile=>tile.x===0&&tile.y===0);
    assert.equal(a.tms,0);assert.equal(b.tms,1);assert.notDeepEqual(a.data,b.data);assert.equal(imageHeader(a.data).width,256);assert.ok(south.tiles.some(tile=>tile.issue));
    assert.throws(()=>pack.db.run("DELETE FROM tiles"),/readonly/);assert.equal(createHash("sha256").update(bytes).digest("hex"),before);
  }finally{pack.db.close();}
});
test("reader rejects unsupported schemas, WAL, XYZ and malformed metadata",()=> {
  for(const [mode,message] of [["unindexed",/index/],["wal",/WAL/],["xyz",/TMS/],["duplicate",/Duplicate/],["oversize-metadata",/metadata/],["bad-coordinate",/coordinates/],["view",/Normalized/]])assert.throws(()=>inspectMBDatabase(SQL,fixture(mode)),message,mode);
  const bytes=fixture();assert.throws(()=>checkMBHeader(bytes.subarray(0,bytes.length-1)),/layout/);bytes[0]=0;assert.throws(()=>checkMBHeader(bytes),/SQLite/);
});
test("oversized tile blobs are identified before returning them and absent zooms fail",()=> {
  const pack=inspectMBDatabase(SQL,fixture("oversize-tile"));try{const frame=readMBFrame(pack,pack.info.initial.lat,-90,1);assert.ok(frame.tiles.some(tile=>tile.issue==="Unsupported tile size"));assert.ok(frame.tiles.every(tile=>!tile.data||tile.data.length<=2097152));assert.throws(()=>readMBFrame(pack,0,0,3),/not stored/);}finally{pack.db.close();}
});
test("Mercator frame math preserves zero, wraps the date line and marks polar padding",()=> {
  assert.deepEqual(mbUnproject(128,128,0),{lat:0,lon:0});assert.equal(mbUnproject(0,128,0).lon,-180);assert.equal(mbUnproject(256,128,0).lon,-180);
  for(const z of [0,1,10,22])for(const [lat,lon] of [[0,0],[40,-74],[-40,179.99],[85,180]]){const frame=mbFrame(lat,lon,z),point=mbUnproject(frame.left+384,frame.top+256,z);assert.ok(Math.abs(point.lat-lat)<1e-8);assert.ok(Math.abs(point.lon-(lon===180?-180:lon))<1e-8);assert.ok(frame.tiles.length<=12);assert.ok(frame.tiles.every(tile=>tile.x>=0&&tile.x<2**z));}
  assert.ok(mbFrame(85,0,1).tiles.some(tile=>tile.outside));assert.throws(()=>mbFrame(90,0,1));assert.throws(()=>mbFrame(NaN,0,1));
});
test("fractional viewport edges include the tile beneath every corner pixel",()=> {
  for(const z of [2,10,22])for(const offset of [-255.75,-.75,0,.25,.5,.75,255.75,256]) {
    const centre=mbUnproject(384+offset,256+offset,z),frame=mbFrame(centre.lat,centre.lon,z);
    assert.ok(frame.tiles.length<=12);
    for(const x of [.5,767.5])for(const y of [.5,511.5]) {
      assert.ok(frame.tiles.some(tile=>x>=tile.left&&x<tile.left+256&&y>=tile.top&&y<tile.top+256),`zoom ${z}, origin ${offset}, corner ${x}/${y}`);
    }
  }
});
test("built SQLite worker starts and reads a pack with network, eval and WebAssembly disabled",async()=> {
  const root=fileURLToPath(new URL("../",import.meta.url));
  const source=execFileSync(process.env.FIELDFORGE_TEST_PYTHON||"python",["-c","from pathlib import Path; from build_mbtiles_worker import worker_source; print(worker_source(Path('portal_preview')))"],{cwd:root,maxBuffer:4*1024*1024,encoding:"utf8"});
  let reply,requests=0;const forbidden=()=>{requests++;throw new Error("Network forbidden");};
  const sandbox={self:{postMessage:value=>reply(value)},crypto:webcrypto,Blob,DecompressionStream,TextDecoder,TextEncoder,setTimeout,clearTimeout,console:{log(){},error(){},warn(){}},fetch:forbidden,XMLHttpRequest:forbidden,WebSocket:forbidden};
  vm.createContext(sandbox,{codeGeneration:{strings:false,wasm:false}});vm.runInContext(source,sandbox,{timeout:5000});
  const send=data=>new Promise(resolve=>{reply=resolve;sandbox.self.onmessage({data});});
  const data=fixture(),opened=await send({id:1,kind:"open",bytes:data.buffer});assert.equal(opened.error,undefined);assert.equal(opened.result.name,"Synthetic test fixture");
  const frame=await send({id:2,kind:"frame",lat:opened.result.initial.lat,lon:-90,zoom:1});assert.equal(frame.error,undefined);assert.ok(frame.result.tiles.some(tile=>tile.data));assert.equal(requests,0);
  const vector=await send({id:3,kind:"open",bytes:fixture("vector-mixed").buffer});assert.equal(vector.result.format,"pbf");
  const vectorFrame=await send({id:4,kind:"frame",lat:vector.result.initial.lat,lon:-90,zoom:1});assert.equal(vectorFrame.error,undefined);assert.ok(vectorFrame.result.tiles.some(tile=>tile.vector?.features.length===3));assert.ok(vectorFrame.result.tiles.some(tile=>tile.issue?.includes("Truncated protobuf")));assert.ok(vectorFrame.result.tiles.every(tile=>!tile.data));assert.equal(requests,0);
  const provenance=JSON.parse(readFileSync(new URL("./vendor/sql.js-provenance.json",import.meta.url)));assert.equal(createHash("sha256").update(readFileSync(new URL("./vendor/sql-asm-1.14.2.js",import.meta.url))).digest("hex"),provenance.sha256);
});
