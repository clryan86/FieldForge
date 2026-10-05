// Fixed local preview style. No downloaded styles, fonts, sprites or property CSS.
const mvtPalette={water:["#9bc7d6","#6497aa"],green:["#c4d2ad","#9bad88"],building:["#d7c8b5","#a99a87"],major:["#edc679","#897957"],road:["#f5efe0","#a39983"],boundary:["#dfd2e0","#9c809f"],rail:["#e1ddd2","#807e77"],minor:["#d5d9c5","#87967f"]};
function mvtPath(ctx,paths,closed) {
  ctx.beginPath();for(const path of paths){ctx.moveTo(...path[0]);for(let i=1;i<path.length;i++)ctx.lineTo(...path[i]);if(closed)ctx.closePath();}
}
export function drawVectorTiles(ctx,tiles,showLabels=true) {
  const labels=[],boxes=[];
  // All geometry first: names remain visible when adjacent tiles are painted.
  for(const tile of tiles){ctx.save();ctx.beginPath();ctx.rect(tile.left,tile.top,256,256);ctx.clip();ctx.translate(tile.left,tile.top);ctx.fillStyle="#e6e6d9";ctx.fillRect(0,0,256,256);ctx.lineJoin="round";ctx.lineCap="round";
    for(const type of [3,2,1])for(const feature of tile.vector.features){if(feature.type!==type)continue;const [fill,stroke]=mvtPalette[feature.style]||mvtPalette.minor;
      if(type===3){mvtPath(ctx,feature.paths,true);ctx.fillStyle=fill;ctx.fill("evenodd");ctx.strokeStyle=stroke;ctx.lineWidth=.6;ctx.stroke();}
      else if(type===2){mvtPath(ctx,feature.paths,false);ctx.strokeStyle=stroke;ctx.lineWidth=feature.style==="major"?4:feature.style==="road"?2.5:1;ctx.setLineDash(feature.style==="boundary"?[5,3]:feature.style==="rail"?[3,2]:[]);ctx.stroke();if(["major","road"].includes(feature.style)){ctx.strokeStyle=fill;ctx.lineWidth-=1.4;ctx.stroke();}ctx.setLineDash([]);}
      else {let named=false;for(const path of feature.paths){const [x,y]=path[0];ctx.beginPath();ctx.arc(x,y,2.5,0,Math.PI*2);ctx.fillStyle="#385246";ctx.fill();if(!named&&showLabels&&feature.label&&x>=0&&x<256&&y>=0&&y<256&&labels.length<384){labels.push({text:feature.label,x:x+tile.left+5,y:y+tile.top-5,tile});named=true;}}}
    }ctx.restore();
  }
  ctx.save();ctx.font="12px system-ui";ctx.textAlign="left";ctx.textBaseline="alphabetic";ctx.lineJoin="round";const counts=new Map();
  for(const label of labels){if(boxes.length>=96)break;if((counts.get(label.tile)||0)>=32)continue;const width=ctx.measureText(label.text).width,box={x:label.x-2,y:label.y-12,w:width+4,h:16};
    if(box.x<0||box.y<0||box.x+box.w>768||box.y+box.h>512||boxes.some(b=>box.x<b.x+b.w&&box.x+box.w>b.x&&box.y<b.y+b.h&&box.y+box.h>b.y))continue;
    boxes.push(box);counts.set(label.tile,(counts.get(label.tile)||0)+1);ctx.strokeStyle="#f8f8ee";ctx.lineWidth=3;ctx.strokeText(label.text,label.x,label.y);ctx.fillStyle="#273e32";ctx.fillText(label.text,label.x,label.y);
  }ctx.restore();return boxes.length;
}
