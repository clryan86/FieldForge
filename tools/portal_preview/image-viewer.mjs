import {MAX_IMAGE_BYTES, BOUNDS_KIND, checkDimensions, imageHeader, validateBounds, pixelCoordinate, validateBoundsFile, imageViewport, pixelAtScreen} from "./image-core.mjs";

// Files are decoded locally. No images, coordinates or bounds enter browser storage.
export function createImageViewer({onExportPoint, download}) {
  const id = key => document.getElementById(key), canvas = id("imageCanvas"), ctx = canvas.getContext("2d");
  let current = null, selected = null, bounds = null, view = null;
  let zoom = 1, cx = 0, cy = 0, generation = 0, boundsGeneration = 0, jobs = Promise.resolve();
  const status = (text, error = false) => { id("imageStatus").textContent = text; id("imageStatus").classList.toggle("error", error); };
  const boundsStatus = (text, error = false) => { id("imageBoundsStatus").textContent = text; id("imageBoundsStatus").classList.toggle("error", error); };
  if (!ctx) { id("imageFile").disabled = true; status("This browser cannot draw map images. Use a browser with Canvas support.", true); return {refresh() {}}; }

  function readout() {
    const point = current && selected && bounds ? pixelCoordinate(selected.column, selected.row, current.width, current.height, bounds) : null;
    id("imageSelectedPixel").textContent = selected ? `${selected.column}, ${selected.row}` : "—";
    id("imageSelectedCoords").textContent = point ? `${point.lat.toFixed(7)}, ${point.lon.toFixed(7)}` : bounds ? "Select a pixel" : "Add map bounds below";
    id("imageSavePoint").disabled = !point;
    id("imageSaveBounds").disabled = !bounds || !current?.sha256;
    id("imageRemoveBounds").disabled = !bounds;
    id("imageOpenBounds").disabled = !current?.sha256;
    id("imageCoordinateNote").textContent = bounds ? "Calculated from your supplied bounds and projection; not independently verified. CSV uses WGS 84 decimal degrees." : "An image alone does not establish geographic coordinates.";
  }
  function draw() {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(rect.width * ratio); canvas.height = Math.round(rect.height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0); ctx.clearRect(0, 0, rect.width, rect.height);
    if (!current) { view = null; return; }
    view = imageViewport(current.width, current.height, rect.width, rect.height, zoom, cx, cy);
    ({zoom, cx, cy} = view);
    ctx.imageSmoothingEnabled = view.scale < 1;
    ctx.drawImage(current.bitmap, view.left, view.top, current.width * view.scale, current.height * view.scale);
    if (selected) {
      const x = view.left + (selected.column + .5) * view.scale, y = view.top + (selected.row + .5) * view.scale;
      ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2); ctx.moveTo(x - 13, y); ctx.lineTo(x + 13, y); ctx.moveTo(x, y - 13); ctx.lineTo(x, y + 13);
      ctx.strokeStyle = "#0e2921"; ctx.lineWidth = 4; ctx.stroke(); ctx.strokeStyle = "#f8dc8f"; ctx.lineWidth = 2; ctx.stroke();
    }
    id("imageZoomLevel").textContent = `${Number(zoom.toFixed(2))}×`;
    id("imageZoomIn").disabled = zoom >= 16; id("imageZoomOut").disabled = zoom <= 1;
  }
  function removeBounds(message = "No geographic bounds applied.") {
    boundsGeneration++; bounds = null; boundsStatus(message); readout();
  }
  function clear(message = "Image cleared from this tab. Nothing was uploaded or saved.") {
    generation++; current?.bitmap.close(); current = null; selected = null; view = null; zoom = 1; cx = cy = 0;
    id("imageFile").value = ""; id("imageBoundsFile").value = ""; id("imageBoundsForm").reset();
    for (const key of ["imageViewControls", "imagePixelControls", "imageBoundsControls"]) id(key).disabled = true;
    id("imageClear").disabled = true; id("imageEmpty").hidden = false; id("imageName").textContent = "Local map image";
    id("imageMetadata").textContent = "Click the image to select a pixel, or use the column and row fields. Zoom is relative to the fitted view.";
    id("imageColumn").value = "0"; id("imageRow").value = "0"; id("imageZoomLevel").textContent = "1×";
    canvas.setAttribute("aria-label", "No map image loaded. Use the file picker to open an image.");
    removeBounds(); status(message); draw();
  }
  function selectPixel(pixel, focusView = false) {
    if (!current || !pixel) return;
    if (!Number.isInteger(pixel.column) || !Number.isInteger(pixel.row) || pixel.column < 0 || pixel.row < 0 || pixel.column >= current.width || pixel.row >= current.height) throw new Error("Choose a whole-number column and row inside the image.");
    selected = pixel; id("imageColumn").value = pixel.column; id("imageRow").value = pixel.row;
    if (focusView) { cx = pixel.column + .5; cy = pixel.row + .5; }
    draw(); readout();
  }
  function openImage(file) {
    if (!file) return;
    clear("Reading your image on this device…"); id("imageClear").disabled = false;
    const token = generation;
    // Serialize reads/decodes and discard superseded selections before allocation.
    jobs = jobs.catch(() => {}).then(async () => {
      let bitmap = null;
      try {
        if (token !== generation) return;
        if (!file.size || file.size > MAX_IMAGE_BYTES) throw new Error("Choose a nonempty image no larger than 32 MiB.");
        if (typeof createImageBitmap !== "function") throw new Error("This browser cannot decode images locally with this viewer. Use a current browser with ImageBitmap support.");
        const buffer = await file.arrayBuffer(); if (token !== generation) return;
        const header = imageHeader(new Uint8Array(buffer));
        let sha256 = null;
        if (globalThis.crypto?.subtle) {
          const hash = await crypto.subtle.digest("SHA-256", buffer);
          sha256 = [...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, "0")).join("");
        }
        if (token !== generation) return;
        try { bitmap = await createImageBitmap(new Blob([buffer], {type:header.mime}), {imageOrientation:"from-image"}); }
        catch { throw new Error("The browser could not decode this image. It may be damaged or use an unsupported encoding."); }
        if (token !== generation) { bitmap.close(); return; }
        const {width, height} = checkDimensions(bitmap.width, bitmap.height);
        if (!((width === header.width && height === header.height) || (width === header.height && height === header.width))) throw new Error("Decoded dimensions disagree with the image header.");
        current = {bitmap, width, height, sha256}; bitmap = null; cx = width / 2; cy = height / 2;
        for (const key of ["imageViewControls", "imagePixelControls", "imageBoundsControls"]) id(key).disabled = false;
        id("imageColumn").max = width - 1; id("imageRow").max = height - 1;
        id("imageName").textContent = file.name; id("imageEmpty").hidden = true;
        id("imageMetadata").textContent = `${header.format} · ${width.toLocaleString()} × ${height.toLocaleString()} pixels · ${(file.size / 1048576).toLocaleString(undefined, {maximumFractionDigits:2})} MiB · orientation applied by the browser`;
        canvas.setAttribute("aria-label", `${file.name}: ${width} by ${height} pixels. Select a pixel with the column and row controls below.`);
        selectPixel({column:Math.floor(width / 2), row:Math.floor(height / 2)});
        status("Image opened locally. Zoom, pan or select a pixel. Geographic coordinates require the optional bounds below." + (sha256 ? "" : " Saved bounds need a browser with secure SHA-256 support."));
      } catch (error) {
        bitmap?.close();
        if (token === generation) { clear(); status(error.message || "The image could not be opened.", true); }
      }
    });
  }
  id("imageFile").addEventListener("change", () => openImage(id("imageFile").files[0]));
  id("imageClear").addEventListener("click", () => clear());
  id("imagePixelForm").addEventListener("submit", event => {
    event.preventDefault();
    try { selectPixel({column:id("imageColumn").valueAsNumber, row:id("imageRow").valueAsNumber}, true); status("Pixel selected. The marker shows its center."); }
    catch (error) { status(error.message, true); }
  });
  canvas.addEventListener("click", event => {
    if (!current || !view) return;
    const rect = canvas.getBoundingClientRect(), pixel = pixelAtScreen(event.clientX - rect.left, event.clientY - rect.top, view, current.width, current.height);
    if (pixel) selectPixel(pixel);
  });
  id("imageZoomIn").addEventListener("click", () => { zoom *= 2; draw(); });
  id("imageZoomOut").addEventListener("click", () => { zoom /= 2; draw(); });
  id("imageFit").addEventListener("click", () => { zoom = 1; if (current) { cx = current.width / 2; cy = current.height / 2; } draw(); });
  for (const [key, dx, dy] of [["imageLeft", -1, 0], ["imageRight", 1, 0], ["imageUp", 0, -1], ["imageDown", 0, 1]]) id(key).addEventListener("click", () => {
    if (!view) return;
    const rect = canvas.getBoundingClientRect(); cx += dx * rect.width / view.scale * .2; cy += dy * rect.height / view.scale * .2; draw();
  });
  id("imageBoundsForm").addEventListener("input", () => removeBounds("Bounds edited. Apply them to enable coordinate calculations."));
  id("imageBoundsForm").addEventListener("submit", event => {
    event.preventDefault(); if (!current) return;
    try {
      if (!id("imageBoundsChecked").checked) throw new Error("Check the map projection, north-up orientation and full-image bounds first.");
      const candidate = {projection:id("imageProjection").value};
      for (const edge of ["West", "East", "North", "South"]) candidate[edge.toLowerCase()] = id("image" + edge).valueAsNumber;
      const checked = validateBounds(candidate); boundsGeneration++; bounds = checked; readout();
      boundsStatus("Your bounds are applied. Coordinates are calculated from these values, not independently verified.");
    } catch (error) { removeBounds(); boundsStatus(error.message, true); }
  });
  id("imageRemoveBounds").addEventListener("click", () => { id("imageBoundsForm").reset(); removeBounds("Bounds removed. Image viewing remains available."); });
  id("imageSavePoint").addEventListener("click", () => {
    if (!current || !selected || !bounds) return;
    const point = pixelCoordinate(selected.column, selected.row, current.width, current.height, bounds);
    onExportPoint({...point, name:`Image pixel ${selected.column}, ${selected.row}`});
    status("Point CSV saved. It uses your supplied image bounds and projection; the coordinates are not independently verified.");
  });
  id("imageSaveBounds").addEventListener("click", () => {
    if (!bounds || !current?.sha256) return;
    download(JSON.stringify({kind:BOUNDS_KIND, schema_version:1, image_sha256:current.sha256, width:current.width, height:current.height, bounds}, null, 2), "application/json", "fieldforge-image-bounds.json");
    boundsStatus("Bounds file saved. It can be reopened only with this exact image; it does not contain the image.");
  });
  id("imageOpenBounds").addEventListener("click", () => id("imageBoundsFile").click());
  id("imageBoundsFile").addEventListener("change", async () => {
    const file = id("imageBoundsFile").files[0], token = generation, boundsToken = ++boundsGeneration;
    if (!file || !current?.sha256) return;
    try {
      if (file.size > 64 * 1024) throw new Error("Choose a bounds file no larger than 64 KiB.");
      const text = await file.text(); if (token !== generation || boundsToken !== boundsGeneration) return;
      let data; try { data = JSON.parse(text); } catch { throw new Error("The bounds file is not valid JSON."); }
      const checked = validateBoundsFile(data, current); // Validate everything before changing any active bounds.
      bounds = checked; id("imageProjection").value = checked.projection;
      for (const edge of ["West", "East", "North", "South"]) id("image" + edge).value = checked[edge.toLowerCase()];
      id("imageBoundsChecked").checked = true; readout(); boundsStatus("Saved user-supplied bounds restored for this exact image. Coordinates are not independently verified.");
    } catch (error) { if (token === generation && boundsToken === boundsGeneration) boundsStatus(error.message + " Existing bounds were kept.", true); }
    finally { if (token === generation && boundsToken === boundsGeneration) id("imageBoundsFile").value = ""; }
  });
  if (typeof ResizeObserver === "function") new ResizeObserver(draw).observe(canvas);
  else window.addEventListener("resize", draw);
  clear("No image loaded. Geographic bounds are optional and must be supplied by you.");
  return {refresh:draw};
}
