import {MAX_POINTS,MAX_WAYPOINTS} from "./desk-core.mjs";
import {MB_LAT_LIMIT,mbScreenPoint} from "./mbtiles-core.mjs";

function routeText(value,fallback) {return (typeof value==="string"?[...value.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069\ufffe\uffff\ud800-\udfff]/gu," ").replace(/\s+/g," ").trim()].slice(0,160).join(""):"")||fallback;}
export function prepareMBRoute(data,filename) {
  if(!data||!Array.isArray(data.segments)||!Array.isArray(data.waypoints)||data.segments.length>MAX_POINTS||data.waypoints.length>MAX_WAYPOINTS)throw new Error("Unsupported GPX overlay structure.");
  const points=[],segments=[];
  function copy(point,kind,segment,index){
    if(points.length>=MAX_POINTS)throw new Error("GPX overlay exceeds 25,000 points.");
    if(!point||!Number.isFinite(point.lat)||!Number.isFinite(point.lon)||Math.abs(point.lat)>MB_LAT_LIMIT||Math.abs(point.lon)>180)throw new Error("Every overlay point needs Web Mercator latitude within ±85.05112878° and longitude within ±180°. The GPX inspector can still show polar files.");
    const p={lat:point.lat,lon:point.lon,name:routeText(point.name,""),kind,segment,index,u:(point.lon+180)/360,v:(1-Math.asinh(Math.tan(point.lat*Math.PI/180))/Math.PI)/2};points.push(p);return p;
  }
  for(const [i,part] of data.segments.entries()){if(!Array.isArray(part)||part.length>MAX_POINTS)throw new Error("Unsupported GPX segment.");const copied=part.map((p,j)=>copy(p,"track",i,j));if(copied.length)segments.push(copied);}
  const waypoints=data.waypoints.map((p,i)=>copy(p,"waypoint",-1,i));if(!points.length)throw new Error("The GPX overlay has no points.");
  return {filename:routeText(filename,"GPX file"),segments,waypoints,points};
}
// Clip each original edge separately. No edge can bridge a segment boundary.
function clipRouteEdge(x,y,endX,endY) {
  const dx=endX-x,dy=endY-y;let from=0,to=1;
  for(const [p,q] of [[-dx,x],[dx,768-x],[-dy,y],[dy,512-y]]){if(p===0){if(q<0)return null;continue;}const r=q/p;if(p<0){if(r>to)return null;from=Math.max(from,r);}else{if(r<from)return null;to=Math.min(to,r);}}
  return [[Math.max(0,Math.min(768,x+from*dx)),Math.max(0,Math.min(512,y+from*dy))],[Math.max(0,Math.min(768,x+to*dx)),Math.max(0,Math.min(512,y+to*dy))]];
}
export function projectMBRoute(route,frame) {
  const world=256*2**frame.zoom,lines=[],dots=[];let ambiguous=0;
  const pointCopies=p=>{const x=p.u*world-frame.left,y=p.v*world-frame.top;if(y<0||y>=512)return;for(let k=Math.ceil(-x/world);k<=Math.floor((768-x)/world);k++){const at=x+k*world;if(at>=0&&at<768)dots.push([at,y]);}};
  for(const part of route.segments){if(part.length===1){pointCopies(part[0]);continue;}for(let i=1;i<part.length;i++){
    const a=part[i-1],b=part[i],raw=b.u-a.u;if(Math.abs(Math.abs(raw)-.5)<1e-12){ambiguous++;continue;}
    const delta=((raw+.5)%1+1)%1-.5,x=a.u*world-frame.left,y=a.v*world-frame.top,endX=x+delta*world,endY=b.v*world-frame.top;
    for(let k=Math.ceil(-Math.max(x,endX)/world);k<=Math.floor((768-Math.min(x,endX))/world);k++){const line=clipRouteEdge(x+k*world,y,endX+k*world,endY);if(line)lines.push(line);}
  }}
  for(const p of route.waypoints)pointCopies(p);
  return {lines,dots,ambiguous};
}
export function drawMBRoute(ctx,route,frame,selected) {
  const view=projectMBRoute(route,frame);ctx.save();ctx.beginPath();ctx.rect(0,0,768,512);ctx.clip();ctx.lineJoin="round";ctx.lineCap="round";
  ctx.beginPath();for(const [a,b] of view.lines){ctx.moveTo(...a);ctx.lineTo(...b);}ctx.strokeStyle="#402638";ctx.lineWidth=5;ctx.stroke();ctx.strokeStyle="#f7a5dd";ctx.lineWidth=2.5;ctx.stroke();
  ctx.beginPath();for(const [x,y] of view.dots){ctx.moveTo(x+3,y);ctx.arc(x,y,3,0,Math.PI*2);}ctx.fillStyle="#f7a5dd";ctx.fill();
  if(selected){const p=mbScreenPoint(selected.lat,selected.lon,frame);if(p.inside){ctx.beginPath();ctx.arc(p.x,p.y,7,0,Math.PI*2);ctx.lineWidth=4;ctx.strokeStyle="#402638";ctx.stroke();ctx.lineWidth=2;ctx.strokeStyle="#fff1fb";ctx.stroke();}}
  ctx.restore();return view;
}
