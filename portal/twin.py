"""将账户内的运行记录转成带虚拟时间的三维回放数据。"""
import hashlib
import json
import math
from pathlib import Path
from django.http import HttpResponse

SCHEMA = 'ld-twin/1'


def checked_cursor(request):
    try:
        value = float(request.GET.get('after', '-1'))
    except (TypeError, ValueError):
        raise ValueError('时间游标必须是有限数值')
    if not math.isfinite(value) or value < -1:
        raise ValueError('时间游标必须是大于等于-1的有限数值')
    return value


def ld_geometry():
    return {'type': 'belt_sorter', 'units': 'schematic',
            'description': '传送带、单件闸门、换向机构和A/B光电；外观为产线模型，位移按仿真通行时序映射。'}


def legacy_frames(events):
    # 旧日志只有状态切换，保持离散动作，不补造连续物料位置。
    frames = []
    for event in events:
        r = event['data']
        if event['kind'] == 'state':
            frames.append(dict(time_s=r['virtual_ms']/1000, state=r['state'],
                               gate=r.get('gate', False), route=r.get('route',0),
                               inputs=r.get('inputs',0), fault=r.get('fault','NONE'),
                               order_id=None, progress=None,
                               completed=r.get('completed',0), releases=r.get('releases',0)))
    return frames


def sorter_payload(ctx, key, after=-1):
    from ldcell.storage import run_folder, verify
    with ctx.engine.lock:
        sim, log = ctx.engine.sim, ctx.engine.log
        if sim and log and log.id == key:
            frames=[dict(f) for f in sim.motion if f['time_s'] > after]
            events=[{'time_s':r['virtual_ms']/1000,'code':r['state'],
                     'detail':str(r.get('fault',''))} for r in sim.trace]
            events += [{'time_s':r['finished'],'code':r['outcome'],
                        'detail':'物料 '+str(r['order_id'])} for r in sim.rows]
            return dict(schema=SCHEMA,domain='ld',source='simulation',run_id=key,
                        name='分拣 '+sim.policy+' / '+sim.scenario,geometry=ld_geometry(),
                        config=log.meta['config'],summary=sim.summary(),frames=frames,
                        duration_s=sim.now/1000,live=sim.status=='running',
                        fidelity='model_motion',events=events,frame_count=len(sim.motion),
                        awaiting_recovery=sim.recovery_started is not None)
    try:
        folder=run_folder(ctx.root,key)
    except ValueError as exc:
        if str(exc)=='run not found':raise FileNotFoundError() from exc
        raise
    if not folder.exists(): raise FileNotFoundError()
    verification=verify(folder)
    if not verification['ok']: raise ValueError('运行未封存或摘要校验未通过，暂不回放')
    meta=json.loads((folder/'meta.json').read_text(encoding='utf-8'))
    if meta['mode'] != 'simulation':
        raise ValueError('实物记录没有连续位置测量；请使用信号回放核对真实反馈')
    rows=[json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    frames=[f for e in rows if e['kind']=='motion_batch' for f in e['data']['frames']]
    fidelity='model_motion' if frames else 'state_only'
    if not frames: frames=legacy_frames(rows)
    summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    events=[{'time_s':e['data']['virtual_ms']/1000,'code':e['data']['state'],
             'detail':str(e['data'].get('fault',''))} for e in rows if e['kind']=='state']
    events += [{'time_s':e['data']['finished'],'code':e['data']['outcome'],
                'detail':'物料 '+str(e['data']['order_id'])} for e in rows if e['kind']=='job_result']
    return dict(schema=SCHEMA,domain='ld',source='simulation',run_id=key,
                name='分拣 '+meta['config'].get('policy','')+' / '+meta['config'].get('scenario',''),
                geometry=ld_geometry(),config=meta['config'],summary=summary,
                frames=[f for f in frames if f['time_s']>after], frame_count=len(frames),
                duration_s=summary.get('makespan_s',frames[-1]['time_s'] if frames else 0),
                live=False,fidelity=fidelity,events=events,verification=verification,
                awaiting_recovery=False)


def wind_payload(ctx, key, after=-1):
    manual=getattr(ctx,'manual',None)
    if manual and manual.id==key and not manual.saved:
        with manual.lock:
            record={'id':key,'name':manual.name,'result':manual.result()}
            live=not manual.done.is_set()
    else:
        record=ctx.repo.get(key)
        live=False
    result=record['result']
    # 完整采样直接供回放；时间轴寻址不沿用旧二维图的抽样。
    frames=[dict(time_s=r['time'],position=[r['x'],r['y'],r['z']],
                 state=r['mode'],speed=r['speed'],battery=r['battery'],
                 wind=[r['wind_x'],r['wind_y'],r['wind_z']],
                 wind_speed=r['wind_speed'],wind_regime=r['wind_regime'],
                 sensor_valid=r['sensor_valid'],target_index=r['target_index'],
                 target_distance=r['target_distance'],command_emitted=r['command_emitted'],
                 heading_rad=r.get('heading_rad'),manual_axes=r.get('manual_axes'))
            for r in result['samples']]
    return dict(schema=SCHEMA,domain='wind',source='simulation',run_id=key,
                name=record['name'],geometry={'type':'quadrotor','units':'m','frame':'ENU',
                'description':'位置和风速来自原始仿真；朝向按位置变化估算，机体为结构示意。'},
                config=result['config'],summary=result['summary'],
                duration_s=result['summary']['elapsed'],live=live,fidelity='full_trajectory',
                frame_count=len(frames),frames=[f for f in frames if f['time_s']>after],
                events=[{'time_s':r.get('time',0),'code':r.get('kind',r.get('code','EVENT')),
                         'detail':r.get('detail',r.get('message',''))} for r in result['events']])


def handle(request,ctx,domain,route,raw):
    if request.method != 'GET': raise ValueError('三维回放接口只接受读取请求')
    after=checked_cursor(request)
    parts=route.split('/')
    if parts==['twin','live'] and domain=='ld':
        with ctx.engine.lock:
            key=ctx.engine.log.id if ctx.engine.log else None
        if not key: return {'run_id':None,'frames':[],'schema':SCHEMA,'domain':domain,'live':False}
        return sorter_payload(ctx,key,after)
    if parts==['twin','live'] and domain=='wind':
        manual=getattr(ctx,'manual',None)
        if not manual:return {'run_id':None,'frames':[],'schema':SCHEMA,'domain':domain,'live':False}
        return wind_payload(ctx,manual.id,after)
    if len(parts) not in (3,4) or parts[:2]!=['twin','runs']:
        raise FileNotFoundError()
    key=parts[2]
    if len(parts)==4 and parts[3]!='download': raise FileNotFoundError()
    payload=sorter_payload(ctx,key,after) if domain=='ld' else wind_payload(ctx,key,after)
    if len(parts)==4:
        if payload['live']: raise ValueError('请先结束运行，再下载完整回放')
        # 下载始终完整；读取用的游标不应让下载缺帧。
        if after!=-1: payload=sorter_payload(ctx,key) if domain=='ld' else wind_payload(ctx,key)
        serialized=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
        wrapped={'replay':payload,'sha256':hashlib.sha256(serialized.encode('utf-8')).hexdigest(),
                 'hash_basis':'UTF-8 / sorted keys / compact separators / replay object'}
        response=HttpResponse(json.dumps(wrapped,ensure_ascii=False,indent=2),content_type='application/json; charset=utf-8')
        response['Content-Disposition']='attachment; filename="twin-'+key+'.json"'
        return response
    return payload
