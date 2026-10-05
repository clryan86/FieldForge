"""Self-contained browser inspection of already decoded source geometry.

No routing, uploads, geolocation, persistent storage, or source execution. The
HTML contains precise source coordinates; handle a private extract accordingly.
"""
from __future__ import annotations

import html
import json
from dataclasses import asdict

from fieldforge.navigation.osm_source import StreetSource

MAX_HTML = 32 * 1024 * 1024
_SAMPLE = '40a25059d31a82521dcf49e3f1c9df385f1759b574d9bb1ca4ea37db91416992'


def street_preview_html(source: StreetSource) -> bytes:
    """Return an offline HTML copy. Values are inert JSON/text, never HTML markup."""
    payload = json.dumps(asdict(source), ensure_ascii=True, allow_nan=False, separators=(',', ':'))
    payload = payload.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    prefix = ('HISTORICAL FORMAT SAMPLE — not current map coverage. ' if source.sha256 == _SAMPLE else
              'LOCAL SOURCE COPY — source age and completeness are not verified. ')
    title = html.escape(source.source_name)
    result = (_TEMPLATE.replace('@@TITLE@@', title).replace('@@NOTICE@@', html.escape(prefix + source.notice))
              .replace('@@DATA@@', payload)).encode('utf-8')
    if len(result) > MAX_HTML:
        raise ValueError('Street preview exceeds the 32 MiB HTML limit; use a smaller extract.')
    return result


