import test from "node:test";
import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {inspectMBDatabase,readMBTileContent} from "./mbtiles-core.mjs";
import {createMBRasterDecode} from "./mbtiles-raster.mjs";
const require=createRequire(import.meta.url),SQL=await require("./vendor/sql-asm-1.14.2.js")();
const pack=inspectMBDatabase(SQL,new Uint8Array(execFileSync(process.env.FIELDFORGE_TEST_PYTHON||"python",[fileURLToPath(new URL("./mbtiles-fixture.py",import.meta.url))])));
const bytes=readMBTileContent(pack,1,0,0).data;pack.db.close();
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const bitmap=(width=256,height=256)=>({width,height,closed:false,close(){this.closed=true;}});

test("raster decoding requires a native decode, rejects mismatches and releases rejected bitmaps",async()=>{
  const saved=Object.getOwnPropertyDescriptor(globalThis,"createImageBitmap");let calls=0,next=bitmap();
  try{
    Object.defineProperty(globalThis,"createImageBitmap",{value:async(blob,options)=>{calls++;assert.equal(blob.type,"image/png");assert.equal(options.imageOrientation,"none");return next;},configurable:true});
    const decoded=await createMBRasterDecode(bytes,"png").promise;assert.equal(decoded,next);assert.equal(decoded.closed,false);decoded.close();
    await assert.rejects(createMBRasterDecode(bytes,"webp").promise,/encoding/);assert.equal(calls,1);
    next=bitmap(512,512);await assert.rejects(createMBRasterDecode(bytes,"png").promise,/dimensions disagree/);assert.equal(next.closed,true);
    Object.defineProperty(globalThis,"createImageBitmap",{value:async()=>{throw new Error("Invalid image pixel data");},configurable:true});
    await assert.rejects(createMBRasterDecode(bytes,"png").promise,/Invalid image pixel data/);
  }finally{if(saved)Object.defineProperty(globalThis,"createImageBitmap",saved);else delete globalThis.createImageBitmap;}
});
test("raster cancellation and deadlines settle promptly, clear timers and close late results",async()=>{
  const keys=["createImageBitmap","setTimeout","clearTimeout"],saved=new Map(keys.map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)])),timers=new Map();let serial=0,gate;
  try{
    for(const [key,value] of Object.entries({createImageBitmap:()=>gate.promise,setTimeout:(fn,ms)=>{assert.equal(ms,15000);timers.set(++serial,fn);return serial;},clearTimeout:key=>timers.delete(key)}))Object.defineProperty(globalThis,key,{value,configurable:true});
    for(const cancel of [true,false]){
      gate=deferred();const late=bitmap(),job=createMBRasterDecode(bytes,"png"),rejected=assert.rejects(job.promise,cancel?/cancelled/:/15 seconds/);
      if(cancel)job.cancel();else [...timers.values()][0]();await rejected;assert.equal(timers.size,0);
      gate.resolve(late);await Promise.resolve();assert.equal(late.closed,true);job.cancel();
    }
  }finally{for(const [key,value] of saved){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key];}}
});
