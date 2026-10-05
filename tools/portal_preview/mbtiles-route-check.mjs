import {mbRouteTiles} from "./mbtiles-route-core.mjs";
import {mbUnproject} from "./mbtiles-core.mjs";

export function createMBRouteCheck({getRoute,onCheck,onVerify,onOpen,download}) {
  const id=key=>document.getElementById(key);let report=null,gaps=[],version=0,busy=false,hasPack=false,verifying=false,stop=false;
  const scope="Checks tile presence and blob size along straight Web Mercator GPX edges, isolated points and waypoints at one zoom. Includes both sides of tile boundaries and corners; date-line edges use the shorter span. No connection between separate segments. Optional decoding results are recorded in content_check and each tile's decode_status. Map accuracy, off-path areas, other zooms and route safety are not checked.";
  const decodeScope="Raster: native bitmap decoding with matching PNG/JPEG/WebP format and 256/512 square dimensions. Vector: this viewer's bounded MVT/gzip parser. Decoded does not establish complete rendering, map accuracy, access or safe passage. Unreadable includes unsupported data and decoder limits/failures in this browser. Missing and unsupported-size/type records are not eligible for decoding.";
  const pending=()=>report?.tiles.filter(tile=>tile.status==="present"&&tile.decode_status==="not-checked")||[];
  function controls(){
    const locked=busy||verifying;
    id("mbRouteCheckControls").disabled=!getRoute()||!hasPack||locked;
    id("mbRouteReportSave").disabled=!report||locked||typeof download!=="function";
    id("mbRouteGapOpen").disabled=!report||!gaps.length||locked;id("mbRouteGaps").disabled=locked;
    id("mbRouteVerify").disabled=!report||!pending().length||locked||typeof onVerify!=="function";
    id("mbRouteVerify").textContent=report?.content_check.attempted?"Continue verifying tile contents":"Verify tile contents";
    id("mbRouteVerifyPause").hidden=!verifying;id("mbRouteVerifyPause").disabled=!verifying||stop;
  }
  function reset(){
    version++;stop=true;verifying=false;report=null;gaps=[];id("mbRouteCheckResult").hidden=true;id("mbRouteGaps").replaceChildren();
    id("mbRouteCheckState").textContent="No path check yet. Choose a stored zoom and check the GPX against this map pack.";
    id("mbRouteDecodeState").textContent="";id("mbRouteDecodeProgress").value=0;controls();
  }
  function render(){
    if(!report)return;
    const decoded=report.tiles.filter(tile=>tile.decode_status==="decoded").length,unreadable=report.tiles.filter(tile=>tile.decode_status==="unreadable").length,remaining=pending().length,attempted=decoded+unreadable;
    report.content_check={state:attempted===0?"not-started":remaining?"partial":"complete",attempted,decoded,unreadable,remaining,eligible:report.present,batch_limit:128,scope:decodeScope};
    gaps=report.tiles.filter(tile=>tile.status!=="present"||tile.decode_status==="unreadable");
    id("mbRouteCheckState").textContent=`Zoom ${report.zoom} · ${report.checked.toLocaleString()} tiles checked · ${report.present.toLocaleString()} present · ${report.missing.toLocaleString()} missing · ${report.unsupported.toLocaleString()} unsupported size/type. ${gaps.length?"Map data gaps or unreadable tiles found.":"No missing or unsupported tile records found."}`;
    id("mbRouteGaps").replaceChildren();
    for(const tile of gaps.slice(0,100)){const option=document.createElement("option");option.value=String(id("mbRouteGaps").children.length);option.textContent=`${report.zoom}/${tile.x}/${tile.y} (XYZ) · ${tile.decode_status==="unreadable"?"unreadable":tile.status}${tile.decode_issue?" · "+tile.decode_issue:""}`;id("mbRouteGaps").append(option);}
    id("mbRouteGaps").value="0";id("mbRouteGapControls").hidden=!gaps.length;
    id("mbRouteGapNote").textContent=gaps.length>100?`Showing the first 100 of ${gaps.length.toLocaleString()} gaps or unreadable tiles. Save the report for the full list.`:"All gaps and unreadable tiles are listed. Opening a tile centres the map on its location.";
    id("mbRouteDecodeProgress").max=Math.max(1,report.present);id("mbRouteDecodeProgress").value=attempted;
    id("mbRouteDecodeProgress").setAttribute("aria-valuetext",`${attempted} of ${report.present} eligible tile contents checked`);
    id("mbRouteDecodeState").textContent=`${verifying?(stop?"Pausing after the current operation… ":"Verifying… "):""}${decoded.toLocaleString()} decoded · ${unreadable.toLocaleString()} unreadable · ${remaining.toLocaleString()} unchecked. `+(report.present===0?"No eligible tile records to decode.":remaining?"Content verification is incomplete.":"All eligible tiles have a decoding result. Missing and unsupported records remain gaps.");
    id("mbRouteCheckResult").hidden=false;controls();
  }
  id("mbRouteCheckZoom").addEventListener("change",()=>{if(!busy&&!verifying)reset();});
  id("mbRouteCheckRun").addEventListener("click",async()=>{
    const route=getRoute();if(!route||!hasPack||busy||verifying)return;
    reset();const token=version,zoom=Number(id("mbRouteCheckZoom").value);
    try{
      const tiles=mbRouteTiles(route,zoom);id("mbRouteCheckState").textContent=`Checking ${tiles.length.toLocaleString()} tile records at zoom ${zoom}… Use Close / cancel to stop.`;
      const result=await onCheck(zoom,tiles);if(token!==version||getRoute()!==route||!result)return;
      report={kind:"fieldforge-gpx-tile-check",schema_version:2,gpx_file:route.filename,scope,...result};
      for(const tile of report.tiles)tile.decode_status=tile.status==="present"?"not-checked":"not-applicable";
      render();
    }catch(error){if(token===version&&getRoute()===route){id("mbRouteCheckState").textContent=error.message||"Could not check the GPX path.";controls();}}
  });
  id("mbRouteVerify").addEventListener("click",async()=>{
    if(!report||busy||verifying||typeof onVerify!=="function")return;
    const selected=pending().slice(0,128);if(!selected.length)return;
    const token=version,current=report;verifying=true;stop=false;render();
    try{
      await onVerify(report.zoom,selected,result=>{
        if(token!==version||report!==current)return;
        const tile=selected.find(tile=>tile.x===result.x&&tile.y===result.y);if(!tile)return;
        tile.decode_status=result.decode_status==="decoded"?"decoded":"unreadable";
        if(tile.decode_status==="unreadable")tile.decode_issue=String(result.decode_issue||"Tile could not be decoded.").slice(0,240);
        render();
      },()=>stop||token!==version||report!==current);
    }finally{if(token===version&&report===current){verifying=false;render();}}
  });
  id("mbRouteVerifyPause").addEventListener("click",()=>{if(verifying){stop=true;render();}});
  id("mbRouteReportSave").addEventListener("click",()=>{if(report&&!busy&&!verifying&&typeof download==="function")download(JSON.stringify(report,null,2)+"\n","application/json","FieldForge-GPX-Tile-Check.json");});
  id("mbRouteGapOpen").addEventListener("click",()=>{
    const index=Number(id("mbRouteGaps").value),tile=gaps[index];if(!report||busy||verifying||!Number.isInteger(index)||index<0||index>=100||!tile)return;
    const p=mbUnproject((tile.x+.5)*256,(tile.y+.5)*256,report.zoom);return onOpen(p.lat,p.lon,report.zoom);
  });
  return {reset,setBusy(value,packOpen){busy=value;hasPack=packOpen;controls();},setPack(info){
    hasPack=!!info;id("mbRouteCheckZoom").replaceChildren();
    for(const zoom of info?.zooms||[]){const option=document.createElement("option");option.value=String(zoom);option.textContent=`Zoom ${zoom}`;id("mbRouteCheckZoom").append(option);}
    id("mbRouteCheckZoom").value=info?String(info.zooms[0]):"";reset();
  }};
}
