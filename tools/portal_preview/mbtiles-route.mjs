import {prepareMBRoute,drawMBRoute} from "./mbtiles-route-core.mjs";
import {mbScreenPoint} from "./mbtiles-core.mjs";
import {createMBRouteCheck} from "./mbtiles-route-check.mjs";
import {placeCoordinateText} from "./places-core.mjs";

export function createMBRoute({onCentre,onAddPoint,onRedraw,onCheck,onVerify,onOpen,download}) {
  const id=key=>document.getElementById(key);let route=null,index=0,busy=false,hasPack=false,frame=null,decodedAt=()=>false;
  const anchor=()=>route?.points[index]||null;
  const check=createMBRouteCheck({getRoute:()=>route,onCheck,onVerify,onOpen,onRedraw,download});
  const pointLabel=p=>p.kind==="waypoint"?`Waypoint ${p.index+1}`:`Segment ${p.segment+1} · point ${p.index+1}`;
  const distance=meters=>(meters/1000).toFixed(meters<10000?2:1)+" km / "+(meters/1609.344).toFixed(meters<16093.44?2:1)+" mi";
  function sync(){
    check.setBusy(busy,hasPack,frame);
    const p=anchor();id("mbRouteCard").hidden=!route;id("mbRouteControls").disabled=!route||busy;id("mbRouteCentre").disabled=!p||!hasPack||busy;id("mbRoutePrevious").disabled=!p||index===0||busy;id("mbRouteNext").disabled=!p||index===route.points.length-1||busy;
    id("mbRouteName").textContent=route?.filename||"";
    const length=route?.traceLengthMeters;
    const lengthText=length===null||length===undefined?"no connected GPX trace":"approximately "+distance(length)+" great-circle trace length; segment gaps excluded";
    id("mbRouteSummary").textContent=route?route.points.length.toLocaleString()+" original points · "+route.segments.length.toLocaleString()+" separate segments · "+route.waypoints.length.toLocaleString()+" waypoints · "+lengthText:"";
    id("mbRoutePoint").max=String(Math.max(0,(route?.points.length||1)-1));id("mbRoutePoint").value=String(index);id("mbRoutePoint").setAttribute("aria-valuetext",p?pointLabel(p):"No GPX point");
    id("mbRouteSelected").textContent=p?`${pointLabel(p)}${p.name?" · "+p.name:""}`:"";id("mbRouteCoordinates").textContent=p?`${placeCoordinateText(p.lat)}, ${placeCoordinateText(p.lon)}`:"";
    id("mbRouteGroup").value=p?String(p.group):"";
    const group=p?route.groups[p.group]:null;
    id("mbRouteDistance").textContent=!p?"":p.kind==="waypoint"?"Separate waypoint; no distance along a GPX segment.":group.lengthMeters===null?"Isolated GPX point; no connected trace in this segment.":`Approximate distance along this GPX segment: ${distance(p.segmentMeters)} from start · ${distance(Math.max(0,group.lengthMeters-p.segmentMeters))} to segment end. `+(p.legMeters===null?"Start of segment; no previous leg.":`Previous recorded leg: ${distance(p.legMeters)}.`);
    let message="";if(p){if(busy)message="Map operation in progress…";else if(!frame)message="Choose a local MBTiles pack to show the overlay.";else{const pos=mbScreenPoint(p.lat,p.lon,frame);message=!pos.inside?"Selected GPX point is outside this view. Centre on it to inspect its location.":decodedAt(pos.x,pos.y)?"Selected GPX point lies on a decoded tile. Use the path tile check below to inspect tile records along the whole GPX.":"No decoded tile beneath the selected GPX point. The overlay is still drawn from your GPX coordinates.";}}
    id("mbRouteState").textContent=message;
  }
  function clear(){route=null;index=0;check.reset();id("mbRouteGroup").replaceChildren();id("mbRouteShow").checked=true;id("mbRouteNote").textContent="";sync();}
  function choose(next){if(!route||busy||!Number.isInteger(next)||next<0||next>=route.points.length)return;index=next;sync();onRedraw();}
  id("mbRouteGroup").addEventListener("change",()=>{const value=id("mbRouteGroup").value,group=value!==""&&Number.isInteger(Number(value))?route?.groups[Number(value)]:null;if(group)choose(group.start);});
  id("mbRoutePoint").addEventListener("input",()=>choose(Number(id("mbRoutePoint").value)));
  id("mbRoutePrevious").addEventListener("click",()=>choose(index-1));id("mbRouteNext").addEventListener("click",()=>choose(index+1));
  id("mbRouteShow").addEventListener("change",()=>{if(!busy)onRedraw();});
  id("mbRouteClear").addEventListener("click",()=>{if(!busy){clear();onRedraw();}});
  id("mbRouteCentre").addEventListener("click",()=>{const p=anchor();if(p&&hasPack&&!busy)return onCentre(p);});
  id("mbRouteAdd").addEventListener("click",()=>{const p=anchor();if(!p||busy)return;try{onAddPoint({name:p.name||pointLabel(p),lat:p.lat,lon:p.lon,source:`User-supplied GPX overlay; ${pointLabel(p)}; not independently verified; file: ${route.filename}`},"GPX overlay point");}catch(error){id("mbRouteState").textContent=error.message||"Could not collect this GPX point.";}});
  clear();return {anchor,clear,setPack:check.setPack,load(data,filename){const next=prepareMBRoute(data,filename);route=next;index=0;check.reset();
    const options=document.createDocumentFragment();
    for(const [i,group] of route.groups.entries()){const option=document.createElement("option");option.value=String(i);option.textContent=group.kind==="waypoint"?`Waypoints · ${group.count.toLocaleString()}`:`Segment ${group.segment+1} · ${group.count.toLocaleString()} points · ${group.lengthMeters===null?"isolated point":"approximately "+distance(group.lengthMeters)}`;options.append(option);}
    id("mbRouteGroup").replaceChildren(options);id("mbRouteShow").checked=true;id("mbRouteNote").textContent="";sync();return anchor();},update(current,hit,isBusy,packOpen){frame=current;decodedAt=hit;busy=isBusy;hasPack=packOpen;sync();},draw(ctx,current){check.draw(ctx,current);if(!route||!id("mbRouteShow").checked)return;const result=drawMBRoute(ctx,route,current,anchor());id("mbRouteNote").textContent=result.ambiguous?`${result.ambiguous} ambiguous 180° longitude edges omitted. No line was inferred across them.`:"Separate segments stay separate; date-line edges follow the shorter longitude span.";}};
}

