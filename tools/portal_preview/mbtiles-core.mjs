export const MAX_MB_BYTES = 64 * 1024 * 1024;
export const MAX_MB_TILE_BYTES = 2 * 1024 * 1024;
export const MB_LAT_LIMIT = 85.0511287798066;
export const MAX_MB_COVERAGE_ROWS = 50000;
export function checkMBHeader(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.length<100 || bytes.length>MAX_MB_BYTES) throw new Error("Choose a closed MBTiles export no larger than 64 MiB. Compatible larger packs can use the desktop map viewer.");
  if (String.fromCharCode(...bytes.subarray(0,16))!=="SQLite format 3\0") throw new Error("This is not a SQLite MBTiles file.");
  if(bytes[18]!==1||bytes[19]!==1) throw new Error("WAL-mode databases are not supported. Export a closed, single-file rollback-mode copy first.");
  const raw=bytes[16]*256+bytes[17],size=raw===1 ? 65536 : raw;
  if(size<512||size>65536||(size&(size-1))||bytes.length%size) throw new Error("Invalid or truncated SQLite page layout.");
}
function mbRows(db,sql,values=[],limit=129) {
  const stmt=db.prepare(sql); try { stmt.bind(values);const rows=[];while(stmt.step()) { if(rows.length>=limit) throw new Error("Map structure exceeds this viewer’s limits.");rows.push(stmt.get()); }return rows; } finally {stmt.free();}
}
function mbQuote(value) { return '"'+String(value).replace(/"/g,'""')+'"'; }
export function inspectMBDatabase(SQL,bytes) {
  checkMBHeader(bytes); const db=new SQL.Database(bytes);
  try {
    db.run("PRAGMA query_only=ON; PRAGMA trusted_schema=OFF; PRAGMA cache_size=-4096;");
    const tables=mbRows(db,"SELECT name,type,substr(sql,1,2048) FROM sqlite_master WHERE name IN ('metadata','tiles')",[],2);
    if(tables.length!==2||tables.some(row=>row[1]!=="table"||!/^\s*CREATE\s+TABLE\b/i.test(row[2]||""))) throw new Error("Use ordinary metadata and tiles tables. Normalized/view-based MBTiles are not supported in this browser viewer.");
    for(const [table,expected] of [["metadata",[["name","TEXT"],["value","TEXT"]]],["tiles",[["zoom_level","INTEGER"],["tile_column","INTEGER"],["tile_row","INTEGER"],["tile_data","BLOB"]]]]) {
      const columns=mbRows(db,`PRAGMA table_info(${table})`,[],8).map(row=>[row[1],String(row[2]).toUpperCase()]);
      if(JSON.stringify(columns)!==JSON.stringify(expected)) throw new Error("Unsupported MBTiles columns or declared types.");
    }
    let index="";
    for(const row of mbRows(db,"PRAGMA index_list(tiles)",[],64)) if(row[2]&&!row[4]) {
      const keys=mbRows(db,`PRAGMA index_xinfo(${mbQuote(row[1])})`,[],8).filter(key=>key[5]);
      if(JSON.stringify(keys.map(key=>key[2]))===JSON.stringify(["zoom_level","tile_column","tile_row"])&&keys.every(key=>key[4]==="BINARY")) {index=row[1];break;}
    }
    if(!index) throw new Error("A unique, non-partial tile index on zoom_level, tile_column, tile_row is required. This viewer never changes your file.");
    const sizes=mbRows(db,"SELECT length(CAST(name AS BLOB)),length(CAST(value AS BLOB)) FROM metadata LIMIT 129",[],129);
    if(sizes.length>128||sizes.some(([a,b])=>!Number.isInteger(a)||!Number.isInteger(b)||a>128||b>16384)) throw new Error("Map metadata is too large or invalid.");
    const metadata=Object.create(null);
    for(const [key,value] of mbRows(db,"SELECT name,value FROM metadata LIMIT 129")) {
      if(typeof key!=="string"||typeof value!=="string"||Object.hasOwn(metadata,key)||(key+value).includes("\0")) throw new Error("Duplicate or invalid map metadata.");
      metadata[key]=value;
    }
    if(!metadata.name?.trim()) throw new Error("The pack needs a name in its metadata.");
    if((metadata.scheme||"tms").toLowerCase()!=="tms") throw new Error("This viewer needs MBTiles/TMS tile rows, not XYZ rows.");
    const format=(metadata.format||"").toLowerCase();
    if(!["png","jpg","jpeg","webp","pbf"].includes(format)) throw new Error("Choose MBTiles declared as PNG, JPEG, WebP or PBF vector tiles.");
    const table=`tiles INDEXED BY ${mbQuote(index)}`;
    for(const order of ["ASC","DESC"]) { const row=mbRows(db,`SELECT zoom_level,typeof(zoom_level) FROM ${table} ORDER BY zoom_level ${order} LIMIT 1`,[],1)[0]; if(!row||row[1]!=="integer"||!Number.isInteger(row[0])||row[0]<0||row[0]>22) throw new Error("The pack must have integer zoom levels from 0 to 22."); }
    const zooms=[];for(let z=0;z<=22;z++) if(mbRows(db,`SELECT 1 FROM ${table} WHERE zoom_level=? LIMIT 1`,[z],1).length) zooms.push(z);
    const z=zooms[0],sample=mbRows(db,`SELECT tile_column,tile_row,typeof(tile_column),typeof(tile_row) FROM ${table} WHERE zoom_level=? LIMIT 1`,[z],1)[0];
    if(!sample||sample[2]!=="integer"||sample[3]!=="integer"||sample.slice(0,2).some(v=>!Number.isInteger(v)||v<0||v>=2**z)) throw new Error("The initial stored tile has invalid coordinates.");
    const initial={...mbUnproject((sample[0]+.5)*256,(2**z-1-sample[1]+.5)*256,z),zoom:z};
    return {db,table,info:{name:metadata.name,format,attribution:metadata.attribution||"No attribution supplied. Check the map source and reuse terms.",description:metadata.description||"",zooms,initial}};
  } catch(error) {db.close();throw error;}
}
export function mbUnproject(x,y,z) {
  const scale=256*2**z;
  return {lon:((x/scale*360)%360+360)%360-180,lat:Math.atan(Math.sinh(Math.PI*(1-2*y/scale)))*180/Math.PI};
}
export function mbFrame(lat,lon,zoom) {
  if(!Number.isFinite(lat)||Math.abs(lat)>MB_LAT_LIMIT||!Number.isFinite(lon)||Math.abs(lon)>180||!Number.isInteger(zoom)||zoom<0||zoom>22) throw new Error("Use longitude within ±180°, Web Mercator latitude within ±85.05112878°, and an available zoom.");
  const count=2**zoom,scale=256*count,x=(lon+180)/360*scale,y=(1-Math.asinh(Math.tan(lat*Math.PI/180))/Math.PI)/2*scale;
  const left=x-384,top=y-256,tiles=[];
  for(let row=Math.floor(top/256);row<Math.ceil((top+512)/256);row++) for(let col=Math.floor(left/256);col<Math.ceil((left+768)/256);col++) {
    tiles.push({z:zoom,x:((col%count)+count)%count,y:row,tms:count-1-row,left:col*256-left,top:row*256-top,outside:row<0||row>=count});
  }
  return {lat,lon,zoom,left,top,tiles};
}
export function mbScreenPoint(lat,lon,frame) {
  const point=mbFrame(lat,lon,frame.zoom),world=256*2**frame.zoom,delta=point.left-frame.left;
  const x=384+((delta+world/2)%world+world)%world-world/2,y=point.top+256-frame.top;
  return {x,y,inside:x>=0&&x<768&&y>=0&&y<512};
}
export function readMBFrame(pack,lat,lon,zoom) {
  if(!pack.info.zooms.includes(zoom)) throw new Error("That zoom level is not stored in this pack.");
  const frame=mbFrame(lat,lon,zoom);let total=0;
  const tiles=frame.tiles.map(slot=> {
    if(slot.outside) return {...slot,issue:"Outside Mercator world"};
    const size=mbRows(pack.db,`SELECT typeof(tile_data),length(tile_data) FROM ${pack.table} WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 1`,[zoom,slot.x,slot.tms],1)[0];
    if(!size) return {...slot,issue:"Missing tile"};
    if(size[0]!=="blob"||!Number.isInteger(size[1])||size[1]<(pack.info.format==="pbf"?1:12)||size[1]>MAX_MB_TILE_BYTES||total+size[1]>16*1024*1024) return {...slot,issue:"Unsupported tile size"};
    const data=mbRows(pack.db,`SELECT tile_data FROM ${pack.table} WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 1`,[zoom,slot.x,slot.tms],1)[0]?.[0];
    if(!(data instanceof Uint8Array)||data.length!==size[1]) return {...slot,issue:"Unreadable tile"};
    total+=data.length;return {...slot,data};
  });
  return {...frame,tiles};
}

// Read only the selected zoom's indexed coordinates, never tile blobs or
// declared coverage metadata. One extra row establishes a partial result.
export function readMBCoverage(pack,zoom) {
  if(!pack.info.zooms.includes(zoom))throw new Error("Choose a stored zoom level to inspect coverage.");
  const rows=mbRows(pack.db,`SELECT tile_column,tile_row,typeof(tile_column),typeof(tile_row) FROM ${pack.table} WHERE zoom_level=? ORDER BY tile_column,tile_row LIMIT ?`,[zoom,MAX_MB_COVERAGE_ROWS+1],MAX_MB_COVERAGE_ROWS+1);
  const partial=rows.length>MAX_MB_COVERAGE_ROWS,scanned=Math.min(rows.length,MAX_MB_COVERAGE_ROWS),count=2**zoom,groups=new Map();let invalid=0;
  for(let i=0;i<scanned;i++){
    const [x,tms,xType,yType]=rows[i];
    if(xType!=="integer"||yType!=="integer"||!Number.isInteger(x)||!Number.isInteger(tms)||x<0||tms<0||x>=count||tms>=count){invalid++;continue;}
    const y=count-1-tms,column=Math.floor(x*32/count),row=Math.floor(y*32/count),key=row*32+column;
    if(groups.has(key)){groups.get(key).count++;continue;}
    groups.set(key,{column,row,span:Math.max(1,32/count),count:1,sample:{x,y,tms,...mbUnproject((x+.5)*256,(y+.5)*256,zoom)}});
  }
  return {zoom,scanned,valid:scanned-invalid,invalid,partial,limit:MAX_MB_COVERAGE_ROWS,cells:[...groups.values()].sort((a,b)=>a.row-b.row||a.column-b.column)};
}
