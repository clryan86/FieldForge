import {prepareMBRoute,drawMBRoute} from "./mbtiles-route-core.mjs";
import {mbScreenPoint} from "./mbtiles-core.mjs";
import {placeCoordinateText} from "./places-core.mjs";

export function createMBRoute({onCentre,onAddPoint,onRedraw}) {
  const id=key=>document.getElementById(key);let route=null,index=0,busy=false,hasPack=false,frame=null,decodedAt=()=>false;
  const anchor=()=>route?.points[index]||null;
  const pointLabel=p=>p.kind==="waypoint"?`Waypoint ${p.index+1}`:`Segment ${p.segment+1} · point ${p.index+1}`;
  function sync(){
    const p=anchor();id("mbRouteCard").hidden=!route;id("mbRouteControls").disabled=!route||busy;id("mbRouteCentre").disabled=!p||!hasPack||busy;id("mbRoutePrevious").disabled=!p||index===0||busy;id("mbRouteNext").disabled=!p||index===route.points.length-1||busy;
    id("mbRouteName").textContent=route?.filename||"";id("mbRouteSummary").textContent=route?`${route.points.length.toLocaleString()} original points · ${route.segments.length.toLocaleString()} separate segments · ${route.waypoints.length.toLocaleString()} waypoints`:"";
    id("mbRoutePoint").max=String(Math.max(0,(route?.points.length||1)-1));id("mbRoutePoint").value=String(index);id("mbRoutePoint").setAttribute("aria-valuetext",p?pointLabel(p):"No GPX point");
    id("mbRouteSelected").textContent=p?`${pointLabel(p)}${p.name?" · "+p.name:""}`:"";id("mbRouteCoordinates").textContent=p?`${placeCoordinateText(p.lat)}, ${placeCoordinateText(p.lon)}`:"";
    let message="";if(p){if(busy)message="Map operation in progress…";else if(!frame)message="Choose a local MBTiles pack to show the overlay.";else{const pos=mbScreenPoint(p.lat,p.lon,frame);message=!pos.inside?"Selected GPX point is outside this view. Centre on it to inspect its location.":decodedAt(pos.x,pos.y)?"Selected GPX point lies on a decoded tile. The rest of the path has not been checked for map coverage.":"No decoded tile beneath the selected GPX point. The overlay is still drawn from your GPX coordinates.";}}
    id("mbRouteState").textContent=message;
  }
  function clear(){route=null;index=0;id("mbRouteShow").checked=true;id("mbRouteNote").textContent="";sync();}
  function choose(next){if(!route||busy||!Number.isInteger(next)||next<0||next>=route.points.length)return;index=next;sync();onRedraw();}
  id("mbRoutePoint").addEventListener("input",()=>choose(Number(id("mbRoutePoint").value)));
  id("mbRoutePrevious").addEventListener("click",()=>choose(index-1));id("mbRouteNext").addEventListener("click",()=>choose(index+1));
  id("mbRouteShow").addEventListener("change",()=>{if(!busy)onRedraw();});
  id("mbRouteClear").addEventListener("click",()=>{if(!busy){clear();onRedraw();}});
  id("mbRouteCentre").addEventListener("click",()=>{const p=anchor();if(p&&hasPack&&!busy)return onCentre(p);});
  id("mbRouteAdd").addEventListener("click",()=>{const p=anchor();if(!p||busy)return;try{onAddPoint({name:p.name||pointLabel(p),lat:p.lat,lon:p.lon,source:`User-supplied GPX overlay; ${pointLabel(p)}; not independently verified; file: ${route.filename}`},"GPX overlay point");}catch(error){id("mbRouteState").textContent=error.message||"Could not collect this GPX point.";}});
  clear();return {anchor,clear,load(data,filename){const next=prepareMBRoute(data,filename);route=next;index=0;id("mbRouteShow").checked=true;id("mbRouteNote").textContent="";sync();return anchor();},update(current,hit,isBusy,packOpen){frame=current;decodedAt=hit;busy=isBusy;hasPack=packOpen;sync();},draw(ctx,current){if(!route||!id("mbRouteShow").checked)return;const result=drawMBRoute(ctx,route,current,anchor());id("mbRouteNote").textContent=result.ambiguous?`${result.ambiguous} ambiguous 180° longitude edges omitted. No line was inferred across them.`:"Separate segments stay separate; date-line edges follow the shorter longitude span.";}};
}
