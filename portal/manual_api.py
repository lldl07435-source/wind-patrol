import threading
import json
import math
from . import data

_start_lock=threading.RLock()
PROFILES=('inspection','folding','mini','fpv','cine','hex','octo','coaxial')

def handle(request,ctx,domain,route,raw):
    if route=='manual/preferences':
        path=ctx.root/'controller-preferences.json'
        with _start_lock:
            if request.method=='GET':
                return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'axes':[0,1,3,2],'reverse':[False,True,True,False],'deadzone':.12,'model':'inspection'}
            axes,reverse=raw.get('axes'),raw.get('reverse');deadzone=raw.get('deadzone',.12);model=raw.get('model','inspection')
            if not isinstance(axes,list) or len(axes)!=4 or any(type(i) is not int or not 0<=i<=15 for i in axes):raise ValueError('通道需指定四个0至15的轴号')
            if not isinstance(reverse,list) or len(reverse)!=4 or any(type(i) is not bool for i in reverse):raise ValueError('反向设置需要四个布尔值')
            if type(deadzone) not in (int,float) or not math.isfinite(deadzone) or not .02<=deadzone<=.5 or model not in PROFILES:raise ValueError('死区或机型无效')
            data.check_quota(ctx,0)
            value=dict(axes=axes,reverse=reverse,deadzone=deadzone,model=model)
            temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value),encoding='utf-8');temporary.replace(path)
            return value
    if request.method!='POST':raise ValueError('手控操作需要POST请求')
    if route=='manual/start':
        if domain=='ld':
            from .studio_api import config
            import workspace_adapter as adapter
            cfg=config(raw.get('config'),domain)
            return adapter.handle(request,'start',{**cfg,'manual':True,'speed':1})
        from quadrotor_patrol_simulation import Config
        from .manual_simulation import ManualFlight
        cfg=Config.from_dict(raw.get('config'));name=raw.get('name','手控飞行')
        profile=raw.get('profile','inspection')
        if profile not in PROFILES:raise ValueError('机型模型无效')
        if not isinstance(name,str) or not 1<=len(name.strip())<=80:raise ValueError('任务名称应为1至80个字符')
        with _start_lock:
            if not ctx.lock.acquire(blocking=False):raise RuntimeError('当前账户已有运行进行中')
            acquired=data.compute_slots.acquire(blocking=False)
            if not acquired:ctx.lock.release();raise RuntimeError('计算队列繁忙')
            def release():
                ctx.lock.release();data.compute_slots.release()
            try:
                data.check_quota(ctx)
                ctx.manual=ManualFlight(ctx,cfg,name.strip(),release,profile)
            except Exception:release();raise
        return {'ok':True,'run_id':ctx.manual.id}
    if route=='manual/control':
        if domain=='ld':
            if raw.get('feed') is not True:raise ValueError('请明确确认单件上料')
            ctx.engine.manual_feed(raw.get('route'));return {'ok':True}
        if not getattr(ctx,'manual',None):raise ValueError('尚无手控仿真')
        ctx.manual.input(raw.get('axes'));return {'ok':True}
    if route=='manual/stop':
        if domain=='ld':ctx.engine.stop()
        elif getattr(ctx,'manual',None):ctx.manual.stop()
        return {'ok':True}
    raise FileNotFoundError()
