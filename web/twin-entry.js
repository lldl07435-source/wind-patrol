import {TwinPlayer} from './twin-viewer.js';
const params=new URLSearchParams(location.search),host=document.getElementById('standalone-twin');
let player,poll;
try{
  const response=await fetch('/api/studio/bootstrap'),boot=await response.json();
  if(!response.ok)throw Error(boot.error||'请先登录');
  player=new TwinPlayer(host,{domain:boot.domain});
  if(params.get('id'))await player.load(params.get('id'),{autoplay:true});
  else if(params.get('live')==='1'){await player.live();poll=setInterval(()=>player.live(),160);}
  else document.getElementById('entry-message').textContent='在工作区运行后选择运行记录，即可打开对应三维动画。';
}catch(e){document.getElementById('entry-message').textContent=e.message;}
window.addEventListener('pagehide',()=>{clearInterval(poll);player?.dispose();});
