import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createHash} from "node:crypto";
import {createImageViewer} from "./image-viewer.mjs";

// DOM/decoder doubles exercise UI state transitions and asynchronous races.
// They are not a browser rendering or native image decoder test.
test("image UI rejects mismatched calibration and discards cancelled or superseded reads", async () => {
  const elements = new Map();
  for (const [, key] of readFileSync(new URL("./desk.html", import.meta.url), "utf8").matchAll(/id="(image\w+)"/g)) {
    const handlers = new Map();
    elements.set(key, {value:"", checked:false, disabled:false, hidden:false, files:[], textContent:"", classList:{toggle() {}},
      addEventListener(type, fn) { handlers.set(type, fn); },
      setAttribute() {}, reset() {}, click() {},
      get valueAsNumber() { return String(this.value).trim() ? Number(this.value) : NaN; },
      async fire(type, extra = {}) { return handlers.get(type)?.({preventDefault() {}, ...extra}); }
    });
  }
  const el = key => elements.get(key), draws = [];
  const context = {setTransform() {}, clearRect() { draws.length = 0; }, drawImage(bitmap) { draws.push(bitmap); }, beginPath() {}, arc() {}, moveTo() {}, lineTo() {}, stroke() {}};
  el("imageCanvas").getContext = () => context; el("imageCanvas").getBoundingClientRect = () => ({width:800,height:500,left:0,top:0});
  el("imageBoundsForm").reset = () => { for (const key of ["imageProjection","imageWest","imageEast","imageNorth","imageSouth"]) el(key).value = ""; el("imageBoundsChecked").checked = false; };
  const savedGlobals = new Map(["document","window","crypto","createImageBitmap","ResizeObserver"].map(key => [key,Object.getOwnPropertyDescriptor(globalThis,key)]));
  let decode = async () => ({width:2,height:2,closed:false,close() { this.closed = true; }});
  const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise,resolve}; };
  const settle = () => new Promise(resolve => setImmediate(resolve));
  const exports = [], downloads = [];
  const png = Buffer.from("89504e470d0a1a0a0000000d4948445200000002000000020806000000000000000000000049454e4400000000", "hex");
  const bytes = png.buffer.slice(png.byteOffset,png.byteOffset+png.byteLength);
  const file = name => ({name,size:png.length,arrayBuffer:async () => bytes});
  const globals = {document:{getElementById:el},window:{devicePixelRatio:1,addEventListener() {}},crypto:{subtle:{digest:async (algorithm, buffer) => createHash("sha256").update(new Uint8Array(buffer)).digest()}},createImageBitmap:(...args) => decode(...args),ResizeObserver:undefined};
  try {
    for (const [key,value] of Object.entries(globals)) Object.defineProperty(globalThis,key,{value,configurable:true,writable:true});
    const viewer = createImageViewer({onExportPoint:point => exports.push(point),download:(text,mime,name) => downloads.push({text,mime,name})});
    assert.equal(el("imageSavePoint").disabled,true); assert.equal(el("imageViewControls").disabled,true);
    el("imageFile").files = [file("first.png")]; await el("imageFile").fire("change"); await settle();
    assert.equal(el("imageName").textContent,"first.png"); assert.equal(el("imageViewControls").disabled,false); assert.equal(draws.length,1);
    assert.equal(el("imageSavePoint").disabled,true); // A decoded image alone is not georeferenced.
    for (const [key,value] of Object.entries({imageProjection:"geographic",imageWest:"-1",imageEast:"1",imageNorth:"1",imageSouth:"-1"})) el(key).value = value;
    el("imageBoundsChecked").checked = true; await el("imageBoundsForm").fire("submit");
    assert.equal(el("imageSavePoint").disabled,false); await el("imageSavePoint").fire("click");
    assert.deepEqual(exports[0],{lat:-.5,lon:.5,name:"Image pixel 1, 1"});
    await el("imageSaveBounds").fire("click"); const calibration = JSON.parse(downloads[0].text);
    assert.equal(calibration.image_sha256,createHash("sha256").update(png).digest("hex")); assert.equal(calibration.width,2);
    const boundsFile = data => ({size:JSON.stringify(data).length,text:async () => JSON.stringify(data)});
    el("imageBoundsFile").files = [boundsFile({...calibration,image_sha256:"b".repeat(64)})]; await el("imageBoundsFile").fire("change");
    assert.match(el("imageBoundsStatus").textContent,/different image/); assert.equal(el("imageSavePoint").disabled,false); // Atomic rejection.
    el("imageEast").value = "2"; await el("imageBoundsForm").fire("input"); assert.equal(el("imageSavePoint").disabled,true);
    el("imageBoundsFile").files = [boundsFile(calibration)]; await el("imageBoundsFile").fire("change");
    assert.equal(el("imageEast").value,1); assert.equal(el("imageSavePoint").disabled,false);
    // An in-flight bounds read cannot overwrite a later form edit.
    const slowBounds = deferred(); el("imageBoundsFile").files = [{size:100,text:() => slowBounds.promise}]; const readingBounds = el("imageBoundsFile").fire("change");
    el("imageWest").value = "-2"; await el("imageBoundsForm").fire("input"); slowBounds.resolve(JSON.stringify(calibration)); await readingBounds;
    assert.equal(el("imageWest").value,"-2"); assert.equal(el("imageSavePoint").disabled,true);
    // Clearing during native decoding disposes the eventual bitmap, without restoring UI data.
    const decoding = deferred(), bitmap = {width:2,height:2,closed:false,close() { this.closed = true; }};
    decode = () => decoding.promise; el("imageFile").files = [file("cancelled.png")]; await el("imageFile").fire("change"); await settle();
    await el("imageClear").fire("click"); decoding.resolve(bitmap); await settle();
    assert.equal(bitmap.closed,true); assert.equal(el("imageViewControls").disabled,true); assert.equal(el("imageSelectedPixel").textContent,"—"); assert.equal(draws.length,0);
    // Serialize reads: an older file resolving last never becomes the active image.
    const reading = deferred(); let decodes = 0;
    decode = async () => { decodes++; return {width:2,height:2,close() {}}; };
    el("imageFile").files = [{name:"old.png",size:png.length,arrayBuffer:() => reading.promise}]; await el("imageFile").fire("change"); await settle();
    el("imageFile").files = [file("new.png")]; await el("imageFile").fire("change"); reading.resolve(bytes); await settle();
    assert.equal(decodes,1); assert.equal(el("imageName").textContent,"new.png"); assert.equal(el("imageSavePoint").disabled,true);
    viewer.refresh(); assert.equal(draws.length,1);
    await el("imageClear").fire("click"); assert.equal(draws.length,0); assert.equal(el("imageOpenBounds").disabled,true);
  } finally {
    for (const [key,descriptor] of savedGlobals) { if (descriptor) Object.defineProperty(globalThis,key,descriptor); else delete globalThis[key]; }
  }
});
