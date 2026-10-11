import test from "node:test";
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {execFileSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {readFileSync} from "node:fs";
import {createHash,webcrypto} from "node:crypto";
import vm from "node:vm";
import {inspectMBDatabase,readMBFrame,readMBCoverage,readMBRouteTiles,readMBTileContent,mbFrame,mbUnproject,mbScreenPoint,checkMBHeader} from "./mbtiles-core.mjs";
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
test("coverage uses stored coordinates, TMS orientation and a separate count for malformed rows",()=> {
  const pack=inspectMBDatabase(SQL,fixture("coverage-invalid"));
  try {
    const report=readMBCoverage(pack,1);assert.equal(report.scanned,5);assert.equal(report.valid,2);assert.equal(report.invalid,3);assert.equal(report.partial,false);
    assert.deepEqual(report.cells.map(c=>[c.column,c.row,c.span,c.count]),[[0,0,16,1],[0,16,16,1]]);
    assert.equal(report.cells[0].sample.tms,1);assert.ok(report.cells[0].sample.lat>0);assert.ok(report.cells[1].sample.lat<0);assert.equal(report.cells[0].sample.lon,-90);
    assert.equal(readMBCoverage(pack,2).valid,1);assert.throws(()=>readMBCoverage(pack,3),/stored zoom/);
    assert.throws(()=>readMBCoverage(pack,"1"),/stored zoom/);assert.throws(()=>pack.db.run("DELETE FROM tiles"),/readonly/);
  }finally{pack.db.close();}
});
test("coverage is explicitly partial only when more indexed rows remain, and groups high zoom tiles",()=> {
  for(const mode of ["coverage-exact","coverage-limit"]){const pack=inspectMBDatabase(SQL,fixture(mode));try{
    const report=readMBCoverage(pack,8);assert.equal(report.scanned,50000);assert.equal(report.valid,50000);assert.equal(report.invalid,0);assert.equal(report.partial,mode==="coverage-limit");assert.equal(report.cells.reduce((sum,c)=>sum+c.count,0),50000);assert.ok(report.cells.length<=1024);assert.ok(report.cells.every(c=>c.span===1));
    for(const c of report.cells){assert.equal(Math.floor(c.sample.x/8),c.column);assert.equal(Math.floor(c.sample.y/8),c.row);}
  }finally{pack.db.close();}}
});
test("world and date-line coverage retain actual tile footprints and do not need readable blobs",()=> {
  for(const mode of ["coverage-world","coverage-wrap","oversize-tile"]){const pack=inspectMBDatabase(SQL,fixture(mode));try{
    const report=readMBCoverage(pack,pack.info.initial.zoom);assert.equal(report.invalid,0);assert.equal(report.partial,false);
    if(mode==="coverage-world"){assert.equal(report.cells.length,1);assert.equal(report.cells[0].span,32);assert.equal(report.cells[0].sample.lon,0);assert.equal(report.cells[0].sample.lat,0);}
    if(mode==="coverage-wrap"){assert.deepEqual(report.cells.map(c=>[c.column,c.row]),[[31,0],[0,31]]);assert.ok(report.cells[0].sample.lon>179&&report.cells[1].sample.lon<-179);}
    if(mode==="oversize-tile")assert.equal(report.valid,2);
  }finally{pack.db.close();}}
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
test("saved-coordinate markers keep exact centres, use the nearest date-line copy and reject polar latitudes",()=> {
  for(const z of [0,1,10,22])for(const [lat,lon] of [[0,0],[38.12345678901234,-90.12345678901234],[-84,179.9]]){
    const p=mbScreenPoint(lat,lon,mbFrame(lat,lon,z));assert.ok(Math.abs(p.x-384)<1e-7&&Math.abs(p.y-256)<1e-7);assert.equal(p.inside,true);
  }
  assert.deepEqual(mbScreenPoint(0,-180,mbFrame(0,180,10)),{x:384,y:256,inside:true});
  const p=mbScreenPoint(0,-179.99,mbFrame(0,179.99,10));assert.ok(p.x>384&&p.x<400);assert.equal(p.inside,true);
  assert.equal(mbScreenPoint(84,0,mbFrame(0,0,10)).inside,false);assert.equal(mbScreenPoint(0,120,mbFrame(0,0,10)).inside,false);
  assert.throws(()=>mbScreenPoint(90,0,mbFrame(0,0,0)),/Mercator/);
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
  const rasterContent=await send({id:10,kind:"tile-content",zoom:1,x:0,y:0});assert.equal(rasterContent.error,undefined);assert.equal(imageHeader(new Uint8Array(rasterContent.result.data)).width,256);
  const absentContent=await send({id:11,kind:"tile-content",zoom:1,x:1,y:0});assert.equal(absentContent.result.decode_status,"unreadable");assert.equal(absentContent.result.data,undefined);
  const coverage=await send({id:5,kind:"coverage",zoom:1});assert.equal(coverage.error,undefined);assert.equal(coverage.result.valid,2);assert.equal(coverage.result.cells.length,2);
  const path=await send({id:6,kind:"route-tiles",zoom:1,tiles:[{x:0,y:0},{x:0,y:1},{x:1,y:1}]});assert.equal(path.error,undefined);assert.equal(path.result.present,2);assert.equal(path.result.missing,1);assert.ok(path.result.tiles.every(t=>!t.data));
  const vector=await send({id:3,kind:"open",bytes:fixture("vector-mixed").buffer});assert.equal(vector.result.format,"pbf");
  const vectorFrame=await send({id:4,kind:"frame",lat:vector.result.initial.lat,lon:-90,zoom:1});assert.equal(vectorFrame.error,undefined);assert.ok(vectorFrame.result.tiles.some(tile=>tile.vector?.features.length===3));assert.ok(vectorFrame.result.tiles.some(tile=>tile.issue?.includes("Truncated protobuf")));assert.ok(vectorFrame.result.tiles.every(tile=>!tile.data));assert.equal(requests,0);
  const vectorContent=await send({id:12,kind:"tile-content",zoom:1,x:0,y:1});assert.equal(vectorContent.result.decode_status,"decoded");assert.equal(vectorContent.result.vector_features,3);assert.equal(vectorContent.result.data,undefined);assert.equal(vectorContent.result.vector,undefined);
  const corruptContent=await send({id:13,kind:"tile-content",zoom:1,x:0,y:0});assert.equal(corruptContent.result.decode_status,"unreadable");assert.match(corruptContent.result.decode_issue,/Truncated protobuf/);assert.equal(corruptContent.result.data,undefined);assert.equal(requests,0);
  const provenance=JSON.parse(readFileSync(new URL("./vendor/sql.js-provenance.json",import.meta.url)));assert.equal(createHash("sha256").update(readFileSync(new URL("./vendor/sql-asm-1.14.2.js",import.meta.url))).digest("hex"),provenance.sha256);
});

test("path records distinguish present, missing and unsupported without retrieving tile blobs",()=>{
  for(const mode of ["valid","vector-mixed","oversize-tile","route-types"]){
    const pack=inspectMBDatabase(SQL,fixture(mode));try{
      const queries=[],prepare=pack.db.prepare.bind(pack.db);pack.db.prepare=(sql,...args)=>{queries.push(sql);return prepare(sql,...args);};
      const zoom=mode==="route-types"?2:1,tiles=mode==="route-types"?[{x:0,y:0},{x:0,y:1},{x:0,y:2},{x:0,y:3},{x:3,y:3}]:[{x:0,y:0},{x:0,y:1},{x:1,y:1}];
      const report=readMBRouteTiles(pack,zoom,tiles);assert.equal(report.checked,tiles.length);assert.equal(report.missing,1);
      assert.equal(report.unsupported,mode==="route-types"?3:mode==="oversize-tile"?1:0);
      assert.equal(report.present,tiles.length-1-report.unsupported);
      assert.ok(queries.every(q=>q.startsWith("SELECT typeof(tile_data),length(tile_data) FROM tiles INDEXED BY")));assert.equal(queries.length,1);
      assert.ok(report.tiles.every(t=>t.tms===2**zoom-1-t.y&&!t.data));assert.equal(report.tiles[0].status,"present");
      assert.throws(()=>readMBRouteTiles(pack,22,tiles),/stored zoom/);
      for(const invalid of [[],Array(4097).fill({x:0,y:0}),[{x:0,y:0},{x:0,y:0}],[{x:-1,y:0}],[{x:0,y:2**zoom}],[{x:0,y:NaN}],[null]])assert.throws(()=>readMBRouteTiles(pack,zoom,invalid));
      assert.throws(()=>pack.db.run("DELETE FROM tiles"),/readonly/);
    }finally{pack.db.close();}
  }
});

test("single-tile content reads validate coordinates and sizes before copying bounded bytes",()=>{
  for(const mode of ["valid","oversize-tile"]){const pack=inspectMBDatabase(SQL,fixture(mode));try{
    const queries=[],prepare=pack.db.prepare.bind(pack.db);pack.db.prepare=(sql,...args)=>{queries.push(sql);return prepare(sql,...args);};
    const content=readMBTileContent(pack,1,0,1);
    if(mode==="valid"){assert.equal(imageHeader(content.data).width,256);assert.equal(content.data.length,content.bytes);}
    else{assert.equal(content.decode_status,"unreadable");assert.equal(content.data,undefined);assert.ok(queries.every(q=>!q.startsWith("SELECT tile_data")));}
    assert.throws(()=>readMBTileContent(pack,1,-1,0),/coordinate/);assert.throws(()=>readMBTileContent(pack,1,0,2),/coordinate/);assert.throws(()=>readMBTileContent(pack,22,0,0),/stored zoom/);
  }finally{pack.db.close();}}
});
