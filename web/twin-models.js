import * as T from './three.module.js';
import {enu,sorterPosition,clamp} from './twin-timeline.js';

export const aircraft=[
  {id:'inspection',name:'工业巡检四旋翼',rotors:4,size:1.15,color:0xe9eef0,fold:false,camera:true},
  {id:'folding',name:'便携折叠四旋翼',rotors:4,size:.8,color:0xaeb9c3,fold:true,camera:true},
  {id:'mini',name:'轻型迷你四旋翼',rotors:4,size:.62,color:0xf4eee4,fold:true,camera:true},
  {id:'fpv',name:'FPV 穿越机',rotors:4,size:.7,color:0x202934,fold:false,camera:true},
  {id:'cine',name:'带桨保护圈航拍机',rotors:4,size:.8,color:0xe0e8eb,fold:false,camera:true,guards:true},
  {id:'hex',name:'工业六旋翼',rotors:6,size:1.5,color:0xf3ad30,fold:false,camera:true},
  {id:'octo',name:'重载八旋翼',rotors:8,size:1.7,color:0xd7e1e8,fold:false,camera:true},
  {id:'coaxial',name:'共轴 X8 多旋翼',rotors:4,size:1.5,color:0x262e3a,fold:false,camera:true,coaxial:true}
];
export const sorterScenes=[
  ['belt','双出口传送带'],['color','颜色识别分拣'],['size','尺寸分级分拣'],
  ['weight','称重分级分拣'],['barcode','扫码四出口分拣'],['rework','重检分流工位']
];

function material(color,metalness=.05,roughness=.65){return new T.MeshStandardMaterial({color,metalness,roughness});}
function mesh(group,geo,mat,xyz=[0,0,0],rotation){const m=new T.Mesh(geo,mat);m.position.set(...xyz);if(rotation)m.rotation.set(...rotation);m.castShadow=true;m.receiveShadow=true;group.add(m);return m;}
function box(g,d,m,p,r){return mesh(g,new T.BoxGeometry(...d),m,p,r);}
function cylinder(g,radius,height,m,p,r){return mesh(g,new T.CylinderGeometry(radius,radius,height,20),m,p,r);}
function bar(g,a,b,r,m){const av=new T.Vector3(...a),bv=new T.Vector3(...b);const q=cylinder(g,r,av.distanceTo(bv),m,av.clone().add(bv).multiplyScalar(.5).toArray());q.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),bv.sub(av).normalize());return q;}
function line(g,points,color,dashed=false){const mat=dashed?new T.LineDashedMaterial({color,dashSize:.6,gapSize:.35}):new T.LineBasicMaterial({color});const l=new T.Line(new T.BufferGeometry().setFromPoints(points.map(p=>new T.Vector3(...p))),mat);if(dashed)l.computeLineDistances();g.add(l);return l;}
function ring(g,r,mat,p){return mesh(g,new T.TorusGeometry(r,.025,8,48),mat,p,[Math.PI/2,0,0]);}
function label(g,text,p,{color='#cfe6ef',background='#132434',scale=1.2}={}){
  const c=document.createElement('canvas');c.width=512;c.height=96;const x=c.getContext('2d');
  x.fillStyle=background;x.fillRect(0,0,512,96);x.font='500 34px Segoe UI, Microsoft YaHei';x.textAlign='center';x.textBaseline='middle';x.fillStyle=color;x.fillText(text,256,48,480);
  const texture=new T.CanvasTexture(c);texture.colorSpace=T.SRGBColorSpace;
  const s=new T.Sprite(new T.SpriteMaterial({map:texture,depthTest:true,transparent:true}));s.scale.set(scale,scale*96/512,1);s.position.set(...p);g.add(s);return s;
}
function floor(scene,size){const g=new T.Group();scene.add(g);const m=material(0x142331,.2,.85);box(g,[size,.12,size],m,[0,-.12,0]);const grid=new T.GridHelper(size,Math.min(100,Math.ceil(size)),0x324758,0x253848);grid.position.y=-.052;g.add(grid);return g;}

