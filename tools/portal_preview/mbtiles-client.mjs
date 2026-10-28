export function createMBFileRead(file) {
  if(typeof FileReader!=="function") throw new Error("This browser cannot read a local MBTiles file. Use a current desktop browser.");
  const reader=new FileReader();let settled=false,timer,finish;
  const promise=new Promise((resolve,reject)=> {
    finish=(error,bytes,abort=false)=> {
      if(settled)return;settled=true;clearTimeout(timer);
      reader.onload=reader.onerror=reader.onabort=null;
      if(abort&&reader.readyState===1)reader.abort();
      if(error)reject(error);else resolve(bytes);
    };
    reader.onload=()=>finish(null,reader.result);
    reader.onerror=()=>finish(new Error("The map file could not be read. Reopen a fully downloaded local copy."));
    reader.onabort=()=>finish(new Error("Map file read cancelled."));
    timer=setTimeout(()=>finish(new Error("Map file read exceeded 15 seconds and was stopped. Reopen a fully downloaded local copy."),null,true),15000);
    try {reader.readAsArrayBuffer(file);}catch(error){finish(error,null,true);}
  });
  return {promise,cancel:()=>finish(new Error("Map file read cancelled."),null,true)};
}

export function createMBClient() {
  if(typeof Worker!=="function") throw new Error("This browser cannot run the local MBTiles worker. Use a current desktop browser.");
  const encoded=document.getElementById("mbWorkerPayload").textContent.trim();
  if(!encoded) throw new Error("The offline SQLite reader is missing. Download the complete tools file again.");
  const binary=atob(encoded),bytes=new Uint8Array(binary.length);for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
  const url=URL.createObjectURL(new Blob([bytes],{type:"text/javascript"}));let worker;
  try {worker=new Worker(url);} catch(error) {URL.revokeObjectURL(url);throw error;}
  let serial=0,closed=false;const pending=new Map();
  function close(reason="Map read cancelled.") {if(closed)return;closed=true;worker.terminate();URL.revokeObjectURL(url);for(const job of pending.values()){clearTimeout(job.timer);job.reject(new Error(reason));}pending.clear();}
  worker.onmessage=event=> {const {id,result,error}=event.data,job=pending.get(id);if(!job||closed)return;pending.delete(id);clearTimeout(job.timer);if(error)job.reject(new Error(error));else job.resolve(result);};
  worker.onerror=()=>close("The local SQLite reader stopped. Reopen a smaller, trusted map pack.");
  function request(kind,values={},transfer=[]) {
    if(closed)return Promise.reject(new Error("Reopen the map pack to continue."));
    return new Promise((resolve,reject)=> {const id=++serial,timer=setTimeout(()=>close("Map read exceeded 15 seconds and was stopped. Reopen a smaller, indexed pack."),15000);pending.set(id,{resolve,reject,timer});try{worker.postMessage({id,kind,...values},transfer);}catch(error){close(error.message);}});
  }
  return {request,close};
}
