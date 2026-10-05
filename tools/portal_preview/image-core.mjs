// Local image metadata and bounded map transforms; no network or storage APIs.
// PNG: https://www.w3.org/TR/png-3/#11IHDR
// WebP: https://developers.google.com/speed/webp/docs/riff_container
// Mercator: https://proj.org/en/stable/operations/projections/webmerc.html
export const MAX_IMAGE_BYTES = 32 * 1024 * 1024;
export const MAX_IMAGE_PIXELS = 24_000_000;
export const MAX_IMAGE_SIDE = 32768;
export const MERCATOR_LIMIT = 85.0511287798066;
export const BOUNDS_KIND = "fieldforge-image-bounds";

export function checkDimensions(width,height) {
  if (![width,height].every(Number.isInteger) || width<1 || height<1 || width>MAX_IMAGE_SIDE || height>MAX_IMAGE_SIDE || width*height>MAX_IMAGE_PIXELS) throw new Error("Use an image of at most 24 megapixels and 32,768 pixels on either side.");
  return {width,height};
}
export function imageHeader(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.length<12 || bytes.length>MAX_IMAGE_BYTES) throw new Error("Choose an image no larger than 32 MiB.");
  const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  const text=(at,length)=>String.fromCharCode(...bytes.subarray(at,at+length));
  const result=(format,mime,width,height)=>({format,mime,...checkDimensions(width,height)});
  if (bytes[0]===137 && text(1,3)==="PNG" && bytes[4]===13 && bytes[5]===10 && bytes[6]===26 && bytes[7]===10) {
    if(bytes.length<33 || text(12,4)!=="IHDR" || view.getUint32(8)!==13) throw new Error("The PNG header is incomplete or invalid.");
    const width=view.getUint32(16),height=view.getUint32(20);
    // Reject animation and damaged chunk framing before image decoding.
    let at=8, ended=false;
    while(at+12<=bytes.length) {
      const length=view.getUint32(at),kind=text(at+4,4);
      if(length>bytes.length-at-12) throw new Error("The PNG contains a truncated chunk.");
      if(kind==="acTL") throw new Error("Use a still PNG or WebP image; animated maps are not supported.");
      at+=length+12;
      if(kind==="IEND") { ended=true;break; }
    }
    if(!ended) throw new Error("The PNG file is incomplete.");
    return result("PNG","image/png",width,height);
  }
  if(bytes[0]===255 && bytes[1]===216) {
    let at=2;
    while(at<bytes.length) {
      if(bytes[at++]!==255) throw new Error("The JPEG header is invalid.");
      while(bytes[at]===255) at++;
      const marker=bytes[at++];
      if(marker===0xd9 || marker===0xda) break;
      if(marker===0x01 || (marker>=0xd0 && marker<=0xd7)) continue;
      if(at+2>bytes.length) break;
      const size=view.getUint16(at);
      if(size<2 || at+size>bytes.length) throw new Error("The JPEG contains a truncated header.");
      if([0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf].includes(marker)) {
        if(size<8) throw new Error("The JPEG dimensions are invalid.");
        return result("JPEG","image/jpeg",view.getUint16(at+5),view.getUint16(at+3));
      }
      at+=size;
    }
    throw new Error("This JPEG does not contain supported image dimensions.");
  }
  if(text(0,4)==="RIFF" && text(8,4)==="WEBP") {
    const end=view.getUint32(4,true)+8;
    if(end>bytes.length || end<20) throw new Error("The WebP container is incomplete.");
    let at=12, canvas=null, frame=null;
    const uint24=offset=>bytes[offset]+bytes[offset+1]*256+bytes[offset+2]*65536;
    while(at+8<=end) {
      const kind=text(at,4),size=view.getUint32(at+4,true),start=at+8;
      if(size>end-start) throw new Error("The WebP contains a truncated chunk.");
      if(kind==="VP8X") {
        if(size<10) throw new Error("The WebP extended header is invalid.");
        if(bytes[start]&2) throw new Error("Use a still PNG or WebP image; animated maps are not supported.");
        canvas=checkDimensions(1+uint24(start+4),1+uint24(start+7));
      } else if(kind==="ANIM" || kind==="ANMF") throw new Error("Animated WebP images are not supported.");
      else if(kind==="VP8 ") {
        if(size<10 || text(start+3,3)!==String.fromCharCode(157,1,42)) throw new Error("The WebP frame header is invalid.");
        frame=checkDimensions(view.getUint16(start+6,true)&0x3fff,view.getUint16(start+8,true)&0x3fff);
      } else if(kind==="VP8L") {
        if(size<5 || bytes[start]!==0x2f || bytes[start+4]>>5) throw new Error("The lossless WebP header is invalid.");
        const packed=view.getUint32(start+1,true);
        frame=checkDimensions(1+(packed&0x3fff),1+((packed>>>14)&0x3fff));
      }
      at=start+size+(size%2);
    }
    if(!frame) throw new Error("The WebP has no supported still-image frame.");
    if(canvas && (canvas.width!==frame.width || canvas.height!==frame.height)) throw new Error("WebP canvas and frame sizes disagree.");
    return result("WebP","image/webp",frame.width,frame.height);
  }
  throw new Error("Choose a PNG, JPEG or still WebP file. TIFF/GeoTIFF, SVG, PDF, GIF, BMP and MBTiles are not supported by this image tool.");
}

