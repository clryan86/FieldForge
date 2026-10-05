// Runs only inside a dedicated, disposable worker, after the pinned SQL.js and core.
let mbPack=null;
const mbSQL=initSqlJs({print:()=>{},printErr:()=>{}});
self.onmessage=async event=> {
  const {id,kind,bytes,lat,lon,zoom,tiles}=event.data;
  try {
    const SQL=await mbSQL;let result;
    if(kind==="open") {mbPack?.db.close();mbPack=null;mbPack=inspectMBDatabase(SQL,new Uint8Array(bytes));result=mbPack.info;}
    else if(kind==="frame"&&mbPack) {result=readMBFrame(mbPack,lat,lon,zoom);if(mbPack.info.format==="pbf")result=await decodeVectorFrame(result);}
    else if(kind==="coverage"&&mbPack) result=readMBCoverage(mbPack,zoom);
    else if(kind==="route-tiles"&&mbPack) result=readMBRouteTiles(mbPack,zoom,tiles);
    else throw new Error("Open a map pack first.");
    const transfer=kind==="frame" ? result.tiles.filter(tile=>tile.data).map(tile=>tile.data.buffer) : [];
    self.postMessage({id,result},transfer);
  } catch(error) { self.postMessage({id,error:error.message||"The map pack could not be read."}); }
};
