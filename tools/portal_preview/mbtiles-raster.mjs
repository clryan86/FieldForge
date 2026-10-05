import {imageHeader} from "./image-core.mjs";

// Native bitmap decoding cannot be aborted. Settle cancellation/timeouts promptly
// and close any bitmap that arrives later, rather than retaining its memory.
export function createMBRasterDecode(bytes,format) {
  let settled=false,timer,finish;
  const promise=new Promise((resolve,reject)=>{
    finish=(error,bitmap)=>{if(settled){bitmap?.close();return;}settled=true;clearTimeout(timer);if(error){bitmap?.close();reject(error);}else resolve(bitmap);};
    try{
      if(typeof createImageBitmap!=="function")throw new Error("This browser cannot decode raster tiles.");
      const header=imageHeader(bytes),expected=format==="png"?"PNG":format==="webp"?"WebP":["jpg","jpeg"].includes(format)?"JPEG":"";
      if(header.format!==expected||header.width!==header.height||![256,512].includes(header.width))throw new Error("Unsupported tile encoding or dimensions.");
      timer=setTimeout(()=>finish(new Error("Raster decoding exceeded 15 seconds; this tile was not verified.")),15000);
      Promise.resolve(createImageBitmap(new Blob([bytes],{type:header.mime}),{imageOrientation:"none"})).then(bitmap=>{
        if(bitmap.width!==header.width||bitmap.height!==header.height)finish(new Error("Decoded tile dimensions disagree with its header."),bitmap);
        else finish(null,bitmap);
      },error=>finish(new Error(error.message||"Raster tile could not be decoded.")));
    }catch(error){finish(error);}
  });
  return {promise,cancel:()=>finish(new Error("Raster decoding cancelled."))};
}
