import {MAX_MB_BYTES, MB_LAT_LIMIT, checkMBHeader, mbFrame, mbUnproject} from "./mbtiles-core.mjs";
import {createMBClient, createMBFileRead} from "./mbtiles-client.mjs";
import {imageHeader} from "./image-core.mjs";
import {vectorLabel} from "./vector-core.mjs";
import {drawVectorTiles} from "./mvt-renderer.mjs";

export function createMBViewer({onAddPoint,clientFactory=createMBClient}) {
  const id=key=>document.getElementById(key),canvas=id("mbCanvas"),ctx=canvas.getContext("2d");
  let client=null,fileRead=null,info=null,frame=null,selected=null,bitmaps=[],vectors=[],generation=0,busy=false,filename="";
  const status=(text,error=false)=>{id("mbStatus").textContent=text;id("mbStatus").classList.toggle("error",error);};
  const node=(tag,text)=>{const element=document.createElement(tag);if(text!==undefined)element.textContent=text;return element;};
  function controls() {id("mbControls").disabled=!info||busy;id("mbAddPlace").disabled=!selected||busy;id("mbPixelControls").disabled=!frame||busy;}
  function dispose() {for(const item of bitmaps)item.bitmap.close();bitmaps=[];vectors=[];frame=null;selected=null;id("mbSelected").textContent="No tile pixel selected";id("mbTileSummary").textContent="No frame loaded";id("mbIssues").textContent="";ctx?.clearRect(0,0,768,512);controls();}
  function clear(message="Map pack closed. Collected places and your original file are unchanged.") {
    generation++;fileRead?.cancel();fileRead=null;client?.close();client=null;info=null;busy=false;filename="";dispose();
    id("mbFile").value="";id("mbClose").disabled=true;id("mbName").textContent="Local MBTiles map";id("mbAttribution").textContent="Attribution will appear here from your map pack.";
    id("mbDescription").textContent="";id("mbZoom").replaceChildren();id("mbLatitude").value="";id("mbLongitude").value="";id("mbColumn").value="384";id("mbRow").value="256";
    id("mbVectorNote").hidden=true;id("mbPointNames").checked=true;status(message);
  }
  if(!ctx) {id("mbFile").disabled=true;status("This browser cannot draw the local map canvas.",true);return;}
  function draw() {
    ctx.clearRect(0,0,768,512);if(!frame)return;
    ctx.fillStyle="#102c23";ctx.fillRect(0,0,768,512);ctx.font="13px system-ui";ctx.textAlign="center";
    for(const tile of frame.tiles) {ctx.strokeStyle="#466052";ctx.strokeRect(tile.left,tile.top,256,256);if(tile.issue){ctx.fillStyle="#b5c9bb";ctx.fillText(tile.issue,tile.left+128,tile.top+128,232);}}
    for(const item of bitmaps)ctx.drawImage(item.bitmap,item.tile.left,item.tile.top,256,256);
    if(vectors.length)drawVectorTiles(ctx,vectors,id("mbPointNames").checked);
    if(selected){const x=selected.column+.5,y=selected.row+.5;ctx.beginPath();ctx.arc(x,y,7,0,Math.PI*2);ctx.moveTo(x-12,y);ctx.lineTo(x+12,y);ctx.moveTo(x,y-12);ctx.lineTo(x,y+12);ctx.strokeStyle="#142d22";ctx.lineWidth=4;ctx.stroke();ctx.strokeStyle="#ffe2a6";ctx.lineWidth=2;ctx.stroke();ctx.lineWidth=1;}
  }
  function select(column,row) {
    if(!frame||busy)return;
    if(!Number.isInteger(column)||!Number.isInteger(row)||column<0||column>=768||row<0||row>=512)throw new Error("Choose a pixel column 0–767 and row 0–511.");
    const hit=[...bitmaps.map(item=>item.tile),...vectors].find(tile=>column+.5>=tile.left&&column+.5<tile.left+256&&row+.5>=tile.top&&row+.5<tile.top+256);
    selected=null;
    if(hit){const point=mbUnproject(frame.left+column+.5,frame.top+row+.5,frame.zoom);selected={...point,column,row};id("mbSelected").textContent=`${point.lat.toFixed(7)}, ${point.lon.toFixed(7)} · tile ${frame.zoom}/${hit.x}/${hit.y} (XYZ)`;}
    else id("mbSelected").textContent="No decoded tile under this pixel; no coordinate selected.";
    id("mbColumn").value=column;id("mbRow").value=row;draw();controls();
  }
  async function show(lat,lon,zoom) {
    if(!client||!info||busy)return;
    try {mbFrame(lat,lon,zoom);if(!info.zooms.includes(zoom))throw new Error("Choose an available zoom from this pack.");}catch(error){status(error.message,true);return;}
    busy=true;const token=generation;dispose();controls();status("Reading map tiles on this device…");
    const loaded=[];
    try {
      const result=await client.request("frame",{lat,lon,zoom});if(token!==generation)return;
      for(const tile of result.tiles) {
        if(!tile.data)continue;
        let bitmap=null;
        try {
          const header=imageHeader(tile.data),expected=info.format==="png" ? "PNG" : info.format==="webp" ? "WebP" : "JPEG";
          if(header.format!==expected||header.width!==header.height||![256,512].includes(header.width))throw new Error("Unsupported tile encoding/dimensions");
          bitmap=await createImageBitmap(new Blob([tile.data],{type:header.mime}),{imageOrientation:"none"});
          if(token!==generation){bitmap.close();return;}
          if(bitmap.width!==header.width||bitmap.height!==header.height)throw new Error("Tile dimensions disagree");
          loaded.push({bitmap,tile});bitmap=null;
        } catch(error) {bitmap?.close();tile.issue="Unreadable / unsupported tile";}
        delete tile.data;
        if(token!==generation)return;
      }
      if(token!==generation)return;
      frame=result;bitmaps=loaded.splice(0);vectors=result.tiles.filter(tile=>tile.vector);busy=false;
      id("mbLatitude").value=String(lat);id("mbLongitude").value=String(lon);id("mbZoom").value=String(zoom);
      id("mbTileSummary").textContent=`Zoom ${zoom} · ${bitmaps.length+vectors.length} decoded / ${frame.tiles.length} view slots`+(result.vectorStats?` · ${result.vectorStats.features.toLocaleString()} features in view slots · basic vector style`:"");
      id("mbIssues").textContent=[...new Set(frame.tiles.filter(tile=>tile.issue).map(tile=>tile.issue))].join(" · ");
      select(384,256);status("Map tiles read locally. Missing tiles or undrawn details do not indicate safe or empty terrain. No routing, GPS or current-condition checks.");
    } catch(error) {if(token===generation){clear();status(error.message||"Could not read this map frame.",true);}}
    finally {for(const item of loaded)item.bitmap.close();if(token===generation){busy=false;controls();}}
  }
  id("mbFile").addEventListener("change",async()=> {
    const file=id("mbFile").files[0];if(!file)return;clear("Opening your MBTiles pack locally…");const token=generation;busy=true;id("mbClose").disabled=false;
    try {
      if(token!==generation)return;
      if(!file.size||file.size>MAX_MB_BYTES||!file.name.toLowerCase().endsWith(".mbtiles"))throw new Error("Choose a .mbtiles export no larger than 64 MiB. Compatible larger packs can use the desktop map viewer.");
      const read=createMBFileRead(file);fileRead=read;let bytes;
      try {bytes=await read.promise;}finally{if(fileRead===read)fileRead=null;}
      if(token!==generation)return;checkMBHeader(new Uint8Array(bytes));client=clientFactory();
      const result=await client.request("open",{bytes},[bytes]);if(token!==generation)return;
      if(result.format!=="pbf"&&typeof createImageBitmap!=="function")throw new Error("This browser needs ImageBitmap support to decode raster map tiles.");
      info=result;filename=file.name;busy=false;
      id("mbVectorNote").hidden=info.format!=="pbf";
      id("mbName").textContent=vectorLabel(info.name,"Local map pack",160);id("mbAttribution").textContent=info.attribution;id("mbDescription").textContent=info.description;
      id("mbZoom").replaceChildren();for(const z of info.zooms){const option=node("option",`Zoom ${z}`);option.value=String(z);id("mbZoom").append(option);}
      await show(info.initial.lat,info.initial.lon,info.initial.zoom);
    } catch(error) {if(token===generation){clear();status(error.message||"The pack could not be opened.",true);}}
  });
  id("mbClose").addEventListener("click",()=>clear());
  id("mbPointNames").addEventListener("change",()=>draw());
  id("mbGo").addEventListener("submit",event=> {event.preventDefault();if(!info||busy)return;try {const lat=id("mbLatitude").value.trim(),lon=id("mbLongitude").value.trim();if(!lat||!lon)throw new Error("Enter both latitude and longitude; a blank field is not zero.");show(Number(lat),Number(lon),Number(id("mbZoom").value));}catch(error){status(error.message,true);}});
  id("mbHome").addEventListener("click",()=> {if(info&&!busy)show(info.initial.lat,info.initial.lon,info.initial.zoom);});
  for(const [key,dx,dy] of [["mbLeft",-384,0],["mbRight",384,0],["mbUp",0,-256],["mbDown",0,256]])id(key).addEventListener("click",()=> {if(!frame||busy)return;const p=mbUnproject(frame.left+384+dx,frame.top+256+dy,frame.zoom);show(Math.max(-MB_LAT_LIMIT,Math.min(MB_LAT_LIMIT,p.lat)),p.lon,frame.zoom);});
  id("mbPixelForm").addEventListener("submit",event=> {event.preventDefault();try{const col=id("mbColumn").value.trim(),row=id("mbRow").value.trim();if(!col||!row)throw new Error("Enter a pixel column and row.");select(Number(col),Number(row));}catch(error){status(error.message,true);}});
  canvas.addEventListener("click",event=> {if(!frame||busy)return;const rect=canvas.getBoundingClientRect();if(rect.width&&rect.height){const col=Math.floor((event.clientX-rect.left)/rect.width*768),row=Math.floor((event.clientY-rect.top)/rect.height*512);if(col>=0&&col<768&&row>=0&&row<512)select(col,row);}});
  id("mbAddPlace").addEventListener("click",()=> {if(!selected||busy)return;try{onAddPoint({name:`Map pixel ${selected.column}, ${selected.row}`,lat:selected.lat,lon:selected.lon,source:`User-supplied ${info.format==="pbf"?"vector MBTiles, basic preview style":"raster MBTiles"}; Web Mercator pixel centre; not independently verified; file: ${vectorLabel(filename,"map pack",160)}`});}catch(error){status(error.message,true);}});
  clear("No pack opened. Choose a trusted, closed raster or vector MBTiles export.");
}