export function makeConveyor(scene,sceneId='belt'){
  const g=new T.Group();scene.add(g);floor(scene,24);
  const steel=material(0xa8b5c0,.75,.34),dark=material(0x263644,.7,.42),beltMat=material(0x263b40,.12,.87),yellow=material(0xffb34b,.35,.45),teal=material(0x2cbdad,.5,.4),rubber=material(0x19242e,.0,.9),blue=material(0x4f9dde,.4,.42);
  const legs=[];
  for(const x of [-2.6,-.6,1.45])for(const z of [-.64,.64]){box(g,[.09,1.1,.09],steel,[x,.48,z]);box(g,[.22,.04,.22],rubber,[x,-.05,z]);legs.push([x,z]);}
  for(const z of [-.63,.63]){box(g,[4.7,.22,.09],steel,[-.6,1.05,z]);box(g,[4.8,.055,.045],yellow,[-.6,1.31,z]);}
  box(g,[4.8,.14,1.15],beltMat,[-.6,1.18,0]);
  const rollers=[];
  for(let x=-2.95;x<1.82;x+=.25){const roller=cylinder(g,.09,1.1,steel,[x,1.16,0],[Math.PI/2,0,0]);rollers.push(roller);}
  const beltLines=new T.Group();g.add(beltLines);
  for(let i=0;i<30;i++)box(beltLines,[.015,.012,1.06],dark,[-3+i*.16,1.263,0]);
  box(g,[.4,.4,.42],blue,[-2.55,.91,.96]);cylinder(g,.15,.38,dark,[-2.55,.91,1.27],[Math.PI/2,0,0]);box(g,[.35,.05,.48],steel,[-2.55,.63,1.05]);
  const gate=new T.Group();g.add(gate);gate.position.set(-2.3,1.35,0);box(gate,[.08,.3,1.03],yellow,[0,.15,0]);
  for(const z of [-.74,.74])box(g,[.06,.75,.06],dark,[-2.3,1.56,z]);bar(g,[-2.3,1.96,-.74],[-2.3,1.96,.74],.035,steel);
  const selector=new T.Group();g.add(selector);selector.position.set(1.17,1.31,0);box(selector,[1.06,.12,.075],teal,[.45,.03,0]);cylinder(g,.09,.3,dark,[1.17,1.05,0]);
  const branches=[];const four=sceneId==='barcode';
  for(let route=0;route<(four?4:2);route++){
    const z=four?[-1.65,-.65,.65,1.65][route]:(route===0?-1.35:1.35);
    const a=[1.3,1.2,0],b=[2.8,.64,z];const center=new T.Vector3(...a).add(new T.Vector3(...b)).multiplyScalar(.5);const path=new T.Group();g.add(path);path.position.copy(center);path.rotation.y=-Math.atan2(z,1.5);path.rotation.z=-.29;
    box(path,[Math.hypot(1.5,z),.07,.48],steel,[0,0,0]);for(const edge of [-.26,.26])box(path,[Math.hypot(1.5,z),.14,.035],yellow,[0,.04,edge]);
    box(g,[.95,.07,.67],dark,[2.95,.12,z]);for(const edge of [-.4,.4])box(g,[.08,.65,.67],route%2?blue:teal,[2.95+edge,.42,z]);for(const edge of [-.3,.3])box(g,[.75,.65,.04],route%2?blue:teal,[2.95,.42,z+edge]);
    label(g,(four?'出口 '+(route+1):route?'B / 右出口':'A / 左出口'),[3,.96,z],{scale:1.2});branches.push(z);
  }
  const beams=[];for(const [x,z,caption] of [[-1.85,0,'入口光电'],[2.62,branches[0],'A 出口光电'],[2.62,branches.at(-1),'B 出口光电']]){
    for(const sign of [-1,1]){box(g,[.065,.28,.08],dark,[x,1.39,z+sign*.33]);box(g,[.075,.06,.03],material(0xec6153,.2),[x,1.45,z+sign*.28]);}
    const beam=bar(g,[x,1.45,z-.28],[x,1.45,z+.28],.01,new T.MeshBasicMaterial({color:0x3bcaba,transparent:true,opacity:.3}));beams.push(beam);
    label(g,caption,[x,1.88,z],{scale:.88});
  }
  // 识别、称重和扫码设备随场景变化，动作仍使用这次运行的分类结果。
  if(['color','size','barcode'].includes(sceneId)){
    for(const z of [-.77,.77])box(g,[.07,.98,.07],steel,[-.8,1.65,z]);box(g,[.35,.09,1.58],steel,[-.8,2.12,0]);box(g,[.25,.18,.28],dark,[-.8,1.97,0]);cylinder(g,.06,.08,rubber,[-.8,1.84,0]);
    label(g,sceneId==='barcode'?'扫码识别':sceneId==='size'?'尺寸检测':'颜色检测',[-.8,2.4,0],{scale:1.1});
  }
  if(sceneId==='weight'){box(g,[.8,.035,.94],steel,[-.55,1.28,0]);label(g,'称重工位',[-.55,2.04,0],{scale:1.1});}
  if(sceneId==='rework')label(g,'合格 / 待重检',[.1,2,0],{scale:1.2});
  box(g,[.7,.9,.38],dark,[-1,.47,-1.12]);box(g,[.44,.28,.025],material(0x238c8a,.3,.2),[-1,.63,-1.325]);cylinder(g,.075,.03,material(0xe9564b),[-.83,.35,-1.32],[Math.PI/2,0,0]);
  for(let i=0;i<5;i++)box(g,[.28,.19,.24],material([0xffb34b,0x32b5a6,0x83a5c0][i%3]),[-3.6-(i%2)*.32,.13+Math.floor(i/2)*.21,.1]);
  label(g,'LD-FLEX · VIRTUAL SORTING LINE',[-.5,2.8,0],{scale:3,color:'#83d9ca'});
  const parcel=new T.Group();g.add(parcel);const carton=box(parcel,[.3,.24,.27],material(0xdca25a,.05,.84),[0,.12,0]);box(parcel,[.044,.006,.28],material(0xc9a978),[0,.244,0]);box(parcel,[.11,.008,.1],material(0xf3eee0),[.075,.248,0]);
  const stack=new T.Group();g.add(stack);let stackKey='';
  return {group:g,extent:7,target:new T.Vector3(0,1,0),home:[6,4.2,6.2],tracked:new T.Vector3(),
    update(f,time){
      gate.position.y=1.35+(f?.gate?.45:0);selector.rotation.y=f?.route===1?-.38:.38;
      const beltTravel=(f?.progress||0)*5;beltLines.position.x=beltTravel% .16;
      for(const roller of rollers)roller.rotation.z=-beltTravel/.09;
      beams.forEach((beam,i)=>{beam.material.color.setHex(f&&(f.inputs&(1<<i))?0xff6c57:0x3bcaba);beam.material.opacity=f&&(f.inputs&(1<<i))?1:.15;});
      const visible=f?.order_id!=null&&f.progress!=null;
      parcel.visible=visible;
      if(visible){let p=sorterPosition(f.progress,f.physical_route??f.route);if(four&&f.progress>.68){const q=(f.progress-.68)/.32;p[2]=q*branches[f.physical_destination??f.destination??((f.physical_route??f.route)*2)];}parcel.position.set(...p);parcel.rotation.y=f.progress>.68?-Math.atan2(p[2],1.5):0;carton.material.color.setHex(f.color==='blue'?0x4f9dde:f.color==='red'?0xe36652:0xdca25a);const size=f.size==='large'?1.25:f.size==='small'?.7:1;parcel.scale.setScalar(size);this.tracked.copy(parcel.position);}else this.tracked.set(1,1.35,0);
      const counts=four?(f?.bin_counts||[0,0,0,0]):[f?.outlet_a||0,f?.outlet_b||0];const key=counts.join(':');
      if(key!==stackKey){while(stack.children.length){const old=stack.children[0];stack.remove(old);old.geometry.dispose();old.material.dispose();}counts.forEach((count,i)=>{for(let j=0;j<Math.min(count,12);j++)box(stack,[.23,.16,.2],material(i%2?0x5f9cc4:0xd9a863),[2.95+(j%3-1)*.24,.19+Math.floor(j/6)*.16,branches[i]+(Math.floor(j/3)%2-.5)*.22]);});stackKey=key;}
      carton.material.emissive.setHex(f?.state==='FAULT'?0x8b1d17:0x000000);
    }
  };
}

