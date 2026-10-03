// 离散信号取前一帧；只有位置、风矢量和同一件物料的位移做插值。
export const clamp = (value, a, b) => Math.max(a, Math.min(b, value));
export const stateNames = {
  LOCKED:'等待会话',IDLE:'待命',ALIGN:'分流换向',RELEASE:'单件放行',TRANSIT:'物料输送',
  SETTLE:'出口确认',DONE:'完成',FAULT:'故障锁定',PATROL:'航点巡检',RETURN:'安全返航',
  LAND:'降落',ABORTED:'安全中止',TIMEOUT:'时长耗尽',MANUAL:'手控飞行',STOPPED:'手控结束',completed:'确认完成',unknown:'未知结果',START:'任务启动',WAYPOINT:'航点到达'
};
export function mergeFrames(previous, incoming) {
  const map=new Map(previous.map(f=>[f.time_s,f]));
  for(const f of incoming) {
    if(!Number.isFinite(f.time_s)||f.time_s<0) throw Error('回放时间无效');
    map.set(f.time_s,f);
  }
  return [...map.values()].sort((a,b)=>a.time_s-b.time_s);
}
export function locate(frames,time) {
  let lo=0,hi=frames.length;
  while(lo<hi){const mid=(lo+hi)>>1;if(frames[mid].time_s<=time)lo=mid+1;else hi=mid;}
  return Math.max(0,lo-1);
}
export function atTime(frames,time,domain) {
  if(!frames.length)return null;
  const i=locate(frames,time), a=frames[i], b=frames[i+1];
  if(!b||time<a.time_s)return {...a,index:i};
  const ratio=clamp((time-a.time_s)/Math.max(.000001,b.time_s-a.time_s),0,1);
  const result={...a,index:i};
  if(domain==='wind') {
    result.position=a.position.map((v,j)=>v+(b.position[j]-v)*ratio);
    result.wind=a.wind.map((v,j)=>v+(b.wind[j]-v)*ratio);
    for(const key of ['battery','speed','wind_speed','target_distance'])result[key]=a[key]+(b[key]-a[key])*ratio;
  }else if(a.order_id===b.order_id&&a.state!=='FAULT'&&a.progress!=null&&b.progress!=null) {
    result.progress=a.progress+(b.progress-a.progress)*ratio;
  }
  return result;
}
export function enu(position) { return [position[0],position[2],-position[1]]; }
export function sorterPosition(progress,route) {
  const t=clamp(progress??0,0,1),sign=route===1?1:-1;
  if(t<.68)return [-2.6+t/.68*3.9,1.33,0];
  const q=(t-.68)/.32;
  return [1.3+q*1.5,1.33-q*.67,sign*q*1.35];
}
export function normalizeReplay(payload) {
  if(payload.schema!=='ld-twin/1'||!['ld','wind'].includes(payload.domain))throw Error('不支持的回放格式');
  return {...payload,frames:mergeFrames([],payload.frames||[]),events:[...(payload.events||[])].sort((a,b)=>a.time_s-b.time_s)};
}
