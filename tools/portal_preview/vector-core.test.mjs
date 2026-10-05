import test from "node:test";
import assert from "node:assert/strict";
import {parseGeoJSON,projectVectors,vectorPath,vectorPlace,selectedGeoJSON,MAX_VECTOR_BYTES} from "./vector-core.mjs";
import {validatePlace} from "./places-core.mjs";
const geometry = (type,coordinates) => ({type,coordinates});
const feature = (value,name="Test") => ({type:"Feature",geometry:value,properties:{name}});
const parse = value => parseGeoJSON(JSON.stringify(value));
const outer = [[0,0],[4,0],[4,4],[0,4],[0,0]], hole = [[1,1],[1,2],[2,2],[2,1],[1,1]];

test("GeoJSON renders every supported geometry type and preserves polygon hole subpaths",()=> {
  const types=[geometry("Point",[0,0,25]),geometry("MultiPoint",[[1,2],[2,3]]),geometry("LineString",[[0,0],[1,1]]),geometry("MultiLineString",[[[0,0],[1,1]],[[2,2],[3,3]]]),geometry("Polygon",[outer,hole]),geometry("MultiPolygon",[[outer],[hole]]),{type:"GeometryCollection",geometries:[geometry("Point",[0,0]),geometry("LineString",[[1,1],[2,2]])]}];
  const data=parse({type:"FeatureCollection",features:types.map((g,i)=>feature(g,String(i)))});
  assert.equal(data.features.length,7); assert.equal(data.features[0].vertices[0][2],25);
  const projected=projectVectors(data), polygon=projected.features[4].shapes[0], path=vectorPath(polygon);
  assert.equal((path.match(/M/g)||[]).length,2); assert.equal((path.match(/Z/g)||[]).length,2); assert.ok(!path.includes("NaN"));
  for(const f of projected.features) for(const [x,y] of f.vertices) { assert.ok(x>=24&&x<=776); assert.ok(y>=24&&y<=356); }
  const [origin,north]=projectVectors(parse(geometry("MultiPoint",[[0,0],[0,1]]))).features[0].vertices;
  assert.ok(north[1]<origin[1]); assert.equal(north[0],origin[0]);
});
test("bare points, null geometries and polar or date-line coordinates have explicit finite handling",()=> {
  const data=parse({type:"FeatureCollection",features:[feature(null),feature(geometry("Point",[180,90]))]});
  assert.equal(data.unlocated,1); assert.deepEqual(projectVectors(data).features[1].vertices,[[400,190]]);
  assert.throws(()=>parse(feature(null)),/no drawable/);
  const split=parse(geometry("MultiLineString",[[[170,10],[180,11]],[[-180,11],[-170,12]]]));
  assert.equal(split.parts,2); assert.equal(projectVectors(split).bounds.west,-180);
  assert.throws(()=>parse(geometry("LineString",[[179,0],[-179,0]])),/Split date-line/);
});
test("invalid coordinates, rings, CRS declarations and mixed invalid features reject the entire file",()=> {
  const bad=[geometry("Point",[91,181]),geometry("Point",[0,"0"]),geometry("Point",[0,0,0,0]),geometry("LineString",[[0,0]]),geometry("Polygon",[[[0,0],[1,0],[1,1],[0,1]]]),geometry("Polygon",[[[0,0,1],[1,0,1],[1,1,1],[0,0,2]]]),geometry("CircularString",[[0,0],[1,1]]),{...geometry("Point",[0,0]),crs:null}];
  for(const g of bad) assert.throws(()=>parse({type:"FeatureCollection",features:[feature(geometry("Point",[0,0])),feature(g)]}));
  assert.throws(()=>parse({...feature(geometry("Point",[0,0])),properties:[]}));
  assert.throws(()=>parseGeoJSON('{"type":"Feature","geometry":{"type":"Point","coordinates":[0,0]},"properties":{"too_big":1e400}}'),/finite numbers/);
});
test("file, feature, position, part and geometry-depth budgets stop oversized inputs",()=> {
  assert.throws(()=>parseGeoJSON(" ".repeat(MAX_VECTOR_BYTES+1)),/4 MiB/);
  assert.throws(()=>parse({type:"FeatureCollection",features:Array.from({length:1001},()=>feature(geometry("Point",[0,0])))}),/1,000/);
  assert.throws(()=>parse(geometry("LineString",Array.from({length:10001},()=>[0,0]))),/10,000/);
  assert.throws(()=>parse(geometry("MultiPoint",Array.from({length:2001},()=>[0,0]))),/2,000/);
  let g=geometry("Point",[0,0]);for(let i=0;i<10;i++)g={type:"GeometryCollection",geometries:[g]};assert.throws(()=>parse(g),/nested/);
});
test("selected vertices retain lon-lat order, full numeric precision and safe filename provenance",()=> {
  const raw=feature(geometry("LineString",[[179.999999999,1e-10],[180,2]]),"\u202eBad\nlabel 🧭"), data=parse(raw);
  const place=vectorPlace(data.features[0],0,"file\u202e\n<script>.geojson"); assert.deepEqual(validatePlace(place),place);
  assert.equal(place.lat,1e-10); assert.equal(place.lon,179.999999999); assert.ok(place.source.includes("file"));
  assert.throws(()=>vectorPlace(data.features[0],3,"test"),/vertex/);
});
test("selected feature export retains attributes, geometry and ID without foreign feature metadata",()=> {
  const raw={...feature(geometry("Polygon",[outer,hole]),'<img src="https://example.invalid">'),id:"area-1",bbox:[0,0,4,4],foreign:"not exported"};
  raw.properties.nested={x:[1,2]}; raw.properties.html="</script>";
  const saved=JSON.parse(selectedGeoJSON(parse(raw).features[0]));
  assert.deepEqual(saved,{type:"Feature",properties:raw.properties,geometry:raw.geometry,id:"area-1"});
  assert.equal(parse(saved).features[0].vertices.length,10);
});
