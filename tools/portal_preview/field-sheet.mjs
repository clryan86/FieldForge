import {MAX_SHEET_PLACES, GEOMETRY_NOTE, COORDINATE_NOTE, comparePlaces, distanceText, bearingText, coordinateText, captureFieldSheet, fieldSheetHTML} from "./field-sheet-core.mjs";

export function createFieldSheet({download}) {
  const id = key => document.getElementById(key);
  const node = (tag,text) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; return element; };
  let points = [], comparison = null, prepared = null;
  id("sheetUnits").value = "metric";
  const status = message => { id("sheetStatus").textContent = message; };
  function invalidate() {
    const hadSheet = prepared !== null; prepared = null;
    id("sheetDownload").disabled = true; id("sheetPreview").hidden = true; id("sheetPreview").replaceChildren();
    if (hadSheet) status("Changed. Prepare a new sheet before downloading.");
  }
  function endpoints() {
    const selected = key => { const value = id(key).value; return /^(0|[1-9]\d*)$/.test(value) ? points[Number(value)] : undefined; };
    return {from:selected("sheetFrom"),to:selected("sheetTo")};
  }
  function resetComparison() {
    invalidate(); comparison = null;
    id("sheetComparison").replaceChildren(); id("sheetComparison").hidden = true;
    id("sheetIncludeComparison").checked = false; id("sheetIncludeComparison").disabled = true;
    const {from,to} = endpoints(); id("sheetCalculate").disabled = !from || !to; id("sheetSwap").disabled = !from || !to;
  }
  function showComparison(parent,leg,units) {
    parent.append(node("h4","Point-to-point estimate"));
    for (const [label,point] of [["From",leg.from],["To",leg.to]]) parent.append(node("p",`${label}: ${point.name} · ${coordinateText(point)}`));
    const numbers = node("div"); numbers.className = "sheet-numbers";
    for (const [label,value] of [["Great-circle distance",distanceText(leg.meters,units)],["Initial true bearing",bearingText(leg)]]) {
      const item = node("p"); item.append(node("span",label),node("strong",value)); numbers.append(item);
    }
    parent.append(numbers); if (leg.reason) parent.append(node("p",leg.reason));
    const note = node("p",GEOMETRY_NOTE); note.className = "desk-fine"; parent.append(note);
  }
  function renderComparison() {
    const panel = id("sheetComparison"); panel.replaceChildren(); panel.hidden = !comparison;
    if (comparison) showComparison(panel,comparison,id("sheetUnits").value);
  }
  for (const key of ["sheetFrom","sheetTo"]) id(key).addEventListener("change",resetComparison);
  id("sheetSwap").addEventListener("click",() => { const from = id("sheetFrom").value; id("sheetFrom").value = id("sheetTo").value; id("sheetTo").value = from; resetComparison(); });
  id("sheetCalculate").addEventListener("click",() => {
    try {
      const {from,to} = endpoints(); invalidate(); comparison = comparePlaces(from,to); renderComparison();
      id("sheetIncludeComparison").disabled = false;
      status("Estimate ready. Choose whether to include it, then prepare your sheet.");
    } catch (error) { resetComparison(); status(error.message); }
  });
  id("sheetUnits").addEventListener("change",() => { invalidate(); renderComparison(); });
  for (const [key,event] of [["sheetTitle","input"],["sheetSources","change"],["sheetIncludeComparison","change"]]) id(key).addEventListener(event,invalidate);
  id("sheetPrepare").addEventListener("click",() => {
    invalidate();
    try {
      if (id("sheetIncludeComparison").checked && !comparison) throw new Error("Calculate the selected comparison first.");
      const snapshot = captureFieldSheet(points,{title:id("sheetTitle").value,includeSources:id("sheetSources").checked,units:id("sheetUnits").value,comparison:id("sheetIncludeComparison").checked ? comparison : null});
      const html = fieldSheetHTML(snapshot), preview = id("sheetPreview");
      preview.append(node("h4",snapshot.title),node("p",`${snapshot.points.length} places · Prepared ${snapshot.createdAt} (device UTC)`),node("p",COORDINATE_NOTE));
      if (snapshot.comparison) { const estimate = node("section"); estimate.className = "sheet-estimate"; showComparison(estimate,snapshot.comparison,snapshot.units); preview.append(estimate); }
      const list = node("ol");
      for (const point of snapshot.points) {
        const row = node("li"); row.append(node("strong",point.name),node("p",`Latitude ${point.lat.toFixed(7)} · Longitude ${point.lon.toFixed(7)}`));
        if (snapshot.includeSources) row.append(node("p",`Source note: ${point.source}`)); list.append(row);
      }
      preview.append(list); preview.hidden = false; prepared = {html}; id("sheetDownload").disabled = false;
      status(`Sheet ready: ${snapshot.points.length} matching places. Source notes ${snapshot.includeSources ? "included" : "omitted"}. Download it, then open the file to print.`);
    } catch (error) { status(error.message); }
  });
  id("sheetDownload").addEventListener("click",() => {
    if (!prepared) return;
    download(prepared.html,"text/html;charset=utf-8","fieldforge-place-sheet.html");
    status("Printable HTML saved. Open that file and use your browser’s Print or Save as PDF. It contains precise locations in plain text.");
  });
  function update(matches) {
    if (matches.length === points.length && matches.every((point,index) => point === points[index])) return;
    points = [...matches]; resetComparison();
    for (const key of ["sheetFrom","sheetTo"]) {
      const select = id(key), placeholder = node("option","Choose a matching place"); placeholder.value = "";
      select.replaceChildren(placeholder);
      points.forEach((point,index) => { const option = node("option",`${index+1}. ${point.name} · ${coordinateText(point)}`); option.value = String(index); select.append(option); });
      select.value = ""; select.disabled = !points.length;
    }
    id("sheetCalculate").disabled = true; id("sheetSwap").disabled = true;
    id("sheetPrepare").disabled = !points.length || points.length > MAX_SHEET_PLACES;
    id("sheetScope").textContent = points.length > MAX_SHEET_PLACES ? `${points.length} matches. Narrow the place search to ${MAX_SHEET_PLACES} or fewer; no places are silently omitted.` : `${points.length} matching places will be included, across all list pages. Maximum ${MAX_SHEET_PLACES} per sheet.`;
  }
  return {update};
}
