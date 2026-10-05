import {MAX_POINTS,MAX_WAYPOINTS} from "./desk-core.mjs";
import {MB_LAT_LIMIT,MAX_MB_ROUTE_TILES,mbScreenPoint} from "./mbtiles-core.mjs";

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

// Conservative supercover of the same straight Mercator edges as the overlay.
// Sample every grid crossing and the interval between crossings. Boundary
// samples include both neighbours (four at a corner), with a tiny tolerance
// for floating-point projection roundoff. Segment breaks never create edges.
export function mbRouteTiles(route,zoom) {
  if(!Number.isInteger(zoom)||zoom<0||zoom>22)throw new Error("Choose a zoom from 0 to 22.");
  const count=2**zoom,tiles=new Map(),epsilon=1e-8;let visits=0;
  const limit=()=>{throw new Error("Path check exceeds 4,096 tiles or its traversal limit. Choose a lower stored zoom or a shorter GPX file. No partial report was created.");};
  function add(x,y){
    if(++visits>250000)limit();
    const neighbours=v=>Math.abs(v-Math.round(v))<=epsilon?[Math.round(v)-1,Math.round(v)]:[Math.floor(v)];
    for(const rawX of neighbours(x))for(const row of neighbours(y)){
      if(row<0||row>=count)continue;const column=((rawX%count)+count)%count,key=`${column}/${row}`;
      if(!tiles.has(key)){if(tiles.size===MAX_MB_ROUTE_TILES)limit();tiles.set(key,{x:column,y:row});}
    }
  }
  const xy=p=>[p.u*count,Math.max(0,Math.min(count,p.v*count))];
  for(const part of route.segments){
    if(part.length===1){add(...xy(part[0]));continue;}
    for(let i=1;i<part.length;i++){
      const a=part[i-1],b=part[i],raw=b.u-a.u;
      if(Math.abs(Math.abs(raw)-.5)<1e-12)throw new Error("Cannot check an ambiguous 180° longitude edge. Split or correct that GPX segment first. No partial report was created.");
      const [x,y]=xy(a),dx=(((raw+.5)%1+1)%1-.5)*count,dy=xy(b)[1]-y,times=[0,1];
      for(const [start,delta] of [[x,dx],[y,dy]]){
        if(delta===0)continue;
        const low=Math.min(start,start+delta),high=Math.max(start,start+delta);
        if(high-low>MAX_MB_ROUTE_TILES+1)limit();
        for(let grid=Math.floor(low)+1;grid<high;grid++){const t=(grid-start)/delta;if(t>0&&t<1)times.push(t);}
      }
      times.sort((a,b)=>a-b);
      for(let j=0;j<times.length;j++){
        const t=times[j];add(x+t*dx,y+t*dy);
        if(j&&t>times[j-1]){const mid=(t+times[j-1])/2;add(x+mid*dx,y+mid*dy);}
      }
    }
  }
  for(const p of route.waypoints)add(...xy(p));
  return [...tiles.values()].sort((a,b)=>a.y-b.y||a.x-b.x);
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