function drone(g,profile){
  const unit=new T.Group();g.add(unit);unit.scale.setScalar(profile.size);
  const shell=material(profile.color,.45,.36),carbon=material(0x1d2831,.55,.48),metal=material(0x9daebb,.85,.25),rubber=material(0x17212a,.1,.8),rotors=[];
  const body=mesh(unit,new T.SphereGeometry(1,24,16),shell,[0,.05,0]);body.scale.set(.38,.16,.24);box(unit,[.48,.06,.34],carbon,[0,-.07,0]);box(unit,[.3,.06,.2],rubber,[-.04,.19,0]);
  for(let i=0;i<profile.rotors;i++){
    const angle=2*Math.PI*i/profile.rotors+Math.PI/4,x=Math.cos(angle)*.73,z=Math.sin(angle)*.73;
    bar(unit,[x*.27,.03,z*.27],[x,.06,z],.052,profile.fold?shell:carbon);cylinder(unit,.085,.12,carbon,[x,.08,z]);cylinder(unit,.064,.07,metal,[x,.17,z]);
    const prop=new T.Group();unit.add(prop);prop.position.set(x,.23,z);
    for(let blade=0;blade<2;blade++){const b=mesh(prop,new T.SphereGeometry(1,12,6),rubber,[blade===0?.15:-.15,0,0]);b.scale.set(.2,.014,.041);}cylinder(prop,.04,.04,metal,[0,.01,0]);rotors.push(prop);
    const led=material(i<profile.rotors/2?0xff584e:0x25d99f,.1);led.emissive=new T.Color(i<profile.rotors/2?0xb32418:0x087857);box(unit,[.09,.025,.045],led,[x,.03,z]);
    if(profile.guards){ring(unit,.34,carbon,[x,.17,z]);for(let k=0;k<3;k++){const a=k*Math.PI*2/3;bar(unit,[x,.17,z],[x+Math.cos(a)*.34,.17,z+Math.sin(a)*.34],.012,carbon);}}
    if(profile.coaxial){const lower=prop.clone();lower.position.y=-.14;unit.add(lower);rotors.push(lower);cylinder(unit,.08,.08,carbon,[x,-.1,z]);}
  }
  for(const z of [-.27,.27]){bar(unit,[-.18,-.1,z*.6],[-.25,-.47,z],.023,carbon);bar(unit,[.18,-.1,z*.6],[.25,-.47,z],.023,carbon);bar(unit,[-.4,-.47,z],[.4,-.47,z],.025,rubber);}
  if(profile.camera){const mount=new T.Group();unit.add(mount);mount.position.set(.27,-.18,0);box(mount,[.05,.13,.23],metal,[0,0,0]);const cam=mesh(mount,new T.SphereGeometry(.12,16,12),carbon,[.08,-.1,0]);cylinder(mount,.057,.075,metal,[.18,-.1,0],[0,0,-Math.PI/2]);cylinder(mount,.042,.006,material(0x23677d,.65,.08),[.222,-.1,0],[0,0,-Math.PI/2]);}
  cylinder(unit,.06,.035,shell,[-.12,.235,0]);label(unit,profile.rotors>=6?'LD INDUSTRIAL':'LD FLIGHT',[0,.5,0],{scale:.55});
  return {unit,rotors};
}

