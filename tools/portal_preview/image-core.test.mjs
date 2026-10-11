import test from "node:test";
import assert from "node:assert/strict";
import {imageHeader, checkDimensions, validateBounds, pixelCoordinate, validateBoundsFile, imageViewport, pixelAtScreen, BOUNDS_KIND, MAX_IMAGE_BYTES, MERCATOR_LIMIT} from "./image-core.mjs";
import {waypointCSV} from "./desk-core.mjs";

// Minimal metadata fixtures exercise preflight only. The browser must still decode
// and validate the actual pixels before the UI accepts an image.
function png(width = 640, height = 480, animation = false) {
  const chunk = (kind, data = Buffer.alloc(0)) => { const out = Buffer.alloc(12 + data.length); out.writeUInt32BE(data.length); out.write(kind, 4); data.copy(out, 8); return out; };
  const header = Buffer.alloc(13); header.writeUInt32BE(width); header.writeUInt32BE(height, 4);
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]), chunk("IHDR", header), ...(animation ? [chunk("acTL", Buffer.alloc(8))] : []), chunk("IEND")]);
}
function jpeg(width, height) {
  const data = Buffer.from([255,216,255,224,0,4,0,0,255,192,0,8,8,0,0,0,0,1,255,217]);
  data.writeUInt16BE(height, 13); data.writeUInt16BE(width, 15); return data;
}
function webp(width, height, {lossless = false, extended = false, animation = false, canvasWidth = width} = {}) {
  const chunk = (kind, data) => { const out = Buffer.alloc(8 + data.length + data.length % 2); out.write(kind); out.writeUInt32LE(data.length, 4); data.copy(out, 8); return out; };
  const chunks = [];
  if (extended || animation) { const x = Buffer.alloc(10); x[0] = animation ? 2 : 0; x.writeUIntLE(canvasWidth - 1, 4, 3); x.writeUIntLE(height - 1, 7, 3); chunks.push(chunk("VP8X", x)); }
  const frame = Buffer.alloc(lossless ? 5 : 10);
  if (lossless) { frame[0] = 0x2f; frame.writeUInt32LE((width - 1) | ((height - 1) << 14), 1); }
  else { frame.set([157, 1, 42], 3); frame.writeUInt16LE(width, 6); frame.writeUInt16LE(height, 8); }
  chunks.push(chunk(lossless ? "VP8L" : "VP8 ", frame));
  const header = Buffer.alloc(12); header.write("RIFF"); header.writeUInt32LE(4 + chunks.reduce((n, c) => n + c.length, 0), 4); header.write("WEBP", 8);
  return Buffer.concat([header, ...chunks]);
}
const bounds = {projection:"geographic", west:-125, east:-105, north:50, south:30};
const near = (actual, expected, precision = 1e-9) => assert.ok(Math.abs(actual - expected) < precision, `${actual} != ${expected}`);

