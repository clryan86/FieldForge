// Bounded MVT 1/2 geometry preview; no publisher styles, fonts, sprites or network.
export const MAX_MVT_EXPANDED = 8 * 1024 * 1024;
export const MAX_MVT_FEATURES = 5000;
export const MAX_MVT_POINTS = 50000;

class MVTReader {
  constructor(bytes,budget) {this.bytes=bytes;this.at=0;this.budget=budget;}
  integer() {
    let result=0n;
    for(let i=0;i<10;i++){if(this.at>=this.bytes.length)throw new Error("Truncated protobuf integer.");const b=this.bytes[this.at++];if(i===9&&b>1)throw new Error("Protobuf integer exceeds 64 bits.");result|=BigInt(b&127)<<BigInt(i*7);if(b<128)return result;}
    throw new Error("Invalid protobuf integer.");
  }
  take(size) {if(!Number.isSafeInteger(size)||size<0||size>this.bytes.length-this.at)throw new Error("Truncated protobuf field.");const result=this.bytes.subarray(this.at,this.at+size);this.at+=size;return result;}
  fields() {
    const result=[];
    while(this.at<this.bytes.length){if(++this.budget.fields>200000)throw new Error("Vector tile has too many protobuf fields.");const key=this.integer();if(key>4294967295n||key<8n)throw new Error("Invalid protobuf field number.");const wire=Number(key&7n),number=Number(key>>3n);let value;
      if(wire===0)value=this.integer();else if(wire===1)value=this.take(8);else if(wire===2){const length=this.integer();if(length>BigInt(this.bytes.length))throw new Error("Invalid protobuf field length.");value=this.take(Number(length));}else if(wire===5)value=this.take(4);else throw new Error("Unsupported protobuf wire type.");
      result.push({number,wire,value});
    }return result;
  }
}
function mvtNumber(value,max=4294967295) {if(typeof value!=="bigint"||value<0n||value>BigInt(max))throw new Error("Vector tile integer is out of range.");return Number(value);}
function mvtText(bytes,max=16384) {if(bytes.length>max)throw new Error("Vector tile text exceeds its limit.");try{return new TextDecoder("utf-8",{fatal:true}).decode(bytes);}catch{throw new Error("Vector tile text is not UTF-8.");}}
function mvtClean(text,limit=48) {return [...text.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069\ufffe\uffff]/gu," ").replace(/\s+/g," ").trim()].slice(0,limit).join("");}
function mvtFields(bytes,budget) {return new MVTReader(bytes,budget).fields();}
function mvtPacked(field,budget) {
  if(field.wire===0){if(++budget.words>250000)throw new Error("Vector tile has too many geometry/tag words.");return [mvtNumber(field.value)];}if(field.wire!==2)throw new Error("Invalid packed vector field.");
  const reader=new MVTReader(field.value,budget),values=[];
  while(reader.at<reader.bytes.length){if(++budget.words>250000)throw new Error("Vector tile has too many geometry/tag words.");values.push(mvtNumber(reader.integer()));}return values;
}
function mvtValue(bytes,budget) {
  let result=null,seen=false;
  for(const f of mvtFields(bytes,budget)) {
    if(f.number<1||f.number>7)continue;if(seen)throw new Error("Ambiguous vector property value.");seen=true;
    if(f.number===1&&f.wire===2)result=mvtText(f.value);
    else if((f.number===2&&f.wire===5)||(f.number===3&&f.wire===1)){const view=new DataView(f.value.buffer,f.value.byteOffset,f.value.byteLength);result=f.number===2?view.getFloat32(0,true):view.getFloat64(0,true);if(!Number.isFinite(result))throw new Error("Non-finite vector property.");}
    else if(f.number>=4&&f.wire===0){if(f.number===7){if(f.value>1n)throw new Error("Invalid boolean property.");result=f.value===1n;}else{const number=f.number===6 ? (f.value>>1n)^-(f.value&1n) : f.number===4 ? BigInt.asIntN(64,f.value) : f.value;result=String(number);}}
    else throw new Error("Wrong protobuf wire type for a vector property.");
  }if(!seen)throw new Error("Empty vector property value.");return result;
}
function mvtGeometry(words,type,extent,budget) {
  let at=0,x=0,y=0,path=null;const paths=[];
  const finishLine=()=>{if(path){if(path.length<2)throw new Error("Incomplete vector line.");paths.push(path);path=null;}};
  while(at<words.length){const command=words[at++],id=command%8,count=Math.floor(command/8);if(!count||![1,2,7].includes(id))throw new Error("Invalid vector geometry command.");
    if(id===7){if(type!==3||count!==1||!path||path.length<3)throw new Error("Invalid polygon close command.");paths.push(path);path=null;continue;}
    if(type===1&&id!==1)throw new Error("Point geometry contains a line command.");
    if(type!==1&&id===1&&count!==1)throw new Error("Line/polygon MoveTo must contain one position.");
    if(id===2&&!path)throw new Error("LineTo appears before MoveTo.");
    if(id===1&&type===3&&path)throw new Error("Polygon ring was not closed.");
    if(count>Math.floor((words.length-at)/2))throw new Error("Truncated vector coordinate pair.");
    for(let i=0;i<count;i++){
      const dx=words[at++],dy=words[at++];x+=dx%2?-(dx+1)/2:dx/2;y+=dy%2?-(dy+1)/2:dy/2;
      if(x < -extent||x>2*extent||y < -extent||y>2*extent)throw new Error("Vector coordinates exceed the supported tile buffer.");
      if(++budget.points>MAX_MVT_POINTS)throw new Error("Vector tile exceeds 50,000 positions.");const point=[x*256/extent,y*256/extent];
      if(type===1)paths.push([point]);else if(id===1){if(type===2)finishLine();path=[point];}else path.push(point);
    }
  }
  if(type===3&&path)throw new Error("Polygon ring was not closed.");if(type===2)finishLine();if(!paths.length)throw new Error("Vector feature has no geometry.");return paths;
}
function mvtStyle(layer,properties) {
  const name=layer.toLowerCase(),kind=String(properties.class||properties.subclass||"").toLowerCase();
  if(/water|ocean|lake|river/.test(name))return "water";
  if(/park|landcover|landuse/.test(name)||name==="land")return "green";
  if(name.includes("building"))return "building";
  if(/transportation|road|highway/.test(name))return ["motorway","trunk","primary"].includes(kind)?"major":"road";
  if(/boundary|admin/.test(name))return "boundary";if(name.includes("rail"))return "rail";return "minor";
}
export function parseMVT(bytes) {
  if(!(bytes instanceof Uint8Array)||!bytes.length||bytes.length>MAX_MVT_EXPANDED)throw new Error("Vector tile is empty or exceeds 8 MiB expanded.");
  const budget={fields:0,words:0,features:0,points:0},features=[],layers=[],layerSet=new Set();
  for(const field of mvtFields(bytes,budget)) {
    if(field.number!==3)continue;if(field.wire!==2)throw new Error("Invalid vector layer field.");if(layers.length>=64)throw new Error("Vector tile exceeds 64 layers.");
    let name=null,extent=4096,version=null;const rawFeatures=[],keys=[],values=[],seen=new Set();
    for(const f of mvtFields(field.value,budget)){
      if([1,5,15].includes(f.number)){if(seen.has(f.number))throw new Error("Duplicate vector layer metadata.");seen.add(f.number);}
      if(f.number===1&&f.wire===2)name=mvtText(f.value,256);
      else if(f.number===2&&f.wire===2){if(++budget.features>MAX_MVT_FEATURES)throw new Error("Vector tile exceeds 5,000 features.");rawFeatures.push(f.value);}
      else if(f.number===3&&f.wire===2)keys.push(mvtText(f.value,256));
      else if(f.number===4&&f.wire===2)values.push(mvtValue(f.value,budget));
      else if(f.number===5&&f.wire===0)extent=mvtNumber(f.value,65536);
      else if(f.number===15&&f.wire===0)version=mvtNumber(f.value,2);
      else if([1,2,3,4,5,15].includes(f.number))throw new Error("Wrong wire type in vector layer.");
    }
    if(!name||!extent||![1,2].includes(version)||layerSet.has(name))throw new Error("Invalid layer name, extent or version.");layerSet.add(name);layers.push(mvtClean(name,80));
    for(const raw of rawFeatures){let type=null;const tags=[],words=[],properties=Object.create(null);
      for(const f of mvtFields(raw,budget)){if(f.number===2||f.number===4){const target=f.number===2?tags:words;for(const word of mvtPacked(f,budget))target.push(word);}else if(f.number===3){if(type!==null||f.wire!==0)throw new Error("Invalid feature geometry type.");type=mvtNumber(f.value,3);}else if(f.number===1&&f.wire!==0)throw new Error("Invalid feature ID.");}
      if(![1,2,3].includes(type)||tags.length%2)throw new Error("Unsupported geometry or incomplete feature tags.");
      for(let i=0;i<tags.length;i+=2){if(tags[i]>=keys.length||tags[i+1]>=values.length)throw new Error("Missing vector property reference.");const key=keys[tags[i]];if(Object.hasOwn(properties,key))throw new Error("Duplicate feature property.");properties[key]=values[tags[i+1]];}
      const label=type===1 ? ["name:en","name_en","name:latin","name:local","name"].map(key=>properties[key]).find(value=>typeof value==="string"&&value.trim()) : "";
      features.push({type,style:mvtStyle(name,properties),paths:mvtGeometry(words,type,extent,budget),label:label?mvtClean(label):""});
    }
  }
  if(!layers.length)throw new Error("No Mapbox Vector Tile layers found.");return {features,layers,positions:budget.points};
}
export function decodeVectorTile(bytes) {
  return (async()=>{
    if(!(bytes instanceof Uint8Array)||!bytes.length||bytes.length>2*1024*1024)throw new Error("Vector tile exceeds the 2 MiB input limit.");
    if(bytes[0]!==31||bytes[1]!==139)return parseMVT(bytes);
    if(typeof DecompressionStream!=="function")throw new Error("Gzip vector tiles need a browser with DecompressionStream support.");
    const reader=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip")).getReader(),chunks=[];let size=0;
    try {while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>MAX_MVT_EXPANDED)throw new Error("Expanded vector tile exceeds 8 MiB.");chunks.push(value);}}
    catch(error){await reader.cancel().catch(()=>{});throw new Error(error.message||"Unreadable gzip vector tile.");}finally{reader.releaseLock();}
    const decoded=new Uint8Array(size);let at=0;for(const chunk of chunks){decoded.set(chunk,at);at+=chunk.length;}return parseMVT(decoded);
  })();
}
export function decodeVectorFrame(frame) {
  return (async()=>{
    let positions=0,features=0;const layers=new Set();
    for(const tile of frame.tiles){if(!tile.data)continue;
      if(positions>=100000||features>=10000){delete tile.data;tile.issue="Vector frame limit";continue;}
      try{const vector=await decodeVectorTile(tile.data);if(positions+vector.positions>100000||features+vector.features.length>10000)throw new Error("Vector frame limit");positions+=vector.positions;features+=vector.features.length;vector.layers.forEach(name=>layers.add(name));tile.vector=vector;}
      catch(error){tile.issue=error.message||"Unreadable vector tile";}
      delete tile.data;
    }
    return {...frame,vectorStats:{features,positions,layers:[...layers]}};
  })();
}