function tower(group,x,z,steel,height){
  const h=height;
  for(const sign of [-1,1])for(const side of [-1,1])bar(group,[x+sign*1.1,0,z+side*.6],[x+sign*.24,h,z+side*.2],.08,steel);
  for(let y=1;y<h;y+=1.5){const w=1.1*(1-y/h)+.24;for(const side of [-1,1]){bar(group,[x-w,y,z+side*.5],[x+w,y+1.4,z+side*.4],.032,steel);bar(group,[x+w,y,z+side*.5],[x-w,y+1.4,z+side*.4],.032,steel);}}
  bar(group,[x-2.4,h-1,z],[x+2.4,h-1,z],.075,steel);bar(group,[x-1.8,h+.4,z],[x+1.8,h+.4,z],.065,steel);label(group,'巡检电力场景',[x,h+1.6,z],{scale:2});
}

export function makeFlight(scene,data,profileId='inspection'){
  const g=new T.Group();scene.add(g);const cfg=data.config||{waypoints:[],obstacles:[],geofence:100};
  const positions=data.frames.map(f=>f.position);const all=positions.concat(cfg.waypoints||[],[[0,0,0]]);let limit=16;
  for(const p of all)limit=Math.max(limit,Math.abs(p[0])+4,Math.abs(p[1])+4,p[2]+4);
  floor(scene,Math.max(70,limit*3));
  const profile=aircraft.find(p=>p.id===profileId)||aircraft[0];const d=drone(g,profile);
  const steel=material(0x91a6b0,.8,.35),grass=material(0x24493e,.05,.9),green=material(0x35765a,.05,.8);
  const h=Math.max(7,Math.min(18,limit*.55));
  // 电力设施作场景背景，真正参与避障的区域只取配置中的 obstacles。
  const x1=-limit*.65,z1=-limit*.72,x2=limit*.92,z2=-limit*.72;tower(g,x1,z1,steel,h);tower(g,x2,z2,steel,h);
  for(let wire=0;wire<3;wire++){const pts=[];for(let j=0;j<=40;j++){const q=j/40;pts.push([x1+(x2-x1)*q,h-.8-Math.sin(q*Math.PI)*1.5,z1+(wire-1)*.8]);}line(g,pts,0x78949d);}
  const pad=mesh(g,new T.CylinderGeometry(1.5,1.5,.08,48),material(0x253d49,.3,.8),[0,-.01,0]);ring(g,1.2,material(0xf1c26b),[0,.04,0]);box(g,[.12,.014,1],material(0xf1c26b),[-.25,.045,0]);box(g,[.12,.014,1],material(0xf1c26b),[.25,.045,0]);box(g,[.5,.015,.1],material(0xf1c26b),[0,.045,0]);
  for(let i=0;i<16;i++){const x=Math.cos(i*2.4)*limit*1.2,z=Math.sin(i*2.4)*limit*1.2;const tree=new T.Group();g.add(tree);cylinder(tree,.14,1.8,material(0x634b38),[x,.9,z]);mesh(tree,new T.ConeGeometry(1.1,3.3,9),i%2?grass:green,[x,2.8,z]);}
  const route=(cfg.waypoints||[]).map(p=>enu(p));if(route.length){line(g,[[0,.1,0],...route],0xeab960,true);route.forEach((p,i)=>{ring(g,.45,material(0xebb954),p);bar(g,[p[0],.05,p[2]],p,.012,new T.MeshBasicMaterial({color:0x5b5144,transparent:true,opacity:.5}));label(g,'WP '+(i+1),[p[0],p[1]+.7,p[2]],{scale:1.5,color:'#ffd68a'});});}
  let points=positions.map(p=>new T.Vector3(...enu(p)));const path=line(g,points.map(p=>p.toArray()),0x43dcca);path.geometry.setDrawRange(0,1);
  const obstacleGroup=new T.Group();g.add(obstacleGroup);
  for(const obstacle of cfg.obstacles||[]){mesh(obstacleGroup,new T.SphereGeometry(obstacle.radius,24,16),new T.MeshStandardMaterial({color:0xf37958,transparent:true,opacity:.14,wireframe:false}),enu(obstacle.center));mesh(obstacleGroup,new T.SphereGeometry(obstacle.radius,12,8),new T.MeshBasicMaterial({color:0xb86744,wireframe:true,transparent:true,opacity:.3}),enu(obstacle.center));label(obstacleGroup,'障碍区域',[obstacle.center[0],obstacle.center[2]+obstacle.radius+.5,-obstacle.center[1]],{scale:2});}
  const fence=new T.Group();g.add(fence);const fenceRadius=cfg.geofence||100;const fenceMat=new T.LineBasicMaterial({color:0x427186,transparent:true,opacity:.25});for(const plane of [0,1,2]){const pts=[];for(let i=0;i<=128;i++){const a=i/128*Math.PI*2;pts.push(plane===0?[Math.cos(a)*fenceRadius,0,Math.sin(a)*fenceRadius]:plane===1?[Math.cos(a)*fenceRadius,Math.sin(a)*fenceRadius,0]:[0,Math.sin(a)*fenceRadius,Math.cos(a)*fenceRadius]);}fence.add(new T.Line(new T.BufferGeometry().setFromPoints(pts.map(p=>new T.Vector3(...p))),fenceMat));}
  const wind=new T.ArrowHelper(new T.Vector3(1,0,0),new T.Vector3(0,3,0),3,0x6fbfff,.5,.25);g.add(wind);
  const particles=new T.Group();g.add(particles);for(let i=0;i<36;i++){const point=mesh(particles,new T.SphereGeometry(.025,4,4),new T.MeshBasicMaterial({color:0x549bac,transparent:true,opacity:.35}),[0,0,0]);point.userData.base=[((i*31)%53)/53*limit*2-limit,2+(i%7)*.7,((i*13)%47)/47*limit*2-limit];}
  return {group:g,extent:limit*1.8,target:new T.Vector3(limit*.2,3,-limit*.2),home:[limit*1.05,limit*.9,limit*1.25],tracked:new T.Vector3(),path,wind,particles,fence,obstacles:obstacleGroup,
    update(f,time,frames){if(!f)return;const p=enu(f.position);d.unit.position.set(...p);this.tracked.copy(d.unit.position);const i=f.index||0,a=frames[Math.max(0,i-1)]?.position||f.position,b=frames[Math.min(frames.length-1,i+1)]?.position||f.position;const dx=b[0]-a[0],dy=b[1]-a[1];if(f.heading_rad!=null)d.unit.rotation.y=f.heading_rad;else if(Math.hypot(dx,dy)>.0001)d.unit.rotation.y=Math.atan2(dy,dx);d.unit.rotation.z=clamp((b[2]-a[2])*-.5,-.12,.12);
      const flying=f.state!=='DONE'&&f.state!=='ABORTED'&&f.position[2]>.05;d.rotors.forEach((p,j)=>p.rotation.y=(j%2?-1:1)*time*(flying?130:0));
      if(points.length!==frames.length){points=frames.map(row=>new T.Vector3(...enu(row.position)));this.path.geometry.dispose();this.path.geometry=new T.BufferGeometry().setFromPoints(points);}
      this.path.geometry.setDrawRange(0,Math.min(i+2,points.length));const v=new T.Vector3(...enu(f.wind));this.wind.position.copy(d.unit.position).add(new T.Vector3(0,2,0));this.wind.visible=v.length()>.05;if(this.wind.visible){this.wind.setDirection(v.normalize());this.wind.setLength(clamp(f.wind_speed*.7,.5,6),.45,.22);}
      particles.children.forEach((p,j)=>{const b=p.userData.base;p.position.set(b[0]+Math.sin(time*.3+j)*.5+(f.wind[0]*time*.2)%(limit*2),b[1],b[2]-(f.wind[1]*time*.2)%(limit*2));});
    }
  };
}

export function disposeScene(root){root.traverse(obj=>{obj.geometry?.dispose();if(obj.material){for(const m of Array.isArray(obj.material)?obj.material:[obj.material]){m.map?.dispose();m.dispose();}}});root.clear();}