test("image metadata uses signatures and validates PNG, JPEG and still WebP dimensions", () => {
  for (const [bytes, format, mime] of [[png(), "PNG", "image/png"], [jpeg(640,480), "JPEG", "image/jpeg"], [webp(640,480), "WebP", "image/webp"], [webp(640,480,{lossless:true}), "WebP", "image/webp"], [webp(640,480,{extended:true,lossless:true}), "WebP", "image/webp"]]) {
    assert.deepEqual(imageHeader(bytes), {format, mime, width:640, height:480});
    // DataView must honor a typed-array slice's offset within a larger buffer.
    const container = Buffer.concat([Buffer.alloc(7), bytes, Buffer.alloc(9)]);
    assert.equal(imageHeader(container.subarray(7, 7 + bytes.length)).width, 640);
  }
});
test("image preflight rejects animation, damaged framing and unsupported content", () => {
  assert.throws(() => imageHeader(png(640,480,true)), /animated/);
  assert.throws(() => imageHeader(webp(640,480,{animation:true})), /animated/);
  assert.throws(() => imageHeader(png().subarray(0,35)), /incomplete|truncated/);
  assert.throws(() => imageHeader(webp(640,480).subarray(0,25)), /incomplete|truncated/);
  const badJpeg = jpeg(640,480); badJpeg.writeUInt16BE(65000,4); assert.throws(() => imageHeader(badJpeg), /truncated/);
  assert.throws(() => imageHeader(webp(640,480,{extended:true,canvasWidth:641})), /disagree/);
  for (const text of ["<svg>not a raster image</svg>", "II*\x00GeoTIFF data", "SQLite format 3\x00MBTiles", "%PDF-1.7 map file"]) assert.throws(() => imageHeader(Buffer.from(text)), /PNG, JPEG or still WebP/);
});
test("oversized byte count and pixel allocation are rejected before decoding", () => {
  assert.deepEqual(checkDimensions(6000,4000), {width:6000,height:4000});
  for (const size of [[6001,4000],[0,1],[1,32769],[NaN,100],[1.5,10]]) assert.throws(() => checkDimensions(...size), /24 megapixels/);
  for (const bytes of [png(6001,4000),jpeg(6001,4000),webp(6001,4000,{lossless:true})]) assert.throws(() => imageHeader(bytes), /24 megapixels/);
  assert.throws(() => imageHeader(new Uint8Array(MAX_IMAGE_BYTES+1)), /32 MiB/);
});
test("geographic bounds map pixel centers, with top-left origin and real zero", () => {
  assert.deepEqual(pixelCoordinate(0,0,2,2,bounds), {lat:45,lon:-120});
  assert.deepEqual(pixelCoordinate(1,1,2,2,bounds), {lat:35,lon:-110});
  assert.deepEqual(pixelCoordinate(0,0,1,1,{...bounds,west:-1,east:1,north:1,south:-1}), {lat:0,lon:0});
  for (const pixel of [[-1,0],[2,0],[0,2],[.5,0],[NaN,0]]) assert.throws(() => pixelCoordinate(...pixel,2,2,bounds), /inside/);
});
test("date-line images wrap longitude but full-world images preserve a 360 degree span", () => {
  const dateline = {...bounds,west:170,east:-170};
  assert.equal(pixelCoordinate(0,0,2,1,dateline).lon,175);
  assert.equal(pixelCoordinate(1,0,2,1,dateline).lon,-175);
  const world = {...bounds,west:-180,east:180};
  assert.equal(pixelCoordinate(0,0,2,1,world).lon,-90); assert.equal(pixelCoordinate(1,0,2,1,world).lon,90);
  assert.throws(() => validateBounds({...bounds,west:180,east:-180}), /nonzero/);
});
test("Web Mercator interpolates projected latitude rather than latitude degrees", () => {
  const region = {...bounds,projection:"webmercator",north:80,south:0};
  near(pixelCoordinate(0,0,1,1,region).lat,57.04516467328689);
  assert.equal(pixelCoordinate(0,0,1,1,{...region,projection:"geographic"}).lat,40);
  near(pixelCoordinate(0,0,1,1,{...region,north:MERCATOR_LIMIT,south:-MERCATOR_LIMIT}).lat,0);
  assert.throws(() => validateBounds({...region,north:90}), /Web Mercator bounds/);
});
test("bounds require explicit supported projection and finite non-degenerate extent", () => {
  for (const edit of [{projection:""},{projection:"utm"},{west:null},{north:"50"},{north:Infinity},{west:181},{south:-91},{north:20},{east:-125}]) assert.throws(() => validateBounds({...bounds,...edit}));
  assert.deepEqual(validateBounds({...bounds,projection:"geographic",north:90,south:-90}), {...bounds,projection:"geographic",north:90,south:-90});
});
test("saved calibration matches exact image fingerprint, orientation dimensions and schema", () => {
  const image = {sha256:"a".repeat(64),width:640,height:480};
  const saved = {kind:BOUNDS_KIND,schema_version:1,image_sha256:image.sha256,width:640,height:480,bounds};
  assert.deepEqual(validateBoundsFile(JSON.parse(JSON.stringify(saved)),image), bounds);
  for (const edit of [{image_sha256:"b".repeat(64)},{image_sha256:"a"},{width:480,height:640},{width:"640"},{schema_version:2},{kind:"fieldforge-source-plan"},{bounds:{...bounds,north:0}}]) assert.throws(() => validateBoundsFile({...saved,...edit},image));
  assert.throws(() => validateBoundsFile(saved,{...image,sha256:null}));
});
test("fit, pan and zoom stay bounded; letterbox clicks do not become image pixels", () => {
  const fit = imageViewport(1000,500,800,600);
  assert.equal(fit.scale,.8); assert.equal(fit.left,0); assert.equal(fit.top,100);
  assert.deepEqual(pixelAtScreen(0,100,fit,1000,500), {column:0,row:0});
  assert.equal(pixelAtScreen(0,99,fit,1000,500),null); assert.equal(pixelAtScreen(800,500,fit,1000,500),null);
  const small = imageViewport(100,50,800,600); assert.equal(small.scale,1); assert.equal(small.left,350);
  const clamped = imageViewport(1000,500,800,600,200,-Infinity,Infinity); assert.equal(clamped.zoom,16);
  for (const [cx,cy] of [[-100,-100],[1e9,1e9],[500,250]]) {
    const v = imageViewport(1000,500,800,600,4,cx,cy);
    assert.ok(v.left<=0 && v.left+1000*v.scale>=800); assert.ok(v.top<=0 && v.top+500*v.scale>=600);
    const p = pixelAtScreen(400,300,v,1000,500); assert.ok(p.column>=0 && p.column<1000 && p.row>=0 && p.row<500);
  }
  assert.throws(() => imageViewport(1000,500,0,600));
});
test("screen-to-pixel round trips preserve the selected image position at every zoom", () => {
  for (const zoom of [1,2,4,8,16]) {
    const view = imageViewport(1024,512,700,500,zoom,500,300);
    for (const [column,row] of [[0,0],[511,255],[1023,511]]) assert.deepEqual(pixelAtScreen(view.left+(column+.5)*view.scale,view.top+(row+.5)*view.scale,view,1024,512),{column,row});
  }
});
test("image CSV carries image provenance, retaining spreadsheet-safe names and real zero", () => {
  const csv = waypointCSV([{name:"=image",lat:0,lon:-120}], "User-supplied image bounds; WGS 84; not independently verified");
  assert.match(csv, /"'=image","0","-120","User-supplied image bounds/); assert.ok(!csv.includes("GPX"));
  assert.match(waypointCSV([{lat:0,lon:0}]), /User-supplied GPX/);
  for (const source of [null,"", "=formula", "line\nbreak"]) assert.throws(() => waypointCSV([{lat:0,lon:0}],source), /source description/);
});
