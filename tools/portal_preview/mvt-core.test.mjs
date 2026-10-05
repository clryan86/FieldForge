import test from "node:test";
import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {gzipSync} from "node:zlib";
import {parseMVT,decodeVectorTile,decodeVectorFrame,MAX_MVT_EXPANDED} from "./mvt-core.mjs";
import {drawVectorTiles} from "./mvt-renderer.mjs";
const bytes=new Uint8Array(execFileSync(process.env.FIELDFORGE_TEST_PYTHON||"python",[fileURLToPath(new URL("./mbtiles-fixture.py",import.meta.url)),"vector-bytes"]));
const integer=value=>{let n=BigInt(value),a=[];while(n>127n){a.push(Number(n&127n)|128);n>>=7n;}return Buffer.from([...a,Number(n)]);};
const scalar=(key,value)=>Buffer.concat([integer(key*8),integer(value)]);
const field=(key,value)=>{const b=typeof value==="string"?Buffer.from(value):Buffer.from(value);return Buffer.concat([integer(key*8+2),integer(b.length),b]);};
const packed=(key,words)=>field(key,Buffer.concat(words.map(integer)));
const feature=(type,words,tags=[])=>Buffer.concat([scalar(3,type),packed(2,tags),packed(4,words)]);
const layer=(features,extra=[],name="place")=>field(3,Buffer.concat([scalar(15,2),field(1,name),scalar(5,256),...features.map(f=>field(2,f)),...extra]));

test("independent MVT bytes and native gzip decode points, roads and polygon holes identically",async()=> {
  const raw=parseMVT(bytes);assert.deepEqual(await decodeVectorTile(new Uint8Array(gzipSync(bytes))),raw);
  assert.deepEqual(raw.layers,["water","transportation","place"]);assert.equal(raw.positions,11);
  assert.deepEqual(raw.features.map(f=>f.style),["water","major","minor"]);
  assert.deepEqual(raw.features[0].paths,[[[16,16],[240,16],[240,240],[16,240]],[[80,80],[80,176],[176,176],[176,80]]]);
  assert.deepEqual(raw.features[1].paths,[[[0,128],[256,128]]]);assert.equal(raw.features[2].label,"Fixture camp");
});
test("MVT parser rejects truncation, invalid protobuf, references and geometry",()=> {
  for(const data of [bytes.subarray(0,bytes.length-1),[0],[15],Array(11).fill(255),[26,255]])assert.throws(()=>parseMVT(new Uint8Array(data)));
  assert.throws(()=>parseMVT(layer([feature(1,[9,0,0],[0,0])])),/reference/);
  assert.throws(()=>parseMVT(layer([feature(3,[9,0,0,18,2,0,0,2])])),/not closed/);
  assert.throws(()=>parseMVT(layer([feature(2,[10,0,0])])),/before MoveTo/);
  assert.throws(()=>parseMVT(layer([feature(1,[9,1026,0])])),/tile buffer/);
  assert.throws(()=>parseMVT(layer([feature(1,[9,0])])),/Truncated/);
  assert.throws(()=>parseMVT(Buffer.concat([layer([]),layer([])])),/layer name/);
  assert.throws(()=>parseMVT(layer([], [scalar(15,2)])),/Duplicate/);
  assert.throws(()=>parseMVT(layer([], [],Buffer.from([255]))),/UTF-8/);
  assert.equal(parseMVT(layer([])).features.length,0);
});
test("MVT text is bounded and cleaned; unknown fields are ignored",()=> {
  const value="<camp>\u202e\n"+"🌲".repeat(60),f=feature(1,[9,0,0],[0,0]),result=parseMVT(layer([Buffer.concat([f,scalar(90,1)])],[field(3,"name"),field(4,field(1,value))]));
  assert.equal([...result.features[0].label].length,48);assert.ok(!result.features[0].label.includes("\u202e"));assert.match(result.features[0].label,/^<camp> /);
  assert.throws(()=>parseMVT(layer([f],[field(3,"name"),field(4,field(1,"x".repeat(16385)))])),/text exceeds/);
});
test("compressed vectors enforce expanded limits, gzip integrity and browser capability",async()=> {
  await assert.rejects(decodeVectorTile(new Uint8Array(gzipSync(Buffer.alloc(MAX_MVT_EXPANDED+1)))),/8 MiB/);
  const bad=new Uint8Array(gzipSync(bytes));bad[bad.length-8]^=1;await assert.rejects(decodeVectorTile(bad));
  await assert.rejects(decodeVectorTile(new Uint8Array(2097153)),/2 MiB/);
  const saved=globalThis.DecompressionStream;try{globalThis.DecompressionStream=undefined;await assert.rejects(decodeVectorTile(new Uint8Array(gzipSync(bytes))),/DecompressionStream/);assert.equal((await decodeVectorTile(bytes)).features.length,3);}finally{globalThis.DecompressionStream=saved;}
});
test("per-tile and per-frame feature/position limits discard whole tiles, preserving usable neighbours",async()=> {
  const point=feature(1,[9,0,0]),many=layer(Array(5000).fill(point));assert.throws(()=>parseMVT(layer(Array(5001).fill(point))),/5,000/);
  const crowded=feature(1,[50000*8+1,...Array(100000).fill(0)]),positions=layer([crowded]);assert.equal(parseMVT(positions).positions,50000);
  assert.throws(()=>parseMVT(layer([feature(1,[50001*8+1,...Array(100002).fill(0)])])),/50,000/);
  for(const data of [many,positions]){
    const frame=await decodeVectorFrame({tiles:[{data},{data},{data},{data:new Uint8Array([26,255])}]});
    assert.ok(frame.tiles[0].vector&&frame.tiles[1].vector);assert.equal(frame.tiles[2].issue,"Vector frame limit");assert.ok(frame.tiles.every(t=>!t.data));
    assert.ok(frame.vectorStats.features<=10000&&frame.vectorStats.positions<=100000);
  }
  const mixed=await decodeVectorFrame({tiles:[{data:new Uint8Array([26,255])},{data:bytes}]});assert.ok(mixed.tiles[0].issue);assert.equal(mixed.tiles[1].vector.features.length,3);
});
test("Canvas commands clip tile buffers, preserve polygon holes and suppress overlapping point names",()=> {
  const calls=[];const ctx=new Proxy({measureText:text=>({width:text.length*6})},{get:(target,key)=>target[key]||((...args)=>calls.push([key,...args]))});
  const vector=parseMVT(bytes),tile={left:0,top:0,vector};assert.equal(drawVectorTiles(ctx,[tile]),1);
  assert.ok(calls.some(c=>c[0]==="rect"&&c.slice(1).join()==="0,0,256,256"));assert.ok(calls.some(c=>c[0]==="clip"));assert.ok(calls.some(c=>c[0]==="fill"&&c[1]==="evenodd"));
  assert.ok(calls.some(c=>c[0]==="fillText"&&c[1]==="Fixture camp"));assert.equal(calls.filter(c=>c[0]==="save").length,calls.filter(c=>c[0]==="restore").length);
  calls.length=0;assert.equal(drawVectorTiles(ctx,[tile],false),0);assert.ok(!calls.some(c=>c[0]==="fillText"));
  assert.equal(drawVectorTiles(ctx,[{...tile,vector:{features:Array(100).fill(vector.features[2])}}]),1);
});
