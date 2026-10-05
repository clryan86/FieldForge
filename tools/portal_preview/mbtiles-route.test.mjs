import test from "node:test";
import assert from "node:assert/strict";
import {prepareMBRoute,projectMBRoute,drawMBRoute,mbRouteTiles} from "./mbtiles-route-core.mjs";
import {mbFrame,mbUnproject,MB_LAT_LIMIT} from "./mbtiles-core.mjs";
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

const gridPoint=(x,y,z=4)=>mbUnproject(x*256,y*256,z);
const tileKeys=tiles=>tiles.map(t=>`${t.x}/${t.y}`).sort();
test("path checks include intermediate cells, preserve segment gaps and include isolated points",()=>{
  const a=gridPoint(.5,2.5),b=gridPoint(4.5,2.5);
  assert.deepEqual(tileKeys(mbRouteTiles(route([[a,b]]),4)),["0/2","1/2","2/2","3/2","4/2"]);
  assert.deepEqual(tileKeys(mbRouteTiles(route([[a],[b]],[gridPoint(7.5,4.5)]),4)),["0/2","4/2","7/4"]);
  assert.deepEqual(mbRouteTiles(route([[a,b]]),4),mbRouteTiles(route([[b,a]]),4));
});
test("path supercover includes both sides of boundaries, corner touches and clamped polar endpoints",()=>{
  assert.deepEqual(tileKeys(mbRouteTiles(route([[gridPoint(.5,2),gridPoint(2.5,2)]]),4)),["0/1","0/2","1/1","1/2","2/1","2/2"]);
  assert.deepEqual(tileKeys(mbRouteTiles(route([[gridPoint(2,.5),gridPoint(2,2.5)]]),4)),["1/0","1/1","1/2","2/0","2/1","2/2"]);
  assert.deepEqual(tileKeys(mbRouteTiles(route([[gridPoint(.5,.5),gridPoint(1.5,1.5)]]),4)),["0/0","0/1","1/0","1/1"]);
  assert.deepEqual(tileKeys(mbRouteTiles(route([[p(MB_LAT_LIMIT,-170)],[p(-MB_LAT_LIMIT,-170)]]),4)),["0/0","0/15"]);
  assert.deepEqual(tileKeys(mbRouteTiles(route([[p(0,180),p(0,-180)]]),0)),["0/0"]);
});
test("path tile checks wrap short date-line edges and refuse ambiguous edges without partial results",()=>{
  const expected=["0/7","15/7"];
  for(const pair of [[179,-179],[-179,179]])assert.deepEqual(tileKeys(mbRouteTiles(route([[p(10,pair[0]),p(10,pair[1])]]),4)),expected);
  assert.throws(()=>mbRouteTiles(route([[p(10,0),p(10,180)]]),4),/ambiguous.*180/);
  for(const zoom of [-1,23,NaN,"1"])assert.throws(()=>mbRouteTiles(route([[p(0,0)]]),zoom),/zoom/);
});
test("path checks bound both unique cells and repeated traversal work",()=>{
  const line=end=>route([[gridPoint(.5,1.5,14),gridPoint(end,1.5,14)]]);
  assert.equal(mbRouteTiles(line(4095.5),14).length,4096);
  assert.throws(()=>mbRouteTiles(line(4096.5),14),/No partial report/);
  assert.throws(()=>mbRouteTiles(route([[p(0,-170),p(0,-10)]]),22),/limit/);
  const repeated=route([Array.from({length:25000},(_,i)=>gridPoint(i%2?80.5:10.5,1.5,8))]);
  assert.throws(()=>mbRouteTiles(repeated,8),/traversal limit/);
  assert.equal(mbRouteTiles(route(Array.from({length:25000},()=>[p(0,0)])),0).length,1);
});
test("grid-crossing coverage matches an independent segment/rectangle intersection oracle",()=>{
  function touches(ax,ay,bx,by,x,y){
    let lo=0,hi=1;
    for(const [start,delta,min,max] of [[ax,bx-ax,x,x+1],[ay,by-ay,y,y+1]]){
      if(delta===0){if(start<min||start>max)return false;continue;}
      const a=(min-start)/delta,b=(max-start)/delta;lo=Math.max(lo,Math.min(a,b));hi=Math.min(hi,Math.max(a,b));if(lo>hi+1e-12)return false;
    }return true;
  }
  const cases=[[.25,.25,7.75,7.75],[2,1,2,7],[1,3,6,3],[.25,6.75,6.75,.25]];
  let seed=1729;const random=()=>((seed=(seed*1664525+1013904223)>>>0)/2**32);
  for(let i=0;i<80;i++)cases.push(Array.from({length:4},()=>.2+random()*7.6));
  for(const [ax,ay,bx,by] of cases){const expected=[];for(let y=0;y<16;y++)for(let x=0;x<16;x++)if(touches(ax,ay,bx,by,x,y))expected.push({x,y});
    assert.deepEqual(mbRouteTiles(route([[gridPoint(ax,ay),gridPoint(bx,by)]]),4),expected,JSON.stringify([ax,ay,bx,by]));
  }
});
