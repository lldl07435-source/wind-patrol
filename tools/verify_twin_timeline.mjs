import assert from 'node:assert/strict';
import {atTime,mergeFrames,normalizeReplay,enu,sorterPosition} from '../web/twin-timeline.js';

let passed=0;
function check(name,fn){fn();passed++;console.log('PASS '+name);}
check('wind position interpolates in ENU without advancing discrete mode',()=>{
  const frames=[{time_s:0,position:[0,0,2],wind:[1,0,0],battery:1,speed:0,wind_speed:1,target_distance:8,state:'PATROL',sensor_valid:true},{time_s:2,position:[4,6,4],wind:[3,2,0],battery:.9,speed:2,wind_speed:3,target_distance:4,state:'ABORTED',sensor_valid:false}];
  const f=atTime(frames,1,'wind');assert.deepEqual(f.position,[2,3,3]);assert.deepEqual(f.wind,[2,1,0]);assert.equal(f.state,'PATROL');assert.equal(f.sensor_valid,true);assert.equal(atTime(frames,2,'wind').state,'ABORTED');
});
check('parcel interpolation stays within the same physical item',()=>{
  const a={time_s:0,order_id:1,progress:.2,state:'TRANSIT',completed:0},b={time_s:1,order_id:2,progress:.8,state:'TRANSIT',completed:1};
  assert.equal(atTime([a,b],.5,'ld').progress,.2);assert.equal(atTime([a,b],.5,'ld').completed,0);
  assert.equal(atTime([a,{...b,order_id:1}],.5,'ld').progress,.5);
});
check('fault stops physical interpolation',()=>assert.equal(atTime([{time_s:0,order_id:1,progress:.64,state:'FAULT'},{time_s:3,order_id:1,progress:1,state:'TRANSIT'}],2,'ld').progress,.64));
check('seeking before and after a recording never extrapolates',()=>{
  const rows=[{time_s:1,order_id:1,progress:.2},{time_s:2,order_id:1,progress:.8}];assert.equal(atTime(rows,-3,'ld').progress,.2);assert.equal(atTime(rows,100,'ld').progress,.8);assert.equal(atTime([],0,'ld'),null);
});
check('live cursor merge keeps final signal at a duplicate timestamp',()=>assert.deepEqual(mergeFrames([{time_s:2,state:'TRANSIT'}],[{time_s:1,state:'ALIGN'},{time_s:2,state:'FAULT'}]),[{time_s:1,state:'ALIGN'},{time_s:2,state:'FAULT'}]));
check('invalid time values are rejected before animation',()=>{for(const time_s of [NaN,Infinity,-1])assert.throws(()=>mergeFrames([],[{time_s}]));});
check('world conversion preserves metre coordinates and north sign',()=>assert.deepEqual(enu([10,5,3]),[10,3,-5]));
check('outlet paths end at distinct bins and clamp out-of-range progress',()=>{assert.deepEqual(sorterPosition(-1,0),sorterPosition(0,0));assert.deepEqual(sorterPosition(3,1),sorterPosition(1,1));assert.ok(sorterPosition(1,0)[2]<0);assert.ok(sorterPosition(1,1)[2]>0);});
check('unsupported replay schema cannot be played',()=>assert.throws(()=>normalizeReplay({schema:'arbitrary',domain:'wind',frames:[]})));
console.log(passed+' timeline checks passed');
