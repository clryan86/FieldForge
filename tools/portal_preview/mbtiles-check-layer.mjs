export function mbCheckState(tile) {
  if(tile.status==="missing")return "missing";
  if(tile.status==="unsupported")return "unsupported";
  if(tile.decode_status==="unreadable")return "unreadable";
  if(tile.status==="present"&&tile.decode_status==="decoded")return "decoded";
  return "unchecked";
}

// Match exact XYZ coordinates only at the checked zoom. View slots already
// encode world wrapping; repeated copies receive the same result independently.
export function projectMBCheckLayer(report,frame,hideDecoded=false) {
  if(!report||!frame||report.zoom!==frame.zoom)return [];
  const lookup=new Map(report.tiles.map(tile=>[`${tile.x}/${tile.y}`,tile])),cells=[];
  for(const slot of frame.tiles){
    if(slot.outside)continue;
    const tile=lookup.get(`${slot.x}/${slot.y}`);if(!tile)continue;
    const state=mbCheckState(tile);if(hideDecoded&&state==="decoded")continue;
    if(slot.left>=768||slot.top>=512||slot.left+256<=0||slot.top+256<=0)continue;
    cells.push({x:slot.x,y:slot.y,left:slot.left,top:slot.top,state});
  }
  return cells;
}

export function drawMBCheckLayer(ctx,report,frame,hideDecoded=false,selected=null) {
  const cells=projectMBCheckLayer(report,frame,hideDecoded);
  if(!cells.length)return cells;
  const styles={missing:["#ff8585","rgba(255,90,90,.14)","M"],unsupported:["#dcb2ff","rgba(173,110,235,.14)","U"],unreadable:["#ffb86b","rgba(255,150,50,.14)","!"],unchecked:["#ffe28a","rgba(255,217,96,.10)","?"],decoded:["#83e4d2","rgba(90,205,180,.08)","D"]};
  ctx.save();ctx.beginPath();ctx.rect(0,0,768,512);ctx.clip();ctx.font="bold 12px system-ui";ctx.textAlign="left";ctx.textBaseline="top";
  for(const cell of cells){
    const [colour,fill,symbol]=styles[cell.state],x=cell.left,y=cell.top;
    ctx.fillStyle=fill;ctx.fillRect(x,y,256,256);ctx.strokeStyle=colour;ctx.lineWidth=2;ctx.setLineDash(cell.state==="unchecked"?[7,5]:[]);ctx.strokeRect(x+1,y+1,254,254);ctx.setLineDash([]);
    if(cell.state==="missing"||cell.state==="unreadable"){
      ctx.beginPath();ctx.moveTo(x+16,y+16);ctx.lineTo(x+240,y+240);
      if(cell.state==="missing"){ctx.moveTo(x+240,y+16);ctx.lineTo(x+16,y+240);}ctx.stroke();
    }
    if(selected&&selected.x===cell.x&&selected.y===cell.y){ctx.strokeStyle="#fff";ctx.lineWidth=3;ctx.strokeRect(x+5,y+5,246,246);}
    const left=Math.max(0,x),top=Math.max(0,y),width=Math.min(768,x+256)-left,height=Math.min(512,y+256)-top;
    if(width>=72&&height>=36){
      ctx.fillStyle="#10221c";ctx.fillRect(left+7,top+7,Math.min(206,width-14),23);
      ctx.fillStyle=colour;ctx.fillText(`${symbol} ${report.zoom}/${cell.x}/${cell.y}`,left+12,top+12,Math.min(194,width-26));
    }
  }
  ctx.restore();return cells;
}
