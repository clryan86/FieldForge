import test from "node:test";
import assert from "node:assert/strict";
import {prepareMBRoute,projectMBRoute,drawMBRoute} from "./mbtiles-route-core.mjs";
import {mbFrame} from "./mbtiles-core.mjs";
const p=(lat,lon,name="")=>({lat,lon,name});
const route=(segments,waypoints=[])=>prepareMBRoute({segments,waypoints},"test.gpx");

test("GPX overlays retain segment boundaries, isolated points and independent waypoints",()=>{
  const data=route([[p(0,-1),p(0,1)],[p(10,-1),p(10,1)],[p(-10,0)]],[p(0,0,"Camp")]),view=projectMBRoute(data,mbFrame(0,0,3));
  assert.equal(view.lines.length,2);assert.equal(view.dots.length,2);assert.equal(data.points.length,6);
  for(const [a,b] of view.lines){assert.equal(a[1],b[1]);assert.ok(b[0]>a[0]);}
  assert.notEqual(view.lines[0][0][1],view.lines[1][0][1]);assert.equal(data.points.at(-1).kind,"waypoint");
});
test("date-line crossings use the short edge without a false line across Greenwich",()=>{
  for(const pair of [[179,-179],[-179,179]]){const data=route([[p(0,pair[0]),p(0,pair[1])]]),near=projectMBRoute(data,mbFrame(0,180,3)),far=projectMBRoute(data,mbFrame(0,0,3));
    assert.equal(near.lines.length,1);assert.ok(Math.abs(near.lines[0][1][0]-near.lines[0][0][0])<12);assert.equal(far.lines.length,0);
  }
  assert.equal(projectMBRoute(route([[p(0,0),p(0,180)]]),mbFrame(0,0,0)).ambiguous,1);
  const wrapped=projectMBRoute(route([[p(0,180),p(0,-180)]]),mbFrame(0,180,0));assert.ok(wrapped.lines.every(([a,b])=>a[0]===b[0]));
});
test("overlay geometry is clipped to the viewport and repeats consistently at world zoom",()=>{
  const data=route([[p(-80,-80),p(80,80)]]),frame=mbFrame(0,0,22),view=projectMBRoute(data,frame);
  assert.equal(view.lines.length,1);for(const edge of view.lines)for(const [x,y] of edge)assert.ok(x>=0&&x<=768&&y>=0&&y<=512);
  const worldwide=projectMBRoute(route([[p(0,-1),p(0,1)]],[p(0,0)]),mbFrame(0,0,0));assert.equal(worldwide.lines.length,3);assert.equal(worldwide.dots.length,3);
  assert.equal(projectMBRoute(route([[p(80,0)]],[p(-80,0)]),mbFrame(0,0,22)).dots.length,0);
});
test("overlay preparation bounds input, rejects polar points and copies coordinates without mutation",()=>{
  const source={segments:[[p(38.12345678901234,-90.12345678901234,"<camp>\u202e")]],waypoints:[]},data=prepareMBRoute(source,"file\nname.gpx");
  assert.equal(data.points[0].lat,38.12345678901234);assert.equal(data.points[0].name,"<camp>");assert.equal(data.filename,"file name.gpx");source.segments[0][0].lat=0;assert.notEqual(data.points[0].lat,0);
  for(const latitude of [90,-90,NaN])assert.throws(()=>route([[p(latitude,0)]]),/Mercator/);
  assert.throws(()=>route([[p(0,181)]]),/longitude/);assert.throws(()=>route([]),/no points/);
  assert.throws(()=>route([Array(25001).fill(p(0,0))]),/segment/);assert.throws(()=>route([Array(25000).fill(p(0,0))],[p(0,0)]),/25,000/);assert.throws(()=>route([],Array(1001).fill(p(0,0))),/structure/);
  const maximum=route(Array.from({length:25000},()=>[p(0,0)]));assert.equal(projectMBRoute(maximum,mbFrame(0,0,0)).dots.length,75000);
});
test("Canvas overlay commands keep edges separate, clip drawing and mark the selected original point",()=>{
  const calls=[],ctx=new Proxy({},{get:(_,key)=>(...args)=>calls.push([key,...args])}),data=route([[p(0,-1),p(0,1)],[p(10,-1),p(10,1)]],[p(0,0)]);
  drawMBRoute(ctx,data,mbFrame(0,0,3),data.waypoints[0]);assert.ok(calls.some(c=>c[0]==="clip"));assert.equal(calls.filter(c=>c[0]==="lineTo").length,2);assert.ok(calls.some(c=>c[0]==="arc"&&c[1]===384&&c[2]===256&&c[3]===7));assert.equal(calls.filter(c=>c[0]==="save").length,calls.filter(c=>c[0]==="restore").length);
});
