import {MAX_PLACE_BYTES, placeCoordinateText, manualPlace, mergePlaces, matchingPlaces, parsePlacesJSON, parsePlacesCSV, placesJSON, placesCSV, placesGPX} from "./places-core.mjs";
import {createFieldSheet} from "./field-sheet.mjs";

export function createPlaces({download}) {
  const id = key => document.getElementById(key);
  const node = (tag,text) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; return element; };
  let records = [], editing = null, page = 0, generation = 0, undo = null;
  const fieldSheet = createFieldSheet({download});
  const pageSize = 50;
  const announce = (message,error = false) => { id("placesStatus").textContent = message; id("placesStatus").classList.toggle("error",error); };
  const filtered = () => matchingPlaces(records,id("placesSearch").value);
  function resetEditor() { editing = null; id("placesForm").reset(); id("placesSubmit").textContent = "Add place"; id("placesCancelEdit").hidden = true; id("placesEditorTitle").textContent = "Add coordinates"; }
  function cancelRead() { generation++; id("placesCancelRead").disabled = true; id("placesFile").value = ""; }
  function render() {
    const matches = filtered(), pages = Math.max(1,Math.ceil(matches.length/pageSize)); page = Math.max(0,Math.min(page,pages-1));
    id("placesTabCount").textContent = records.length ? ` (${records.length})` : "";
    id("placesCount").textContent = `${matches.length} matching / ${records.length} total · 1,000 maximum`;
    id("placesPage").textContent = `Page ${page+1} of ${pages}`;
    id("placesPrevious").disabled = page === 0; id("placesNext").disabled = page >= pages-1;
    id("placesClear").disabled = !records.length; id("placesUndo").disabled = !undo;
    id("placesSaveJSON").disabled = !records.length; id("placesSaveCSV").disabled = !matches.length;
    id("placesSaveGPX").disabled = !matches.length || matches.length > 200;
    id("placesExportCount").textContent = `CSV / GPX export all ${matches.length} search matches, across pages. Collection JSON saves all ${records.length} places.`;
    id("placesGPXNote").textContent = matches.length > 200 ? "Narrow the search to 200 places or fewer for desktop GPX import." : "GPX uses distinct names and puts the source note in each waypoint description. Review name conflicts when importing into the desktop.";
    const body = node("tbody");
    for (const record of matches.slice(page*pageSize,(page+1)*pageSize)) {
      const row = node("tr"), name = node("td"), coords = node("td"), source = node("td",record.source), actions = node("td");
      name.append(node("strong",record.name)); coords.append(node("span",record.lat.toFixed(7)),node("span",record.lon.toFixed(7)));
      for (const [label,action] of [["Edit",() => { editing = record; id("placesName").value = record.name; id("placesLatitude").value = placeCoordinateText(record.lat); id("placesLongitude").value = placeCoordinateText(record.lon); id("placesSource").value = record.source; id("placesSubmit").textContent = "Save changes"; id("placesCancelEdit").hidden = false; id("placesEditorTitle").textContent = "Edit coordinates"; id("placesName").focus(); }],["Remove",() => { if (!records.includes(record)) return; undo = records; records = records.filter(point => point !== record); cancelRead(); if (editing === record) resetEditor(); render(); announce("Place removed from this tab. Undo restores the previous collection."); }]]) {
        const button = node("button",label); button.type = "button"; button.className = "secondary"; button.setAttribute("aria-label",`${label} ${record.name}`); button.addEventListener("click",action); actions.append(button);
      }
      row.append(name,coords,source,actions); body.append(row);
    }
    if (!matches.length) { const row = node("tr"), cell = node("td",records.length ? "No places match this search." : "Add a place, import a collection, or collect points from the GPX and image tools."); cell.colSpan = 4; row.append(cell); body.append(row); }
    id("placesRows").replaceChildren(...body.children);
    fieldSheet.update(matches);
  }
  function add(points, label = "Places") {
    const result = mergePlaces(records,points);
    if (result.added) { undo = records; records = result.places; cancelRead(); }
    page = 0; render(); const message = `${label}: ${result.added} added; ${result.duplicates} exact duplicates skipped. Save collection JSON to keep this work after closing.`;
    announce(message); return message;
  }
  id("placesForm").addEventListener("submit",event => {
    event.preventDefault();
    try {
      const record = manualPlace(id("placesName").value,id("placesLatitude").value,id("placesLongitude").value,id("placesSource").value);
      if (editing) {
        const index = records.indexOf(editing); if (index < 0) throw new Error("This place changed. Choose it again before editing.");
        if (records.some((point,i) => i !== index && JSON.stringify(point) === JSON.stringify(record))) throw new Error("An identical place already exists. Remove this duplicate or change its details.");
        undo = records; records = records.map((point,i) => i === index ? record : point); cancelRead(); announce("Changes kept in this tab. Save collection JSON to keep them after closing.");
      } else add([record],"Manual entry");
      resetEditor(); render();
    } catch (error) { announce(error.message,true); }
  });
  id("placesCancelEdit").addEventListener("click",resetEditor);
  id("placesSearch").addEventListener("input",() => { page = 0; render(); });
  id("placesPrevious").addEventListener("click",() => { page--; render(); });
  id("placesNext").addEventListener("click",() => { page++; render(); });
  id("placesUndo").addEventListener("click",() => { if (!undo) return; records = undo; undo = null; cancelRead(); resetEditor(); render(); announce("Previous collection restored. Undo is available for one change."); });
  id("placesClear").addEventListener("click",() => {
    if (!records.length || !window.confirm(`Clear all ${records.length} places from this tab?\n\nSave collection JSON first if you want to keep them. This also clears undo and cannot remove exported files.`)) return;
    cancelRead(); records = []; undo = null; page = 0; id("placesSearch").value = ""; resetEditor(); render(); announce("Collection and undo cleared from this tab. Previously exported files are unchanged.");
  });
  id("placesOpen").addEventListener("click",() => id("placesFile").click());
  id("placesCancelRead").addEventListener("click",() => { cancelRead(); announce("File import cancelled. Your existing places were kept."); });
  id("placesFile").addEventListener("change",async () => {
    const file = id("placesFile").files[0]; if (!file) return;
    const token = ++generation; id("placesCancelRead").disabled = false; announce("Reading your collection on this device…");
    try {
      if (!file.size || file.size > MAX_PLACE_BYTES) throw new Error("Choose a nonempty collection no larger than 4 MiB.");
      const type = file.name.toLowerCase().endsWith(".json") ? "json" : file.name.toLowerCase().endsWith(".csv") ? "csv" : null;
      if (!type) throw new Error("Choose a FieldForge collection .json or supported .csv file.");
      const bytes = await file.arrayBuffer(); if (token !== generation) return;
      let text; try { text = new TextDecoder("utf-8",{fatal:true}).decode(bytes); } catch { throw new Error("The collection must use UTF-8 text encoding."); }
      const points = type === "json" ? parsePlacesJSON(text) : parsePlacesCSV(text);
      id("placesCancelRead").disabled = true; id("placesFile").value = "";
      add(points,"Imported collection");
    } catch (error) { if (token === generation) announce(error.message + " Existing places were kept.",true); }
    finally { if (token === generation) { id("placesCancelRead").disabled = true; id("placesFile").value = ""; } }
  });
  for (const [key,convert,mime,filename,all] of [["placesSaveJSON",placesJSON,"application/json","fieldforge-place-collection.json",true],["placesSaveCSV",placesCSV,"text/csv;charset=utf-8","fieldforge-places.csv",false],["placesSaveGPX",placesGPX,"application/gpx+xml","fieldforge-places.gpx",false]]) id(key).addEventListener("click",() => {
    try { const selected = all ? records : filtered(); download(convert(selected),mime,filename); announce(`${selected.length} places exported. The file contains names, coordinates and source notes in plain text.`); }
    catch (error) { announce(error.message,true); }
  });
  render();
  return {add};
}