_TEMPLATE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>FieldForge • Street source preview</title><style>
:root{color-scheme:light;--ink:#193d32;--line:#ccd6cf;--bg:#f5f7f2}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}
header,main,footer{max-width:1360px;margin:auto;padding:20px 28px}.brand{font-size:13px;letter-spacing:2px;font-weight:800}
h1{font-size:32px;line-height:1.18;margin:12px 0}.notice{border-left:4px solid #a06f26;background:#fbf0db;padding:12px 16px;font-size:14px}
.meta{font-size:13px;overflow-wrap:anywhere}main{padding-top:0}.layout{display:grid;grid-template-columns:310px 1fr;gap:16px}
.panel{background:white;border:1px solid var(--line);border-radius:10px;padding:14px}.tools{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
button,input{font:inherit;padding:8px;border:1px solid #98aaa0;border-radius:6px}button{cursor:pointer;background:white;color:var(--ink)}button:focus-visible,input:focus-visible{outline:3px solid #7e4dad}
input{width:100%}#results{height:260px;overflow:auto;padding:0;list-style:none}#results button{text-align:left;border:0;border-bottom:1px solid var(--line);width:100%;border-radius:0}
#results small{display:block;color:#496c5b}pre{font:13px/1.5 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere}#detail{min-height:110px}
#map{display:block;width:100%;height:530px;background:#edf3ee;border:1px solid var(--line);touch-action:none;cursor:grab}#pointer,#counts,#render-status{font-size:13px}footer{font-size:13px;padding-top:0}
@media(max-width:760px){header,main,footer{padding:16px}.layout{grid-template-columns:1fr}#results{height:140px}#map{height:430px}h1{font-size:27px}}
@media print{header,main,footer{padding:10px}.layout{display:block}.search-panel,.tools{display:none}#map{height:500px}.notice{background:white}}
</style></head><body><header><div class="brand">FIELDFORGE / OFFLINE MAP DATA</div>
<h1>Street-source preview</h1><p>@@TITLE@@</p><div class="notice">@@NOTICE@@</div>
<p class="meta" id="metadata"></p></header><main><div class="layout"><section class="panel search-panel">
<label for="search">Find a source name, type, or ID</label><input id="search" maxlength="200" placeholder="Try Wellfield Road"><p id="counts"></p>
<ul id="results" aria-label="Source features"></ul><pre id="detail">Select a source feature. This is not an address search or a routing service.</pre>
</section><section class="panel"><div class="tools"><button id="fit">Fit all geometry</button><button id="minus" aria-label="Zoom out">−</button><button id="plus" aria-label="Zoom in">+</button></div>
<canvas id="map" tabindex="0" aria-label="Source geometry map. Search list gives feature names. Arrow keys pan; plus and minus zoom."></canvas>
<p id="pointer">Drag to pan. Use + / − or the mouse wheel to zoom. North is up.</p><p id="render-status">Blank areas and missing features do not establish open or safe passage.</p>
</section></div></main><footer>© OpenStreetMap contributors • Open Database License 1.0 • https://www.openstreetmap.org/copyright<br>
This unencrypted file contains source coordinates. No network, GPS, background download or automatic data storage is used. Keep the original source and its rights notices.</footer>
<noscript><p>Enable this file's built-in script to inspect the map. No network library is needed.</p></noscript>
<script>
'use strict';
const data=@@DATA@@;
const $=id=>document.getElementById(id),canvas=$('map'),ctx=canvas.getContext('2d');
const fold=s=>s.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const project=([lon,lat])=>[(lon+180)/360,(1-Math.asinh(Math.tan(lat*Math.PI/180))/Math.PI)/2];
const rows=data.features.map(f=>({...f,xy:f.geometry.map(project),search:fold(f.name+' '+f.kind+' '+f.id)}));
let cx=.5,cy=.5,z=10,selected=null,drag=null,w=800,h=530;
$('metadata').textContent=data.nodes+' nodes · '+data.ways+' ways · '+data.features.length+' preview features · '+data.relations+' relations NOT drawn · '+data.missing_node_ways+' ways omitted for missing nodes. Snapshot date: '+(data.replication_timestamp===null?'unknown':new Date(data.replication_timestamp*1000).toISOString())+'. SHA-256: '+data.sha256;
function fit(features){
 const points=features.flatMap(f=>f.xy);if(!points.length){draw();return;}
 const xs=points.map(p=>(p[0]%1+1)%1).sort((a,b)=>a-b);let gap=-1,start=0;
 for(let i=0;i<xs.length;i++){const next=xs[(i+1)%xs.length]+(i===xs.length-1?1:0),d=next-xs[i];if(d>gap){gap=d;start=next%1;}}
 let ymin=1,ymax=0;for(const p of points){ymin=Math.min(ymin,p[1]);ymax=Math.max(ymax,p[1]);}
 cx=(start+(1-gap)/2)%1;cy=(ymin+ymax)/2;
 z=Math.max(0,Math.min(18,Math.floor(Math.log2(Math.min(Math.max(1,w-90)/Math.max(1e-9,1-gap),Math.max(1,h-90)/Math.max(1e-9,ymax-ymin))/256))));draw();
}
function draw(){
 const scale=256*Math.pow(2,z);ctx.clearRect(0,0,w,h);let vertices=0,omitted=0,labels=[];
 const ordered=rows.filter(f=>f.id!==selected).concat(rows.filter(f=>f.id===selected));
 for(const f of ordered){
  if(vertices+f.xy.length>20000){omitted++;continue;}vertices+=f.xy.length;
  const points=[];let last;
  for(const p of f.xy){let x=p[0];x+=Math.round((last===undefined?cx:last)-x);last=x;points.push([(x-cx)*scale+w/2,(p[1]-cy)*scale+h/2]);}
  const color=f.id===selected?'#733fa3':f.kind.startsWith('highway=')?'#a05a26':f.kind.startsWith('waterway=')?'#387ca8':'#6b816e';
  ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=f.id===selected?4:1.7;ctx.beginPath();
  if(points.length===1){ctx.arc(points[0][0],points[0][1],3,0,2*Math.PI);ctx.fill();}
  else{points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.stroke();}
  const p=points[Math.floor(points.length/2)];
  if(p&&f.name!==f.id&&labels.length<70&&p[0]>0&&p[0]<w-40&&p[1]>35&&p[1]<h&&labels.every(a=>Math.abs(a[0]-p[0])>90||Math.abs(a[1]-p[1])>20)){
   ctx.font='12px system-ui';ctx.fillStyle='#193d32';ctx.fillText(f.name.slice(0,60),p[0]+5,p[1]-8);labels.push(p);
  }
 }
 ctx.fillStyle='#edf3ee';ctx.fillRect(0,0,w,30);ctx.fillStyle='#193d32';ctx.font='12px system-ui';ctx.fillText('SOURCE GEOMETRY / NOT NAVIGATION / ZOOM '+z,12,19);
 $('render-status').textContent=omitted?'Display budget: '+omitted+' features are not drawn. The source list is unchanged. Use a smaller extract.':'Blank areas and missing features do not establish open or safe passage.';
}
function resize(){const box=canvas.getBoundingClientRect();w=Math.min(1800,Math.max(100,box.width));h=Math.min(1000,Math.max(100,box.height));const ratio=Math.min(2,window.devicePixelRatio||1);canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);draw();}
function search(){const terms=fold($('search').value).split(/\s+/).filter(Boolean),matches=rows.filter(f=>terms.every(t=>f.search.includes(t)));$('results').replaceChildren();$('counts').textContent=Math.min(100,matches.length)+' of '+matches.length+' matches shown';
 for(const f of matches.slice(0,100)){const li=document.createElement('li'),button=document.createElement('button'),small=document.createElement('small');button.textContent=f.name;small.textContent=f.kind;button.appendChild(small);button.addEventListener('click',()=>{selected=f.id;$('detail').textContent=f.name+'\n'+f.id+'\n\n'+f.tags.map(t=>t[0]+': '+t[1]).join('\n')+'\n\nSource tags only. Access and restrictions are not enforced.';fit([f]);});li.appendChild(button);$('results').appendChild(li);}}
function zoom(delta){z=Math.max(0,Math.min(22,z+delta));draw();}
$('search').addEventListener('input',search);$('fit').addEventListener('click',()=>fit(rows));$('minus').addEventListener('click',()=>zoom(-1));$('plus').addEventListener('click',()=>zoom(1));
canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);canvas.focus();});
canvas.addEventListener('pointermove',e=>{if(!drag)return;const scale=256*Math.pow(2,z);cx=(cx+(drag[0]-e.clientX)/scale+1)%1;cy=Math.max(0,Math.min(1,cy+(drag[1]-e.clientY)/scale));drag=[e.clientX,e.clientY];draw();});
canvas.addEventListener('pointerup',()=>drag=null);canvas.addEventListener('pointercancel',()=>drag=null);
canvas.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY<0?1:-1);},{passive:false});
canvas.addEventListener('keydown',e=>{const d={ArrowLeft:[-70,0],ArrowRight:[70,0],ArrowUp:[0,-70],ArrowDown:[0,70]}[e.key];if(d){e.preventDefault();cx=(cx+d[0]/(256*2**z)+1)%1;cy=Math.max(0,Math.min(1,cy+d[1]/(256*2**z)));draw();}else if(e.key==='+'||e.key==='=')zoom(1);else if(e.key==='-')zoom(-1);});
window.addEventListener('resize',resize);resize();search();fit(rows);
</script></body></html>'''
