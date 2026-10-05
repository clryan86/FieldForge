import {elevationProfile, projectElevation, nearestDistanceSample, nearestPlotSample, clampView} from "./desk-core.mjs";

export function createRouteExplorer({onExportPoint}) {
  const id = key => document.getElementById(key), ns = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs) => { const node = document.createElementNS(ns, tag); for (const [key,value] of Object.entries(attrs)) node.setAttribute(key,value); return node; };
  let data = null, projected = null, profile = null, positions = [], profilePositions = [], selected = null, marker = null, view = clampView(1,400,190);
  const number = (value, digits = 0) => value.toLocaleString(undefined, {maximumFractionDigits:digits});
  const imperial = () => id("deskUnits").value === "imperial";
  const height = meters => meters === null ? "Not recorded" : number(imperial() ? meters / .3048 : meters, 1) + (imperial() ? " ft" : " m");
  const distance = meters => imperial() ? number(meters / 1609.344, 2) + " mi" : meters < 1000 ? number(meters, 1) + " m" : number(meters / 1000, 2) + " km";
  const selectedPoint = () => !data || !selected ? null : selected.kind === "waypoint" ? data.waypoints[selected.index] : profile.samples[selected.index]?.point;
  const selectedPosition = () => selected?.kind === "waypoint" ? projected?.places[selected.index] : positions[selected?.index];

  function updateView() {
    id("deskTraceSvg").setAttribute("viewBox", view.box.join(" "));
    id("deskZoomLevel").textContent = number(view.zoom,1) + "×";
    id("deskZoomOut").disabled = !data || view.zoom <= 1;
    id("deskZoomIn").disabled = !data || view.zoom >= 8;
    for (const key of ["deskPanLeft", "deskPanRight", "deskPanUp", "deskPanDown"]) id(key).disabled = !data || view.zoom <= 1;
    if (marker) marker.setAttribute("r", 7 / view.zoom);
  }
  function setView(zoom, x, y) { view = clampView(zoom,x,y); updateView(); }
  function updateLabels() {
    if (!data) return;
    id("deskDistance").textContent = data.geometryPoints ? distance(data.meters) : "No track";
    if (profile.validCount) {
      id("deskElevationHigh").textContent = height(profile.max);
      id("deskElevationLow").textContent = height(profile.min);
      id("deskElevationEnd").textContent = distance(profile.meters) + " along file";
      id("deskAscent").textContent = profile.knownPairs ? height(profile.ascent) : "Insufficient pairs";
      id("deskDescent").textContent = profile.knownPairs ? height(profile.descent) : "Insufficient pairs";
      id("deskElevationRange").textContent = height(profile.min) + " to " + height(profile.max);
    }
  }
  function updateSelected(follow = false) {
    const point = selectedPoint(), position = selectedPosition(); if (!point || !position) return;
    const isTrack = selected.kind === "track", sample = isTrack ? profile.samples[selected.index] : null;
    const label = isTrack ? `Point ${selected.index + 1} of ${profile.samples.length} · segment ${sample.segmentIndex + 1}` : `Waypoint ${selected.index + 1} of ${data.waypoints.length}`;
    id("deskSelectedLabel").textContent = label;
    id("deskSelectedName").textContent = point.name || (isTrack ? "Track / route point" : "Unnamed waypoint");
    id("deskSelectedCoords").textContent = point.lat.toFixed(7) + ", " + point.lon.toFixed(7);
    id("deskSelectedDistance").textContent = isTrack ? distance(sample.distance) : "Not part of track";
    id("deskSelectedElevation").textContent = point.invalidElevation ? "Invalid value" : height(Number.isFinite(point.ele) ? point.ele : null);
    id("deskSavePoint").disabled = false;
    id("deskWaypointPicker").value = isTrack ? "" : String(selected.index);
    if (isTrack) {
      id("deskPointSlider").value = selected.index;
      id("deskPointSlider").setAttribute("aria-valuetext", label + ", " + distance(sample.distance) + ", elevation " + height(sample.ele));
    }
    id("deskPreviousPoint").disabled = !profile.samples.length || (isTrack && selected.index === 0);
    id("deskNextPoint").disabled = !profile.samples.length || (isTrack && selected.index === profile.samples.length - 1);
    if (!marker) { marker = svg("circle", {r:7,fill:"#ffffff",stroke:"#0c4430","stroke-width":2,"vector-effect":"non-scaling-stroke","pointer-events":"none"}); id("deskTraceDrawing").append(marker); }
    marker.setAttribute("cx", position[0]); marker.setAttribute("cy", position[1]); marker.setAttribute("r", 7 / view.zoom);
    if (follow && (position[0] < view.box[0] || position[0] > view.box[0] + view.width || position[1] < view.box[1] || position[1] > view.box[1] + view.height)) setView(view.zoom,position[0],position[1]);
    const cursor = id("deskElevationCursor"); cursor.replaceChildren();
    if (isTrack && profile.validCount) {
      const x = profile.meters ? 50 + 700 * sample.distance / profile.meters : 400;
      cursor.append(svg("line", {x1:x,x2:x,y1:20,y2:170,stroke:"#a0651d","stroke-width":1,"stroke-dasharray":"4 3"}));
      if (sample.ele !== null) {
        const y = profile.min === profile.max ? 95 : 25 + 140 * (profile.max - sample.ele) / (profile.max - profile.min);
        cursor.append(svg("circle", {cx:x,cy:y,r:5,fill:"#a0651d",stroke:"#fff","stroke-width":2}));
      }
    }
  }
  function select(kind, index, follow = true) {
    if (!data || !Number.isInteger(index) || index < 0 || index >= (kind === "waypoint" ? data.waypoints.length : profile.samples.length)) return;
    selected = {kind,index}; updateSelected(follow);
  }
  function renderElevation() {
    const drawing = id("deskElevationDrawing"), fragment = document.createDocumentFragment();
    const runs = projectElevation(profile); profilePositions = runs.flat();
    for (const run of runs) {
      if (run.length > 1) fragment.append(svg("polyline", {points:run.map(p => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" "),fill:"none",stroke:"#176445","stroke-width":2.5,"stroke-linecap":"round","stroke-linejoin":"round"}));
      else if (run.length) fragment.append(svg("circle", {cx:run[0].x,cy:run[0].y,r:3,fill:"#176445"}));
    }
    drawing.replaceChildren(fragment);
    id("deskElevationSvg").hidden = !profile.validCount; id("deskElevationTotals").hidden = !profile.validCount;
    id("deskElevationAxis").hidden = !profile.validCount;
    // SVG elements do not consistently implement HTMLElement.hidden.
    if (profile.validCount) id("deskElevationSvg").removeAttribute("hidden"); else id("deskElevationSvg").setAttribute("hidden", "");
    id("deskElevationCoverage").textContent = `${profile.validCount} of ${profile.samples.length} route points have valid heights`;
    id("deskElevationNote").textContent = !profile.validCount
      ? "No valid elevations are recorded on the tracks or routes. A waypoint’s own elevation can still appear in its selected-point readout. No heights are inferred."
      : `${profile.samples.length - profile.validCount} points without usable elevation (${profile.invalidCount} invalid values). Gaps and separate segments stay separate. Raw ascent/descent use only adjacent recorded heights, with no GPS-noise correction.`;
    updateLabels();
  }
  function clear() {
    data = null; projected = null; profile = null; positions = []; profilePositions = []; selected = null;
    marker?.remove(); marker = null;
    id("deskExplorePanel").hidden = true; id("deskViewControls").disabled = true; id("deskSavePoint").disabled = true;
    id("deskPointSlider").disabled = true; id("deskPointSlider").value = 0; id("deskPointSlider").max = 0; id("deskPointSlider").removeAttribute("aria-valuetext");
    for (const key of ["deskSelectedName", "deskSelectedCoords", "deskSelectedDistance", "deskSelectedElevation"]) id(key).textContent = "—";
    id("deskSelectedLabel").textContent = "Selected point";
    id("deskElevationDrawing").replaceChildren(); id("deskElevationCursor").replaceChildren();
    id("deskElevationCoverage").textContent = "No elevation records"; id("deskElevationNote").textContent = "";
    for (const key of ["deskElevationHigh", "deskElevationLow", "deskElevationEnd", "deskAscent", "deskDescent", "deskElevationRange"]) id(key).textContent = "";
    id("deskElevationSvg").setAttribute("hidden", ""); id("deskElevationTotals").hidden = true;
    id("deskElevationAxis").hidden = true;
    const option = document.createElement("option"); option.value = ""; option.textContent = "Choose a waypoint";
    id("deskWaypointPicker").replaceChildren(option); id("deskWaypointPickerPanel").hidden = true;
    setView(1,400,190);
  }
  function load(routeData, plot) {
    clear(); data = routeData; projected = plot; positions = plot.parts.flat(); profile = elevationProfile(data);
    id("deskExplorePanel").hidden = false; id("deskViewControls").disabled = false;
    id("deskPointControls").hidden = !profile.samples.length; id("deskPointSlider").disabled = !profile.samples.length; id("deskPointSlider").max = Math.max(0,profile.samples.length - 1);
    id("deskWaypointPickerPanel").hidden = !data.waypoints.length;
    const options = document.createDocumentFragment();
    for (const [index,point] of data.waypoints.entries()) { const option = document.createElement("option"); option.value = String(index); option.textContent = `${index + 1}. ${point.name || "Unnamed waypoint"}`; options.append(option); }
    id("deskWaypointPicker").append(options);
    renderElevation(); updateView();
    if (profile.samples.length) select("track",0,false); else if (data.waypoints.length) select("waypoint",0,false);
  }
  function eventPoint(element, event) {
    const matrix = element.getScreenCTM(); if (!matrix) return null;
    const point = element.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
    return point.matrixTransform(matrix.inverse());
  }
  id("deskTraceSvg").addEventListener("click", event => {
    if (!data) return;
    const element = id("deskTraceSvg"), point = eventPoint(element,event); if (!point) return;
    const matrix = element.getScreenCTM(), tolerance = 18 / Math.hypot(matrix.a,matrix.b);
    let best = tolerance * tolerance, hit = null;
    for (const [kind,points] of [["track",positions],["waypoint",projected.places]]) for (const [index,p] of points.entries()) { const squared = (point.x-p[0])**2 + (point.y-p[1])**2; if (squared <= best) { best=squared; hit={kind,index}; } }
    if (hit) select(hit.kind,hit.index,false);
  });
  id("deskElevationSvg").addEventListener("click", event => {
    if (!profile?.validCount) return;
    const point = eventPoint(id("deskElevationSvg"),event); if (!point) return;
    const matrix = id("deskElevationSvg").getScreenCTM();
    const hit = nearestPlotSample(profilePositions,point.x,point.y,18 / Math.hypot(matrix.a,matrix.b));
    if (hit >= 0) { select("track",hit); return; }
    const meters = Math.max(0,Math.min(1,(point.x-50)/700)) * profile.meters;
    select("track",nearestDistanceSample(profile.samples,meters));
  });
  id("deskPointSlider").addEventListener("input", () => select("track",Number(id("deskPointSlider").value)));
  id("deskWaypointPicker").addEventListener("change", () => { if (id("deskWaypointPicker").value !== "") select("waypoint",Number(id("deskWaypointPicker").value)); });
  id("deskPreviousPoint").addEventListener("click", () => select("track",selected?.kind === "track" ? selected.index-1 : 0));
  id("deskNextPoint").addEventListener("click", () => select("track",selected?.kind === "track" ? selected.index+1 : 0));
  id("deskUnits").addEventListener("change", () => { updateLabels(); updateSelected(); });
  id("deskSavePoint").addEventListener("click", () => { const point=selectedPoint(); if (point) onExportPoint({...point,name:point.name || `${selected.kind === "track" ? "Route point" : "Waypoint"} ${selected.index+1}`}); });
  id("deskZoomIn").addEventListener("click", () => { if(data) { const center=selectedPosition() || [view.x,view.y]; setView(view.zoom*1.5,center[0],center[1]); } });
  id("deskZoomOut").addEventListener("click", () => { if(data) setView(view.zoom/1.5,view.x,view.y); });
  id("deskFitTrace").addEventListener("click", () => setView(1,400,190));
  for (const [key,dx,dy] of [["deskPanLeft",-1,0],["deskPanRight",1,0],["deskPanUp",0,-1],["deskPanDown",0,1]]) id(key).addEventListener("click", () => { if (data) setView(view.zoom,view.x+dx*view.width*.2,view.y+dy*view.height*.2); });
  clear();
  return {load,clear,selectWaypoint:index => select("waypoint",index)};
}
