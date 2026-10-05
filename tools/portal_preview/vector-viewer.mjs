import {MAX_VECTOR_BYTES, parseGeoJSON, projectVectors, vectorPath, vectorPlace, vectorLabel, selectedGeoJSON} from "./vector-core.mjs";
import {clampView} from "./desk-core.mjs";

export function createVectorViewer({download,onAddPoint}) {
  const id = key => document.getElementById(key), ns = "http://www.w3.org/2000/svg";
  const node = (tag,text) => { const element=document.createElement(tag); if(text!==undefined) element.textContent=text; return element; };
  const svg = (tag,attrs) => { const element=document.createElementNS(ns,tag); for(const [key,value] of Object.entries(attrs)) element.setAttribute(key,value); return element; };
  let data=null,projected=null,filename="",generation=0,selected=-1,vertex=0,groups=[],marker=null,view=clampView(1,400,190);
  const status = (text,error=false) => { id("vectorStatus").textContent=text; id("vectorStatus").classList.toggle("error",error); };
  function updateView() {
    id("vectorSvg").setAttribute("viewBox",view.box.join(" ")); id("vectorZoomLevel").textContent=`${view.zoom.toFixed(1)}×`;
    id("vectorZoomIn").disabled=!data||view.zoom>=8; id("vectorZoomOut").disabled=!data||view.zoom<=1; id("vectorFit").disabled=!data;
    for(const key of ["vectorLeft","vectorRight","vectorUp","vectorDown"]) id(key).disabled=!data||view.zoom<=1;
    if(marker) marker.setAttribute("r",7/view.zoom);
  }
  function updateVertex() {
    const feature=data?.features[selected], count=feature?.vertices.length || 0;
    vertex=Math.max(0,Math.min(count-1,vertex));
    id("vectorVertex").max=Math.max(0,count-1); id("vectorVertex").value=vertex; id("vectorVertex").disabled=!count;
    id("vectorPrevious").disabled=!count||vertex===0; id("vectorNext").disabled=!count||vertex===count-1;
    id("vectorAddPlace").disabled=!count; id("vectorSaveFeature").disabled=!feature;
    id("vectorVertexCount").textContent=count ? `Vertex ${vertex+1} of ${count} · file order, including ring closing points` : "No coordinate selected";
    id("vectorLatitude").textContent=count ? feature.vertices[vertex][1].toFixed(7) : "—";
    id("vectorLongitude").textContent=count ? feature.vertices[vertex][0].toFixed(7) : "—";
    if(marker) { marker.remove(); marker=null; }
    if(count) { const [x,y]=projected.features[selected].vertices[vertex]; marker=svg("circle",{cx:x,cy:y,r:7/view.zoom,fill:"none",stroke:"#fff","stroke-width":2,"vector-effect":"non-scaling-stroke","pointer-events":"none"}); id("vectorMarker").replaceChildren(marker); }
    else id("vectorMarker").replaceChildren();
  }
  function select(index) {
    selected=Number.isInteger(index)&&data?.features[index] ? index : -1; vertex=0;
    const feature=data?.features[selected];
    id("vectorFeature").value=selected<0 ? "" : String(selected);
    id("vectorSelectedName").textContent=feature ? feature.label : "Choose a feature";
    id("vectorSelectedType").textContent=feature ? feature.type : "Points, lines and polygons";
    groups.forEach((group,i) => group.setAttribute("class",i===selected ? "vector-shape selected" : "vector-shape"));
    const properties=id("vectorProperties"); properties.replaceChildren();
    const entries=Object.entries(feature?.feature.properties||{});
    for(const [key,value] of entries.slice(0,20)) {
      const text=value===null ? "null" : typeof value==="object" ? (Array.isArray(value) ? `Array (${value.length} items; kept in export)` : "Object (kept in export)") : vectorLabel(String(value),"(empty)",512);
      properties.append(node("dt",vectorLabel(key,"(unnamed)",120)),node("dd",text));
    }
    id("vectorPropertyNote").textContent=entries.length ? `Showing ${Math.min(20,entries.length)} of ${entries.length} properties. Long values are shortened; export retains the original properties.` : "No properties on this feature.";
    updateVertex();
  }
  function filterFeatures(preferred=selected) {
    const query=id("vectorSearch").value.trim().toLocaleLowerCase();
    const matches=data ? data.features.map((feature,index)=>({feature,index})).filter(({feature})=>(feature.label+" "+feature.type).toLocaleLowerCase().includes(query)) : [];
    const picker=id("vectorFeature"); picker.replaceChildren();
    if(!matches.length) { const option=node("option","No matching feature"); option.value=""; picker.append(option); }
    for(const {feature,index} of matches) { const option=node("option",`${index+1}. ${feature.label} · ${feature.type}`); option.value=String(index); picker.append(option); }
    picker.disabled=!matches.length; id("vectorMatchCount").textContent=`${matches.length} matching / ${data?.features.length||0} total · list filter only`;
    select(matches.some(item=>item.index===preferred) ? preferred : matches[0]?.index ?? -1);
  }
  function clear(message="File cleared from this tab. Places already collected and exported files remain.") {
    generation++; data=null; projected=null; selected=-1; filename=""; groups=[]; marker=null; vertex=0; view=clampView(1,400,190);
    id("vectorFile").value=""; id("vectorSearch").value=""; id("vectorSearch").disabled=true; id("vectorClear").disabled=true;
    id("vectorDrawing").replaceChildren(); id("vectorMarker").replaceChildren(); id("vectorEmpty").removeAttribute("display");
    id("vectorFileName").textContent="Your vector layer"; id("vectorOverview").textContent="No file loaded"; id("vectorBounds").textContent="—";
    id("vectorSvgDesc").textContent="Load a local GeoJSON layer to inspect its points, lines and polygons. No basemap or routing.";
    filterFeatures(); updateView(); status(message);
  }
  function render() {
    projected=projectVectors(data); groups=[]; const fragment=document.createDocumentFragment();
    for(const [index,feature] of projected.features.entries()) {
      const group=svg("g",{"class":"vector-shape"}), title=svg("title",{}); title.textContent=data.features[index].label; group.append(title);
      for(const shape of feature.shapes) {
        const element=shape.kind==="point" ? svg("circle",{cx:shape.coordinates[0],cy:shape.coordinates[1],r:4,"class":"vector-point"}) : svg("path",{d:vectorPath(shape),"class":`vector-${shape.kind}`,"fill-rule":"evenodd","vector-effect":"non-scaling-stroke"});
        group.append(element);
      }
      group.addEventListener("click",()=> { id("vectorSearch").value=""; filterFeatures(index); }); groups.push(group); fragment.append(group);
    }
    id("vectorDrawing").replaceChildren(fragment); id("vectorEmpty").setAttribute("display","none");
    id("vectorFileName").textContent=filename; id("vectorOverview").textContent=`${data.features.length} features · ${data.positions} positions · ${data.unlocated} without geometry`;
    const b=projected.bounds; id("vectorBounds").textContent=`West ${b.west.toFixed(5)}° · East ${b.east.toFixed(5)}° · South ${b.south.toFixed(5)}° · North ${b.north.toFixed(5)}°`;
    id("vectorSvgDesc").textContent=`GeoJSON coordinate layer with ${data.features.length} features. North up; linear longitude and latitude. Choose a feature in the list for coordinates and properties.`;
    id("vectorSearch").disabled=false; filterFeatures(data.features.findIndex(feature=>feature.vertices.length)); updateView();
  }
  id("vectorFile").addEventListener("change",async()=> {
    const file=id("vectorFile").files[0]; if(!file) return;
    clear("Reading your GeoJSON on this device…"); const token=generation; id("vectorClear").disabled=false;
    try {
      if(!file.size||file.size>MAX_VECTOR_BYTES) throw new Error("Choose a nonempty GeoJSON file no larger than 4 MiB.");
      const bytes=await file.arrayBuffer(); if(token!==generation) return;
      let text; try { text=new TextDecoder("utf-8",{fatal:true}).decode(bytes); } catch { throw new Error("GeoJSON must use UTF-8 text encoding."); }
      const parsed=parseGeoJSON(text); data=parsed; filename=file.name; render();
      status("Vector layer opened locally. Coordinates and properties come from your file; their accuracy has not been independently checked.");
    } catch(error) { if(token===generation) { clear(); status(error.message||"Could not open this file.",true); } }
  });
  id("vectorClear").addEventListener("click",()=>clear());
  id("vectorSearch").addEventListener("input",()=>filterFeatures());
  id("vectorFeature").addEventListener("change",()=>select(id("vectorFeature").value==="" ? -1 : Number(id("vectorFeature").value)));
  id("vectorVertex").addEventListener("input",()=> { vertex=Number(id("vectorVertex").value); if(!Number.isInteger(vertex)) vertex=0; updateVertex(); });
  for(const [key,delta] of [["vectorPrevious",-1],["vectorNext",1]]) id(key).addEventListener("click",()=> { vertex+=delta; updateVertex(); });
  id("vectorAddPlace").addEventListener("click",()=> { try { if(data?.features[selected]) onAddPoint(vectorPlace(data.features[selected],vertex,filename)); } catch(error) { status(error.message,true); } });
  id("vectorSaveFeature").addEventListener("click",()=> { try { if(data?.features[selected]) { download(selectedGeoJSON(data.features[selected]),"application/geo+json","fieldforge-selected-feature.geojson"); status("Selected feature saved with its original geometry, properties and optional ID. It contains coordinates and properties in plain text."); } } catch(error) { status("This feature could not be exported. Keep the original file.",true); } });
  for(const [key,factor] of [["vectorZoomIn",1.5],["vectorZoomOut",1/1.5]]) id(key).addEventListener("click",()=> { if(!data) return; const center=factor>1&&selected>=0 ? projected.features[selected].vertices[vertex] : null; view=clampView(view.zoom*factor,...(center||[view.x,view.y])); updateView(); });
  id("vectorFit").addEventListener("click",()=> { view=clampView(1,400,190); updateView(); });
  for(const [key,dx,dy] of [["vectorLeft",-1,0],["vectorRight",1,0],["vectorUp",0,-1],["vectorDown",0,1]]) id(key).addEventListener("click",()=> { if(data) { view=clampView(view.zoom,view.x+dx*view.width*.2,view.y+dy*view.height*.2); updateView(); } });
  clear("No file loaded. Choose a local GeoJSON layer to begin.");
}
