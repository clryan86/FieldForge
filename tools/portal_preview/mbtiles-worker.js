// Runs only inside a dedicated, disposable worker, after the pinned SQL.js and core.
let mbPack=null;
const mbSQL=initSqlJs({print:()=>{},printErr:()=>{}});
self.onmessage=async event=> {
  const {id,kind,bytes,lat,lon,zoom}=event.data;
  try {
    const SQL=await mbSQL;let result;
    if(kind==="open") {mbPack?.db.close();mbPack=null;mbPack=inspectMBDatabase(SQL,new Uint8Array(bytes));result=mbPack.info;}
    else if(kind==="frame"&&mbPack) result=readMBFrame(mbPack,lat,lon,zoom);
    else throw new Error("Open a map pack first.");
    const transfer=kind==="frame" ? result.tiles.filter(tile=>tile.data).map(tile=>tile.data.buffer) : [];
    self.postMessage({id,result},transfer);
  } catch(error) { self.postMessage({id,error:error.message||"The map pack could not be read."}); }
};
