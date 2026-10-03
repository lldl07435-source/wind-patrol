"""手控飞行的服务器时钟；键盘和HID输入只作用于仿真。"""
import math
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

class ManualFlight:
    def __init__(self,ctx,cfg,name,release,profile='inspection'):
        from quadrotor_patrol_simulation import WindModel,WindStateEstimator
        self.ctx=ctx;self.cfg=cfg;self.name=name;self.profile=profile;self.release=release
        self.id=uuid4().hex[:16];self.created=datetime.now(timezone.utc).isoformat(timespec='seconds')
        self.lock=threading.RLock();self.done=threading.Event();self.rows=[];self.events=[]
        self.position=[0.,0.,0.];self.velocity=[0.,0.,0.];self.battery=cfg.initial_battery
        self.axes=[0.,0.,0.,0.];self.heading=0.;self.last_input=time.monotonic();self.started=time.monotonic();self.elapsed=0.
        self.status='MANUAL';self.wind=WindModel(cfg);self.estimator=WindStateEstimator(cfg);self.error='';self.saved=False;self.sensor_missing=0.;self.min_clearance=math.inf
        self.event('START','手控仿真启动');self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def event(self,kind,detail): self.events.append({'time':round(self.elapsed,6),'kind':kind,'detail':detail})

    def input(self,axes):
        if not isinstance(axes,list) or len(axes)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1 for v in axes):
            raise ValueError('手控输入需要四个-1至1之间的有限数值')
        with self.lock:
            if self.done.is_set(): raise RuntimeError('手控会话已经结束')
            self.axes=list(axes);self.last_input=time.monotonic()

    def advance(self,dt=.05):
        from quadrotor_patrol_simulation import limit,norm,segment_clearance
        cfg=self.cfg;actual_wind=self.wind.sample(self.elapsed,dt);estimated,regime,gust=self.estimator.update(actual_wind,dt)
        safe_axes=[0,0,0,0] if time.monotonic()-self.last_input>.5 else self.axes
        desired=limit([v*cfg.max_speed for v in safe_axes[:3]],cfg.max_speed)
        command=limit([(target-v)*2-.25*w for target,v,w in zip(desired,self.velocity,actual_wind)],cfg.max_accel)
        old=list(self.position)
        acceleration=[a+.25*(w-v) for a,w,v in zip(command,actual_wind,self.velocity)]
        self.velocity=limit([v+a*dt for v,a in zip(self.velocity,acceleration)],cfg.max_speed)
        self.position=[p+v*dt for p,v in zip(self.position,self.velocity)]
        if self.position[2]<0:self.position[2]=0;self.velocity[2]=max(0,self.velocity[2])
        self.heading+=safe_axes[3]*1.2*dt;self.elapsed=round(self.elapsed+dt,6)
        self.battery=max(0,self.battery-cfg.battery_rate*(1+.1*norm(command))*dt)
        valid=not(cfg.dropout_start<=self.elapsed<cfg.dropout_start+cfg.dropout_duration)
        self.sensor_missing=0 if valid else self.sensor_missing+dt
        for obstacle in cfg.obstacles:self.min_clearance=min(self.min_clearance,segment_clearance(old,self.position,obstacle))
        self.rows.append(dict(time=self.elapsed,mode=self.status,x=self.position[0],y=self.position[1],z=self.position[2],
            speed=norm(self.velocity),battery=self.battery,target_index=0,target_distance=norm(self.position),
            wind_x=actual_wind[0],wind_y=actual_wind[1],wind_z=actual_wind[2],wind_speed=norm(actual_wind),
            wind_estimate_speed=norm(estimated),wind_regime=regime,gust_factor=gust,sensor_valid=valid,
            command_emitted=any(safe_axes),virtual_latency=0,heading_rad=self.heading,manual_axes=list(safe_axes)))
        reason=''
        if time.monotonic()-self.last_input>2:reason='手控输入超时，结束会话'
        elif norm(self.position)>cfg.geofence:reason='达到围栏边界'
        elif self.battery<=cfg.critical_threshold:reason='达到电量安全阈值'
        elif norm(actual_wind)>=cfg.max_operating_wind:reason='达到风速安全阈值'
        elif self.sensor_missing>cfg.sensor_timeout:reason='观测中断超过允许时长'
        elif self.min_clearance<=0:reason='检测到障碍物碰撞'
        if reason:self.status='ABORTED';self.event('ABORTED',reason);self.done.set()
        elif self.elapsed>=min(cfg.duration,300):self.status='TIMEOUT';self.event('TIMEOUT','达到手控会话时长上限');self.done.set()
        if self.rows:self.rows[-1]['mode']=self.status

    def summary(self):
        from quadrotor_patrol_simulation import SOFTWARE_NAME
        return dict(software=SOFTWARE_NAME,version='1.4.0',status=self.status,control_mode='manual',visual_profile=self.profile,
            samples=len(self.rows),elapsed=self.elapsed,visited=0,total_waypoints=len(self.cfg.waypoints),mission_complete=False,
            battery_remaining=self.battery,max_speed=max((r['speed'] for r in self.rows),default=0),
            max_wind_speed=max((r['wind_speed'] for r in self.rows),default=0),mean_wind_speed=sum(r['wind_speed'] for r in self.rows)/len(self.rows) if self.rows else 0,
            wind_regime_counts={},command_updates=sum(bool(r['command_emitted']) for r in self.rows),min_clearance=None if math.isinf(self.min_clearance) else self.min_clearance,
            virtual_node_jobs=0,virtual_deadline_misses=0,virtual_max_latency=0)

    def result(self): return {'config':asdict(self.cfg),'summary':self.summary(),'events':list(self.events),'samples':[dict(r) for r in self.rows]}

    def stop(self):
        with self.lock:
            if not self.done.is_set():self.status='STOPPED';self.event('STOPPED','操作者结束手控仿真');self.done.set()
        self.thread.join(timeout=5)

    def run(self):
        try:
            # 服务器按固定50 ms推进，浏览器不能提交任意步长加速物理运动。
            while not self.done.wait(.05):
                with self.lock:self.advance()
        except Exception as exc:
            self.error=str(exc);self.status='ABORTED';self.event('ABORTED','手控计算异常');self.done.set()
        finally:
            try:
                with self.lock:
                    if self.rows:self.rows[-1]['mode']=self.status
                    record={'id':self.id,'name':self.name,'created':self.created,'result':self.result()}
                    with self.ctx.repo.connect() as db:self.ctx.repo.insert(db,record)
                    self.saved=True
            finally:self.release()
