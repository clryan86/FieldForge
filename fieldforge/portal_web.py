"""Self-contained portal assets; no CDN, analytics, automatic searches or keys."""

HTML = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>FieldForge · Prepare online, use offline</title><link rel="stylesheet" href="/portal.css">
<script src="/portal.js" defer></script></head><body>
<header><a class="brand" href="/">FIELD<span>FORGE</span></a><span class="pill" id="mode">Offline mode</span></header>
<main><section class="intro"><p class="eyebrow">THE MAP PORTAL</p><h1>Prepare online.<br>Take it with you.</h1>
<p>Find coordinates, collect regional maps and save a planned route. Your downloaded files stay usable in FieldForge when the connection is gone.</p></section>
<section class="connection panel"><div><h2>A connection you control</h2><label><input id="consent" type="checkbox"> Send my entered searches and route coordinates to this portal and its configured providers.</label></div>
<button id="connect">Connect</button><button id="disconnect" class="secondary" disabled>Go offline</button>
<p id="status" role="status" aria-live="polite">Offline. Connect to enable address search, route planning and downloads.</p><p id="providers" class="muted"></p></section>
<div class="columns"><section class="panel"><p class="eyebrow">01 / FIND A PLACE</p><h2>Address → coordinates</h2>
<form id="search-form"><label for="query">Address or place, with city and country</label><div class="search"><input id="query" maxlength="300" placeholder="Enter an address while connected" disabled required><button id="search" disabled>Search</button></div></form>
<p class="muted">Search runs when you press Search. Results are possible matches, not a GPS fix.</p><div id="results" aria-live="polite"></div>
<div id="selected" hidden><h3 id="address-label"></h3><label for="coordinates">Latitude, longitude · WGS84</label><input id="coordinates" readonly>
<p id="address-source" class="muted"></p><div class="actions"><button id="copy" class="secondary">Copy coordinates</button><button id="save-address" class="secondary">Save place CSV</button><button id="use-start" class="secondary">Use as start</button><button id="use-end" class="secondary">Use as destination</button></div></div>
</section><section class="panel"><p class="eyebrow">02 / PLAN A JOURNEY</p><h2>Save a driving route</h2>
<form id="route-form"><fieldset id="route-fields" disabled><legend>WGS84 decimal degrees</legend><div class="coordinate-grid">
<label>Start latitude<input id="start-lat" required></label><label>Start longitude<input id="start-lon" required></label>
<label>Destination latitude<input id="end-lat" required></label><label>Destination longitude<input id="end-lon" required></label></div><button id="plan">Plan driving route</button></fieldset></form>
<p class="muted">Save the route geometry as GPX for offline review. Download its regional map separately. No offline rerouting or live road conditions.</p>
<div id="route-result" hidden><svg id="route-sketch" viewBox="0 0 440 180" role="img" aria-label="Planned route shape, not a basemap"></svg><p id="route-summary"></p><p id="route-source" class="muted"></p><button id="save-route">Save planned GPX</button></div>
</section></div>
<section class="panel maps"><div class="section-title"><div><p class="eyebrow">03 / YOUR OFFLINE MAPS</p><h2>Available map packs</h2></div><button id="refresh" class="secondary" disabled>Refresh catalogue</button></div>
<p>Only packs published by this portal appear here. Coverage, age, format and attribution travel with each file.</p><p class="muted">FieldForge's desktop downloader verifies the file automatically. For a browser download, retain the source note and compare its SHA-256 before opening.</p>
<div id="maps"><p class="muted">Connect to see available maps. Worldwide coverage is not bundled.</p></div></section>
<footer>FIELD FORGE / OFFLINE FIRST<p>Saved maps and places remain local. Address searches and route planning need this portal and its providers to be reachable.</p></footer></main></body></html>'''

CSS = '''*{box-sizing:border-box}body{margin:0;background:#f4f2ea;color:#183b32;font:16px/1.55 system-ui,sans-serif}header,main{max-width:1240px;margin:auto;padding:26px 34px}header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #c9d3c6}.brand{letter-spacing:.16em;font-weight:850;color:#163f33;text-decoration:none}.brand span{font-weight:400}.pill{font-size:.78rem;border:1px solid #a8b9aa;border-radius:30px;padding:6px 14px}.intro{max-width:750px;padding:28px 0 32px}.eyebrow{font-size:.7rem;letter-spacing:.2em;font-weight:750;color:#657868;margin:0 0 12px}h1{font-size:clamp(2.5rem,6vw,4.2rem);line-height:1.05;letter-spacing:-.05em;margin:0 0 24px}h2{font-size:1.35rem;letter-spacing:-.025em;margin:0 0 16px}h3{font-size:1rem;margin:18px 0 8px}p{margin:10px 0}.panel{padding:28px;background:#fffef9;border:1px solid #d9decf;border-radius:12px;min-width:0}.connection{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:24px}.connection>div{flex:1;min-width:250px}.connection p{flex-basis:100%;margin:0}.columns{display:grid;grid-template-columns:1fr 1fr;gap:24px}.muted{font-size:.83rem;color:#67746b}label{display:block;font-size:.85rem}input{font:inherit;color:inherit;border:1px solid #acb9ad;border-radius:6px;background:#fff;padding:10px 12px;max-width:100%;width:100%;margin:6px 0 12px}input[type=checkbox]{width:auto;margin:0 6px 0 0}button,a.download{font:600 .82rem system-ui;cursor:pointer;background:#235640;color:white;border:1px solid #235640;border-radius:6px;padding:11px 16px;white-space:nowrap;display:inline-block;text-decoration:none}button.secondary{background:transparent;color:#235640;border-color:#bcc9ba}button:disabled,input:disabled,fieldset:disabled{opacity:.48;cursor:default}button:focus-visible,input:focus-visible,a:focus-visible{outline:3px solid #d5a349;outline-offset:3px}.search{display:flex;gap:8px;align-items:center}.search input{margin-bottom:6px}.actions{display:flex;flex-wrap:wrap;gap:8px}.result{display:block;text-align:left;background:#f0f5ec;color:#183b32;border-color:#d4dfcf;white-space:normal;margin:8px 0;width:100%}.coordinate-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}fieldset{border:0;padding:0;margin:0}legend{font-size:.8rem;margin-bottom:8px;color:#67746b}#route-sketch{background:#e8efe3;border-radius:8px;width:100%;margin-top:18px}#route-sketch polyline{fill:none;stroke:#275f47;stroke-width:3;stroke-linejoin:round}.maps{margin-top:24px}.section-title{display:flex;justify-content:space-between;gap:16px;align-items:center}#maps{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-top:24px}.map-card{border-top:3px solid #9aae8f;padding:14px 0;overflow-wrap:anywhere}.map-card h3{margin-top:0}.map-card .actions{margin-top:12px}footer{padding:38px 0 16px;font-size:.75rem;letter-spacing:.13em;color:#687769}footer p{letter-spacing:0;max-width:720px}[hidden]{display:none!important}@media(max-width:760px){header,main{padding:20px}.columns{grid-template-columns:1fr}.panel{padding:20px}.connection{align-items:stretch}.section-title{align-items:flex-start;flex-direction:column}.search{align-items:stretch;flex-direction:column}.search button{margin-bottom:10px}}'''

SCRIPT = r'''"use strict";
const el = id => document.getElementById(id);
let online=false, busy=false, generation=0, controller=null, capabilities={}, chosen=null, route=null;
const onlineControls=["query","search","refresh"];
function controls(){
  el("connect").disabled=online||busy||!navigator.onLine;
  el("disconnect").disabled=!online&&!busy;
  el("consent").disabled=busy;
  for(const id of onlineControls) el(id).disabled=!online||busy||(id!=="refresh"&&!capabilities.geocoding);
  el("route-fields").disabled=!online||busy||!capabilities.routing;
  for(const a of document.querySelectorAll("a.download")){
    if(online&&!busy){a.href=a.dataset.url;a.removeAttribute("aria-disabled");}
    else {a.removeAttribute("href");a.setAttribute("aria-disabled","true");}
  }
  el("mode").textContent=online?"Connected":"Offline mode";
}
function disconnect(message="Offline. Saved files and selected coordinates remain available."){
  generation++;controller?.abort();controller=null;online=false;busy=false;capabilities={};
  el("status").textContent=message;controls();
}
async function request(path,payload){
  const options={signal:controller.signal,cache:"no-store",credentials:"omit",redirect:"error"};
  if(payload!==undefined){options.method="POST";options.headers={"Content-Type":"application/json"};options.body=JSON.stringify(payload);}
  const response=await fetch(path,options);
  if(!response.ok)throw Error(response.status===429?"Service busy. Wait before reconnecting.":"Portal request failed. Reconnect to try again.");
  return response.json();
}
async function operation(action){
  if(busy)return;busy=true;controller=new AbortController();const token=generation;controls();
  const timer=setTimeout(()=>controller?.abort(),30000);
  try{await action(()=>token===generation);}
  catch(error){if(token===generation)disconnect(error.name==="AbortError"?"Request timed out. Reconnect to try again.":error.message);}
  finally{clearTimeout(timer);if(token===generation){busy=false;controller=null;controls();}}
}
function save(name,content,type){const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function csv(value){return '"'+String(value).replaceAll('"','""')+'"';}
function decimal(value){
  const raw=String(value);if(!/[eE]/.test(raw))return raw;
  const [coefficient,power]=raw.toLowerCase().split("e"),negative=coefficient.startsWith("-");
  const unsigned=negative?coefficient.slice(1):coefficient,parts=unsigned.split("."),digits=parts.join("");
  const position=parts[0].length+Number(power);
  return (negative?"-":"")+(position<=0?"0."+"0".repeat(-position)+digits:
    position>=digits.length?digits+"0".repeat(position-digits.length):digits.slice(0,position)+"."+digits.slice(position));
}
function selectAddress(value){
  chosen=value;el("selected").hidden=false;el("address-label").textContent=value.label;
  el("coordinates").value=`${decimal(value.latitude)}, ${decimal(value.longitude)}`;
  el("address-source").textContent=`${value.source} · ${value.attribution}`;
}
function renderMaps(items){
  const target=el("maps");target.replaceChildren();
  if(!items.length){const p=document.createElement("p");p.textContent="No map packs published yet. The operator must add licensed regional files.";target.append(p);}
  for(const item of items){
    const card=document.createElement("article");card.className="map-card";
    const heading=document.createElement("h3");heading.textContent=item.title;card.append(heading);
    for(const value of [`${item.coverage} · ${item.kind.toUpperCase()} · ${(item.size/1048576).toFixed(1)} MiB`, `Updated: ${item.updated}`,item.source,item.attribution,item.license]){
      const p=document.createElement("p");p.className="muted";p.textContent=value;card.append(p);
    }
    const actions=document.createElement("div");actions.className="actions";
    const link=document.createElement("a");link.className="download";link.dataset.url=`/api/v1/maps/${encodeURIComponent(item.id)}/file`;link.download=item.filename;link.textContent="Download map";
    link.addEventListener("click",event=>{if(!online||busy)event.preventDefault();});actions.append(link);
    const note=document.createElement("button");note.className="secondary";note.textContent="Save source note";
    note.onclick=()=>save(item.filename+".source.json",JSON.stringify(item,null,2),"application/json");actions.append(note);card.append(actions);target.append(card);
  }
  controls();
}
el("connect").onclick=()=>{
  if(!el("consent").checked){el("status").textContent="Choose to send searches to this portal before connecting.";return;}
  operation(async current=>{const info=await request("/api/v1/status");if(!current())return;
    if(info.version!==1)throw Error("Unsupported portal version.");
    capabilities=info.capabilities;online=true;
    el("providers").textContent=Object.values(info.providers||{}).map(p=>`${p.name}: ${p.attribution}`).join(" · ");
    const maps=await request("/api/v1/maps");if(!current())return;renderMaps(maps.maps);
    el("status").textContent=`Connected to ${info.name}. ${capabilities.geocoding?"Address search ready.":"Address provider not configured."} ${capabilities.routing?"Driving routes ready.":"Route provider not configured."}`;
  });
};
el("disconnect").onclick=()=>disconnect();
el("consent").onchange=()=>{if(!el("consent").checked)disconnect();};
window.addEventListener("offline",()=>disconnect("Connection lost. Downloaded files remain usable offline."));
window.addEventListener("online",controls); // Never reconnect automatically.
el("search-form").onsubmit=event=>{event.preventDefault();if(!online||!capabilities.geocoding)return;
  const query=el("query").value.trim();if(!query)return;
  operation(async current=>{const data=await request("/api/v1/search",{query});if(!current())return;
    el("results").replaceChildren();
    for(const value of data.results){const button=document.createElement("button");button.className="result";button.textContent=`${value.label} — ${value.latitude}, ${value.longitude}`;button.onclick=()=>selectAddress(value);el("results").append(button);}
    el("status").textContent=data.results.length?"Choose a matching result before using its coordinates.":"No matching addresses. Add city or country and try again.";
  });
};
el("copy").onclick=async()=>{try{await navigator.clipboard.writeText(el("coordinates").value);el("status").textContent="Coordinates copied.";}catch{el("coordinates").select();el("status").textContent="Select and copy the coordinate field.";}};
el("save-address").onclick=()=>{if(chosen)save("fieldforge-place.csv",["name,latitude,longitude,source",[chosen.label,decimal(chosen.latitude),decimal(chosen.longitude),`${chosen.source}; ${chosen.attribution}; online address result`].map(csv).join(",")].join("\r\n")+"\r\n","text/csv;charset=utf-8");};
for(const [button,prefix] of [["use-start","start"],["use-end","end"]])el(button).onclick=()=>{if(chosen){el(prefix+"-lat").value=decimal(chosen.latitude);el(prefix+"-lon").value=decimal(chosen.longitude);}};
el("refresh").onclick=()=>{if(online)operation(async current=>{const data=await request("/api/v1/maps");if(current())renderMaps(data.maps);});};
function coord(id,limit){const raw=el(id).value.trim();if(!/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$/.test(raw))throw Error("Enter decimal coordinates in all four fields.");const n=Number(raw);if(!Number.isFinite(n)||Math.abs(n)>limit)throw Error("Coordinate is out of range.");return n;}
el("route-form").onsubmit=event=>{event.preventDefault();if(!online||!capabilities.routing)return;
  let payload;try{payload={start:[coord("start-lat",90),coord("start-lon",180)],end:[coord("end-lat",90),coord("end-lon",180)]};}catch(error){el("status").textContent=error.message;return;}
  operation(async current=>{const result=await request("/api/v1/route",payload);if(!current())return;route=result;
    el("route-result").hidden=false;el("route-summary").textContent=`Planned driving route · ${(route.distance_m/1000).toFixed(1)} km · ${Math.round(route.duration_s/60)} minutes estimated`;
    el("route-source").textContent=`${route.source} · ${route.attribution} · Requested ${route.created_at}`;
    const points=route.coordinates;const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
    const xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);
    const polyline=document.createElementNS("http://www.w3.org/2000/svg","polyline");
    polyline.setAttribute("points",points.map(p=>`${20+(p[0]-xmin)/(xmax-xmin||1)*400},${160-(p[1]-ymin)/(ymax-ymin||1)*140}`).join(" "));
    el("route-sketch").replaceChildren(polyline);el("status").textContent="Route ready to save. The sketch shows its shape, not current road conditions.";
  });
};
el("save-route").onclick=()=>{if(!route)return;const ns="http://www.topografix.com/GPX/1/1";const doc=document.implementation.createDocument(ns,"gpx");const root=doc.documentElement;root.setAttribute("version","1.1");root.setAttribute("creator","FieldForge");
  function node(parent,name,content){const n=doc.createElementNS(ns,name);if(content!==undefined)n.textContent=content;parent.append(n);return n;}
  const description=`PLANNED driving route, not recorded. Requested ${route.created_at}. ${route.source}. ${route.attribution}. Saved geometry; no offline rerouting.`;
  node(node(root,"metadata"),"desc",description);const track=node(root,"trk");node(track,"name","PLANNED driving route — not recorded");node(track,"desc",description);const segment=node(track,"trkseg");
  for(const [lon,lat] of route.coordinates){const p=node(segment,"trkpt");p.setAttribute("lat",decimal(lat));p.setAttribute("lon",decimal(lon));}
  save("fieldforge-planned-route.gpx",'<?xml version="1.0" encoding="UTF-8"?>\n'+new XMLSerializer().serializeToString(doc),"application/gpx+xml");
};
controls();
'''