export function validateBounds(value) {
  if(!value || !["geographic","webmercator"].includes(value.projection)) throw new Error("Choose the map’s actual projection: latitude/longitude grid or Web Mercator.");
  const {west,east,north,south,projection}=value;
  if(![west,east,north,south].every(Number.isFinite)) throw new Error("Enter all four outer-edge bounds as decimal degrees.");
  if(Math.abs(west)>180 || Math.abs(east)>180 || Math.abs(north)>90 || Math.abs(south)>90) throw new Error("Longitude must be within ±180° and latitude within ±90°.");
  if(north<=south) throw new Error("The north bound must be greater than the south bound.");
  const span=east>west ? east-west : east-west+360;
  if(span<=0 || span>360 || east===west) throw new Error("West and east must define a nonzero width. Use −180 to 180 for a full-world image.");
  if(projection==="webmercator" && (Math.abs(north)>MERCATOR_LIMIT || Math.abs(south)>MERCATOR_LIMIT)) throw new Error("Web Mercator bounds must stay within ±85.0511287798066° latitude.");
  return {projection,west,east,north,south};
}
export function pixelCoordinate(column,row,width,height,bounds) {
  checkDimensions(width,height);const b=validateBounds(bounds);
  if(!Number.isInteger(column)||!Number.isInteger(row)||column<0||row<0||column>=width||row>=height) throw new Error("Select a pixel inside the image.");
  const x=(column+.5)/width, y=(row+.5)/height;
  const span=b.east>b.west ? b.east-b.west : b.east-b.west+360;
  let lon=b.west+x*span; if(lon>180) lon-=360;
  let lat;
  if(b.projection==="geographic") lat=b.north+(b.south-b.north)*y;
  else {
    const forward=latitude=>Math.log(Math.tan(Math.PI/4+latitude*Math.PI/360));
    const projected=forward(b.north)+(forward(b.south)-forward(b.north))*y;
    lat=(Math.PI/2-2*Math.atan(Math.exp(-projected)))*180/Math.PI;
  }
  return {lat,lon};
}
export function validateBoundsFile(document,image) {
  if(!document || document.kind!==BOUNDS_KIND || document.schema_version!==1) throw new Error("Choose a FieldForge image-bounds file.");
  if(!image.sha256 || typeof document.image_sha256!=="string" || !/^[a-f0-9]{64}$/.test(document.image_sha256) || document.image_sha256!==image.sha256 || document.width!==image.width || document.height!==image.height) throw new Error("These bounds belong to a different image. Open the exact original image first.");
  return validateBounds(document.bounds);
}
export function imageViewport(width,height,viewportWidth,viewportHeight,zoom=1,cx=width/2,cy=height/2) {
  if(![width,height,viewportWidth,viewportHeight].every(v=>Number.isFinite(v)&&v>0)) throw new Error("Invalid image viewport.");
  const level=Math.min(16,Math.max(1,Number.isFinite(zoom)?zoom:1)),fit=Math.min(1,viewportWidth/width,viewportHeight/height),scale=fit*level;
  const clamp=(center,extent,visible)=>visible>=extent ? extent/2 : Math.max(visible/2,Math.min(extent-visible/2,center));
  const centerX=clamp(Number.isFinite(cx)?cx:width/2,width,viewportWidth/scale),centerY=clamp(Number.isFinite(cy)?cy:height/2,height,viewportHeight/scale);
  return {zoom:level,scale,cx:centerX,cy:centerY,left:viewportWidth/2-centerX*scale,top:viewportHeight/2-centerY*scale};
}
export function pixelAtScreen(x,y,view,width,height) {
  const column=Math.floor((x-view.left)/view.scale),row=Math.floor((y-view.top)/view.scale);
  return Number.isFinite(column)&&Number.isFinite(row)&&column>=0&&row>=0&&column<width&&row<height ? {column,row} : null;
}
