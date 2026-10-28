export function createMBCoverage({onScan,onOpen}) {
  const id=key=>document.getElementById(key);let report=null,hasPack=false,busy=false,selection=-1,rects=[];
  const node=(tag,text)=>{const el=document.createElement(tag);el.textContent=text;return el;};
  function controls(){id("mbCoverageControls").disabled=!hasPack||busy;id("mbCoverageAreas").disabled=busy||!report?.cells.length;id("mbCoverageOpen").disabled=busy||selection<0;}
  function select(index){
    selection=Number.isInteger(index)&&report?.cells[index]?index:-1;id("mbCoverageAreas").value=String(selection);
    rects.forEach((rect,i)=>{rect.setAttribute("fill",i===selection?"#f0c66b":"#77aa88");rect.setAttribute("stroke",i===selection?"#ffe9ae":"#c7dfc7");});
    if(selection<0)id("mbCoverageSelected").textContent="No stored area selected.";
    else {const cell=report.cells[selection],p=cell.sample;id("mbCoverageSelected").textContent=`${cell.count.toLocaleString()} indexed tile${cell.count===1?"":"s"} in this area. Jump target: ${p.lat.toFixed(5)}, ${p.lon.toFixed(5)} · tile ${report.zoom}/${p.x}/${p.y} (XYZ).`;}
    controls();
  }
  function reset(){report=null;hasPack=false;selection=-1;rects=[];id("mbCoverageZoom").replaceChildren();id("mbCoverageDrawing").replaceChildren();id("mbCoverageAreas").replaceChildren();id("mbCoverageResult").hidden=true;id("mbCoverageStatus").textContent="Open a pack, then inspect one of its stored zoom levels.";id("mbCoverageSelected").textContent="No stored area selected.";controls();}
  function setPack(info){reset();hasPack=true;for(const z of info.zooms){const option=node("option",`Zoom ${z}`);option.value=String(z);id("mbCoverageZoom").append(option);}id("mbCoverageZoom").value=String(info.initial.zoom);controls();}
  function show(result){
    report=result;selection=-1;rects=[];id("mbCoverageDrawing").replaceChildren();id("mbCoverageAreas").replaceChildren();id("mbCoverageResult").hidden=false;
    id("mbCoverageStatus").textContent=`Zoom ${result.zoom} · ${result.valid.toLocaleString()} indexed tile locations · ${result.cells.length.toLocaleString()} occupied overview areas. `+(result.partial?`Partial scan: first ${result.limit.toLocaleString()} rows only; more remain.`:"Complete index scan at this zoom.")+(result.invalid?` ${result.invalid.toLocaleString()} invalid coordinate rows skipped.`:"");
    for(const [i,cell] of result.cells.entries()){
      const label=`Area ${i+1} · ${cell.count.toLocaleString()} tile${cell.count===1?"":"s"} · near ${cell.sample.lat.toFixed(2)}, ${cell.sample.lon.toFixed(2)}`,option=node("option",label);option.value=String(i);id("mbCoverageAreas").append(option);
      const rect=document.createElementNS("http://www.w3.org/2000/svg","rect");for(const [key,value] of Object.entries({x:cell.column,y:cell.row,width:cell.span,height:cell.span,"stroke-width":.12}))rect.setAttribute(key,String(value));
      const title=document.createElementNS("http://www.w3.org/2000/svg","title");title.textContent=label;rect.append(title);rect.addEventListener("click",()=>{if(!busy)select(i);});rects.push(rect);id("mbCoverageDrawing").append(rect);
    }
    select(result.cells.length?0:-1);
  }
  id("mbCoverageScan").addEventListener("click",()=>{if(!hasPack||busy)return;return onScan(Number(id("mbCoverageZoom").value));});
  id("mbCoverageAreas").addEventListener("change",()=>{if(!busy)select(Number(id("mbCoverageAreas").value));});
  id("mbCoverageOpen").addEventListener("click",()=>{if(busy||selection<0)return;const sample=report.cells[selection].sample;return onOpen(sample.lat,sample.lon,report.zoom);});
  reset();return {reset,setPack,show,setBusy(value){busy=value;controls();},reading(zoom){id("mbCoverageStatus").textContent=`Reading the local tile index at zoom ${zoom}…`;}};
}
