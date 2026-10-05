import test from "node:test";
import assert from "node:assert/strict";
import {mbFrame,mbUnproject} from "./mbtiles-core.mjs";
import {mbCheckState,projectMBCheckLayer,drawMBCheckLayer} from "./mbtiles-check-layer.mjs";
const tile=(x,y,status="present",decode_status="not-checked")=>({x,y,status,decode_status});

test("tile layer distinguishes all five states and never treats unchecked records as decoded",()=>{
  assert.equal(mbCheckState(tile(0,0,"missing","decoded")),"missing");
  assert.equal(mbCheckState(tile(0,0,"unsupported","unreadable")),"unsupported");
  assert.equal(mbCheckState(tile(0,0,"present","unreadable")),"unreadable");
  assert.equal(mbCheckState(tile(0,0,"present","decoded")),"decoded");
  for(const decode_status of ["not-checked",undefined,"unexpected"])assert.equal(mbCheckState(tile(0,0,"present",decode_status)),"unchecked");
});
test("layer matches visible XYZ cells at the checked zoom and can hide decoded cells",()=>{
  const centre=mbUnproject(384,384,2),frame=mbFrame(centre.lat,centre.lon,2),report={zoom:2,tiles:[tile(0,1,"missing"),tile(1,1,"present","decoded"),tile(2,1),tile(3,3)]};
  const cells=projectMBCheckLayer(report,frame);assert.deepEqual(cells.map(c=>[c.x,c.y,c.state]),[[0,1,"missing"],[1,1,"decoded"],[2,1,"unchecked"]]);
  for(const cell of cells){assert.equal(cell.left,cell.x*256-frame.left);assert.equal(cell.top,256-frame.top);}
  assert.deepEqual(projectMBCheckLayer(report,frame,true).map(c=>c.x),[0,2]);
  assert.deepEqual(projectMBCheckLayer(report,mbFrame(centre.lat,centre.lon,3)),[]);assert.deepEqual(projectMBCheckLayer(null,frame),[]);
});
test("layer wraps date-line tiles, repeats world copies and omits polar padding",()=>{
  const report={zoom:3,tiles:[tile(7,4,"missing"),tile(0,4,"unsupported")]};
  const near=projectMBCheckLayer(report,mbFrame(-10,179,3));assert.deepEqual(new Set(near.map(c=>c.x)),new Set([0,7]));
  assert.equal(projectMBCheckLayer(report,mbFrame(-10,0,3)).length,0);
  const world=projectMBCheckLayer({zoom:0,tiles:[tile(0,0)]},mbFrame(0,0,0));assert.equal(world.length,3);assert.deepEqual(world.map(c=>c.left),[0,256,512]);
  const pole=projectMBCheckLayer({zoom:1,tiles:[tile(0,0),tile(1,0)]},mbFrame(85,0,1));assert.ok(pole.length);assert.ok(pole.every(c=>c.y===0));
});
test("drawing clips the layer, labels states and isolates Canvas styles and selected gap borders",()=>{
  const calls=[],target={};const ctx=new Proxy(target,{get:(obj,key)=>key in obj?obj[key]:(...args)=>calls.push([key,...args]),set:(obj,key,value)=>{obj[key]=value;calls.push(["set",key,value]);return true;}});
  const frame=mbFrame(0,0,2),report={zoom:2,tiles:[tile(0,1,"missing"),tile(1,1,"unsupported"),tile(2,1,"present","unreadable"),tile(1,2),tile(2,2,"present","decoded")]};
  const cells=drawMBCheckLayer(ctx,report,frame,false,{x:2,y:1});assert.equal(cells.length,5);
  assert.equal(calls.filter(c=>c[0]==="save").length,1);assert.equal(calls.filter(c=>c[0]==="restore").length,1);assert.ok(calls.some(c=>c[0]==="clip"));
  const labels=calls.filter(c=>c[0]==="fillText");assert.deepEqual(new Set(labels.map(c=>c[1][0])),new Set(["M","U","!","?","D"]));
  for(const [,label,x,y,width] of labels){assert.ok(x>=0&&x<768&&y>=0&&y<512&&width>0);assert.match(label,/ [0-9]+\/[0-9]+\/[0-9]+$/);}
  assert.ok(calls.some(c=>c[0]==="setLineDash"&&c[1].length===2));assert.ok(calls.some(c=>c[0]==="set"&&c[1]==="strokeStyle"&&c[2]==="#fff"));
});
