import {mbRouteTiles} from "./mbtiles-route-core.mjs";
import {mbUnproject} from "./mbtiles-core.mjs";

export function createMBRouteCheck({getRoute,onCheck,onOpen,download}) {
  const id=key=>document.getElementById(key);let report=null,gaps=[],version=0,busy=false,hasPack=false;
  const scope="Checks tile presence and blob size along straight Web Mercator GPX edges, isolated points and waypoints at one zoom. Includes both sides of tile boundaries and corners; date-line edges use the shorter span. No connection between separate segments. Tile contents are not decoded; map accuracy, off-path areas, other zooms and route safety are not checked.";
  function controls(){
    id("mbRouteCheckControls").disabled=!getRoute()||!hasPack||busy;
    id("mbRouteReportSave").disabled=!report||busy||typeof download!=="function";
    id("mbRouteGapOpen").disabled=!report||!gaps.length||busy;id("mbRouteGaps").disabled=busy;
  }
  function reset(){version++;report=null;gaps=[];id("mbRouteCheckResult").hidden=true;id("mbRouteGaps").replaceChildren();id("mbRouteCheckState").textContent="No path check yet. Choose a stored zoom and check the GPX against this map pack.";controls();}
  id("mbRouteCheckZoom").addEventListener("change",()=>{if(!busy)reset();});
  id("mbRouteCheckRun").addEventListener("click",async()=>{
    const route=getRoute();if(!route||!hasPack||busy)return;
    reset();const token=version,zoom=Number(id("mbRouteCheckZoom").value);
    try{
      const tiles=mbRouteTiles(route,zoom);id("mbRouteCheckState").textContent=`Checking ${tiles.length.toLocaleString()} tile records at zoom ${zoom}… Use Close / cancel to stop.`;
      const result=await onCheck(zoom,tiles);if(token!==version||getRoute()!==route||!result)return;
      report={kind:"fieldforge-gpx-tile-check",schema_version:1,gpx_file:route.filename,scope,...result};
      gaps=report.tiles.filter(tile=>tile.status!=="present");
      id("mbRouteCheckState").textContent=`Zoom ${report.zoom} · ${report.checked.toLocaleString()} tiles checked · ${report.present.toLocaleString()} present · ${report.missing.toLocaleString()} missing · ${report.unsupported.toLocaleString()} unsupported size/type. ${gaps.length?"Map data gaps found.":"No missing or unsupported tile records found."} Contents have not been decoded.`;
      for(const tile of gaps.slice(0,100)){const option=document.createElement("option");option.value=String(id("mbRouteGaps").children.length);option.textContent=`${report.zoom}/${tile.x}/${tile.y} (XYZ) · ${tile.status}`;id("mbRouteGaps").append(option);}
      id("mbRouteGaps").value="0";id("mbRouteGapControls").hidden=!gaps.length;
      id("mbRouteGapNote").textContent=gaps.length>100?`Showing the first 100 of ${gaps.length.toLocaleString()} gaps. Save the report for the full list.`:"All gaps are listed. Opening a tile centres the map on its location.";
      id("mbRouteCheckResult").hidden=false;controls();
    }catch(error){if(token===version&&getRoute()===route){id("mbRouteCheckState").textContent=error.message||"Could not check the GPX path.";controls();}}
  });
  id("mbRouteReportSave").addEventListener("click",()=>{if(report&&!busy&&typeof download==="function")download(JSON.stringify(report,null,2)+"\n","application/json","FieldForge-GPX-Tile-Check.json");});
  id("mbRouteGapOpen").addEventListener("click",()=>{
    const index=Number(id("mbRouteGaps").value),tile=gaps[index];if(!report||busy||!Number.isInteger(index)||index<0||index>=100||!tile)return;
    const p=mbUnproject((tile.x+.5)*256,(tile.y+.5)*256,report.zoom);return onOpen(p.lat,p.lon,report.zoom);
  });
  return {reset,setBusy(value,packOpen){busy=value;hasPack=packOpen;controls();},setPack(info){
    hasPack=!!info;id("mbRouteCheckZoom").replaceChildren();
    for(const zoom of info?.zooms||[]){const option=document.createElement("option");option.value=String(zoom);option.textContent=`Zoom ${zoom}`;id("mbRouteCheckZoom").append(option);}
    id("mbRouteCheckZoom").value=info?String(info.zooms[0]):"";reset();
  }};
}
