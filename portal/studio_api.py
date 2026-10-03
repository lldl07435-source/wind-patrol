"""统一工作区：计划串起执行、数据和复核，而不是复制业务实体。"""
import hashlib
import io
import json
import math
import platform
import zipfile
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
from django.conf import settings
from django.http import HttpResponse
from .studio_store import Studio, text, device_payload, calibration
from .experiment_lab import Lab, csv_bytes

STATES = {'draft': '草稿', 'ready': '已核对', 'running': '运行中', 'review': '待复核', 'completed': '已归档'}
LD_SCENARIOS = [('normal', '正常分拣'), ('jam', '卡料'), ('wrong_exit', '错出口'),
                ('missing_entry', '入口漏检'), ('double_feed', '重复进料'), ('stuck_exit', '传感器粘连'),
                ('link_loss', '通信中断'), ('estop', '急停'), ('reboot', '控制器重启'), ('duplicate', '重复命令')]


def config(raw, domain):
    if not isinstance(raw, dict):
        raise ValueError('实验参数应为对象')
    if domain == 'wind':
        from quadrotor_patrol_simulation import Config
        cfg = Config.from_dict(raw)
        if math.ceil(cfg.duration / cfg.dt) > 20000:
            raise ValueError('单任务最多20000步')
        return asdict(cfg)
    from ldcell.simulation import SCENARIOS
    from ldcell.scheduling import POLICIES
    if set(raw) - {'seed', 'count', 'policy', 'scenario', 'speed', 'task_kind'}:
        raise ValueError('分拣参数包含未支持的字段')
    result = dict(seed=42, count=24, policy='BEAM', scenario='normal', speed=5)
    result.update(raw)
    if 'task_kind' in result and result['task_kind'] not in ('belt','color','size','weight','barcode','rework'):
        raise ValueError('分拣任务类型不正确')
    if type(result['seed']) is not int or not 0 <= result['seed'] <= 2**32 - 1:
        raise ValueError('随机种子应为0至4294967295的整数')
    if type(result['count']) is not int or not 4 <= result['count'] <= 80:
        raise ValueError('物料数量应为4至80件')
    if result['policy'] not in POLICIES or result['scenario'] not in SCENARIOS or type(result['speed']) is not int or result['speed'] not in (1, 2, 5, 10):
        raise ValueError('策略、场景或演示速度不正确')
    return result


def presets(domain):
    if domain == 'wind':
        from scenarios import scenario_list
        return scenario_list()
    return [dict(id=k, name=n, description='第3件注入故障' if k != 'normal' else '双出口分拣，固定10 ms控制步长',
                 config=config({'scenario': k}, domain)) for k, n in LD_SCENARIOS]


def runs(ctx, domain):
    if domain == 'wind':
        return [dict(id=r['id'], name=r['name'], created=r['created'], status=r['summary']['status'],
                     summary=r['summary'], kind='simulation', url='/api/tasks/'+r['id']+'/download') for r in ctx.repo.list()]
    from ldcell.storage import history
    return [dict(id=r['id'], name=r['summary'].get('scenario', r['mode']), created=r['started_at'],
                 status=r['status'], summary=r['summary'], kind=r['mode'], url='/api/export?id='+r['id'])
            for r in history(ctx.root, limit=max(ctx.record_count(), 1))]


def resolve(ctx, domain, kind, ident):
    if kind in ('dataset', 'report'):
        return Lab(ctx.root, domain).get(ident, 'datasets' if kind == 'dataset' else 'reports')
    if kind == 'run':
        if domain == 'wind':
            return ctx.repo.get(ident)
        from ldcell.storage import run_folder, verify
        folder = run_folder(ctx.root, ident)
        if not verify(folder)['ok']:
            raise RuntimeError('运行尚未封存或校验未通过')
        return json.loads((folder/'meta.json').read_text(encoding='utf-8'))
    raise ValueError('不支持的关联类型')


def reconcile(store, ctx, domain):
    # 运行结束和人工归档是两个步骤；重启后的未封存记录也会进入复核。
    saved = {r['id']: r for r in runs(ctx, domain)}
    for plan in store.list('plans'):
        if plan['state'] != 'running':
            continue
        if not plan.get('run_id'):
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(plan['updated'])).total_seconds()
            if age > 300:
                try:
                    store.update('plans', plan['id'], plan['version'], 'run_unresolved',
                                 lambda item: item.update(state='review', run_status='unresolved'))
                except RuntimeError:
                    pass
            continue
        record = saved.get(plan['run_id'])
        if record and record['status'] != 'running':
            def change(item):
                item.update(state='review', run_status=record['status'])
                return {'run_id': item['run_id'], 'run_status': record['status']}
            try:
                store.update('plans', plan['id'], plan['version'], 'run_finished', change)
            except RuntimeError:
                pass  # 另一请求已经推进了状态，下一次读取即可。


def search_index(store, ctx, domain):
    items = []
    for col, kind, label in [('plans', 'plan', '实验'), ('devices', 'device', '设备'), ('recipes', 'recipe', '模板')]:
        for r in store.list(col):
            if r['archived']:
                continue
            items.append(dict(id=r['id'], kind=kind, label=label, name=r['name'],
                              description=r.get('objective', r.get('model', '')), time=r['updated']))
    for r in runs(ctx, domain):
        items.append(dict(id=r['id'], kind='run', label='运行', name=r['name'], description=r['status'], time=r['created']))
    lab = Lab(ctx.root, domain)
    for r in lab.list():
        items.append(dict(id=r['id'], kind='dataset', label='数据', name=r['name'], description=r['kind_label'], time=r['created']))
    for r in lab.list('reports'):
        items.append(dict(id=r['id'], kind='report', label='对照', name=r['base']['name']+' / '+r['observed']['name'],
                          description=r['metrics']['metric'], time=r['created']))
    return items


def notice_list(store, usage):
    pref = store.preferences()
    items = []
    for r in store.list('plans'):
        if r['state'] == 'review' and not r['archived']:
            items.append(dict(id='review:'+r['id']+':'+str(r['version']), name=r['name']+' 等待复核',
                              detail='查看运行结果，补充结论后归档。', kind='plan', target=r['id'], level='info'))
    for r in store.list('devices'):
        if r['archived'] or not r['calibrations']:
            continue
        c = r['calibrations'][-1]
        if not c['passed'] or (c['expires'] and c['expires'] < date.today().isoformat()):
            items.append(dict(id='calibration:'+c['id'], name=r['name']+' 校准需检查', detail=c['label']+' 偏差或有效期需要复核。',
                              kind='device', target=r['id'], level='warning'))
    if usage >= settings.MAX_WORKSPACE_BYTES * .8:
        items.append(dict(id='quota', name='工作区容量已超过80%', detail='下载备份并检查数据容量。', kind='settings', target='', level='warning'))
    return [r for r in items if r['id'] not in pref['dismissed']]


def dossier(store, plan, ctx, domain):
    if domain == 'ld':
        from ldcell.storage import export_run, run_folder
    buf = io.BytesIO()
    hashes = {}
    def add(archive, name, raw):
        if not isinstance(raw, bytes):
            raw = json.dumps(raw, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        archive.writestr(name, raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
        add(archive, 'experiment.json', plan)
        add(archive, 'activity.json', store.events(plan['id']))
        if plan.get('device_id'):
            add(archive, 'device.json', store.get('devices', plan['device_id']))
        for ref in plan['references']:
            record = resolve(ctx, domain, ref['kind'], ref['id'])
            if ref['kind'] == 'run':
                if domain == 'wind':
                    raw = ctx.repo.zip_bytes(ref['id'])
                else:
                    output = io.BytesIO(); export_run(run_folder(ctx.root, ref['id']), output); raw = output.getvalue()
                add(archive, 'runs/'+ref['id']+'.zip', raw)
            elif ref['kind'] == 'dataset':
                add(archive, 'datasets/'+ref['id']+'/metadata.json', Lab.summary(record))
                add(archive, 'datasets/'+ref['id']+'/data.csv', csv_bytes(domain, record['rows']))
            else:
                add(archive, 'reports/'+ref['id']+'.json', record)
        add(archive, 'README.txt', '实验参数、操作时间与数据来源按实际记录保存。仿真与演示数据不能作为实体性能结果。\n'.encode('utf-8'))
        archive.writestr('manifest.json', json.dumps(hashes, indent=2))
    return buf.getvalue()


def handle(request, ctx, domain, route, raw):
    import workspace_adapter as adapter
    from portal import data
    store = Studio(ctx.root)
    if request.method == 'GET':
        reconcile(store, ctx, domain)
        if route == 'studio/bootstrap':
            lab = Lab(ctx.root, domain)
            usage = data.usage(ctx.root)
            plans, devices, recipes = [store.list(c) for c in ('plans','devices','recipes')]
            records = runs(ctx, domain)
            activity = store.events(limit=30)
            return dict(domain=domain, title=adapter.TITLE, version=adapter.VERSION, mode=settings.DEPLOYMENT_MODE,
                        states=STATES, presets=presets(domain), plans=plans, devices=devices, recipes=recipes,
                        runs=records, datasets=lab.list(), reports=lab.list('reports'), activity=activity,
                        preferences=store.preferences(), notices=notice_list(store, usage),
                        storage=dict(used=usage, limit=settings.MAX_WORKSPACE_BYTES),
                        runtime=dict(os=platform.system(), python=platform.python_version(), interface='browser + local gateway'),
                        operator=request.user.is_staff, hardware_allowed=domain=='ld' and settings.DEPLOYMENT_MODE=='local' and request.user.is_staff)
        if route == 'studio/search':
            query = text(request.GET.get('q', ''), '搜索词', 100).lower()
            return [r for r in search_index(store, ctx, domain) if query in (r['name']+' '+r['description']+' '+r['id']).lower()][:100]
        parts = route.split('/')
        if len(parts) >= 3 and parts[1] == 'plans':
            plan = store.get('plans', parts[2])
            if len(parts) == 3:
                return dict(plan=plan, events=store.events(plan['id']))
            if len(parts) == 4 and parts[3] == 'download':
                if plan['state'] == 'running':
                    raise RuntimeError('请等运行结束后再下载完整实验包')
                response = HttpResponse(dossier(store, plan, ctx, domain), content_type='application/zip')
                response['Content-Disposition'] = 'attachment; filename="experiment-'+plan['id']+'.zip"'
                return response
        raise FileNotFoundError()
    data.check_quota(ctx, 0)
    if data.usage(ctx.root) + len(json.dumps(raw, ensure_ascii=False).encode()) * 3 > settings.MAX_WORKSPACE_BYTES:
        raise ValueError('工作区容量不足')
    if route == 'studio/preferences':
        updates = {}
        for field, choices in [('theme', ('light','dark')), ('density', ('comfortable','compact'))]:
            if field in raw:
                if raw[field] not in choices:
                    raise ValueError('外观选项不正确')
                updates[field] = raw[field]
        return store.preferences(updates)
    if route == 'studio/favorite':
        identity = str(raw.get('kind'))+':'+str(raw.get('id'))
        if not any(identity == r['kind']+':'+r['id'] for r in search_index(store, ctx, domain)):
            raise FileNotFoundError()
        def toggle(pref):
            favs = pref['favorites']
            if identity in favs:
                favs.remove(identity)
            elif len(favs) < 100:
                favs.append(identity)
            else:
                raise ValueError('收藏最多100项')
        return store.preferences(toggle)
    if route == 'studio/dismiss':
        notice = text(raw.get('id'), '通知编号', 100, True)
        if not any(r['id'] == notice for r in notice_list(store, data.usage(ctx.root))):
            raise FileNotFoundError()
        def dismiss(pref):
            pref['dismissed'] = list(dict.fromkeys(pref['dismissed'] + [notice]))[-200:]
        return store.preferences(dismiss)
    if route == 'studio/recipes':
        return store.create('recipes', dict(name=text(raw.get('name'), '模板名称', 80, True), config=config(raw.get('config'), domain)))
    if route == 'studio/devices':
        return store.create('devices', device_payload(raw, domain))
    if route == 'studio/plans':
        device = raw.get('device_id', '')
        if device:
            item = store.get('devices', device)
            if item['archived']:
                raise ValueError('设备档案已归档')
        priority = raw.get('priority', 'normal')
        if priority not in ('high','normal','low'):
            raise ValueError('实验优先级不正确')
        return store.create('plans', dict(name=text(raw.get('name'), '实验名称', 80, True),
                            objective=text(raw.get('objective'), '实验目的', 1000, True), priority=priority,
                            config=config(raw.get('config'), domain), state='draft', device_id=device,
                            references=[], conclusion='', checklist=False, run_id=''))
    parts = route.split('/')
    if len(parts) != 4 or parts[1] not in ('plans','devices','recipes'):
        raise FileNotFoundError()
    collection, ident, action = parts[1:]
    item = store.get(collection, ident)
    version = raw.get('version')
    if action == 'archive':
        if item.get('state') == 'running':
            raise RuntimeError('运行中的实验不能归档')
        if type(raw.get('archived')) is not bool:
            raise ValueError('归档状态应为布尔值')
        return store.update(collection, ident, version, 'archive_changed', lambda p: p.update(archived=raw['archived']))
    if item['archived']:
        raise RuntimeError('请先恢复这条记录')
    if collection == 'devices' and action == 'calibrate':
        c = calibration(raw)
        def add_calibration(p):
            if len(p['calibrations']) >= 200:
                raise ValueError('该设备最多200条校准记录')
            p['calibrations'].append(c)
            return c
        return store.update(collection, ident, version, 'calibrated', add_calibration)
    if collection != 'plans':
        raise FileNotFoundError()
    if action == 'ready':
        def ready(p):
            if p['state'] != 'draft' or raw.get('confirmed') is not True:
                raise ValueError('请核对参数和实验目的后确认')
            p.update(state='ready', checklist=True)
        return store.update(collection, ident, version, 'prepared', ready)
    if action == 'attach':
        kind, target = raw.get('kind'), raw.get('target')
        record = resolve(ctx, domain, kind, target)
        def attach(p):
            if p['state'] not in ('ready','review'):
                raise ValueError('实验需处于已核对或待复核状态')
            ref = dict(kind=kind, id=target)
            if ref not in p['references']:
                if len(p['references']) >= 30:
                    raise ValueError('每个实验最多关联30项资料')
                p['references'].append(ref)
            if kind == 'run' and (p['state'] == 'ready' or not p.get('run_id')):
                p.update(state='review', run_id=target)
            return ref
        return store.update(collection, ident, version, 'reference_attached', attach)
    if action == 'complete':
        conclusion = text(raw.get('conclusion'), '实验结论', 4000, True)
        def complete(p):
            if p['state'] != 'review' or not p['run_id'] or len(conclusion) < 10:
                raise ValueError('实验需有运行结果，处于待复核状态并填写至少10字结论')
            resolve(ctx, domain, 'run', p['run_id'])
            p.update(state='completed', conclusion=conclusion)
        return store.update(collection, ident, version, 'review_completed', complete)
    if action == 'start':
        def reserve(p):
            if p['state'] != 'ready':
                raise RuntimeError('实验需先核对参数，不能重复执行')
            p['state'] = 'running'
        reserved = store.update(collection, ident, version, 'run_requested', reserve)
        try:
            if domain == 'ld':
                adapter.handle(request, 'start', reserved['config'])
                run_id = ctx.engine.snapshot()['run_id']
                final_state = 'running'
            else:
                result = adapter.handle(request, 'run', dict(name=reserved['name'], config=reserved['config']))
                run_id = result['id']; final_state = 'review'
            def bind(p):
                p.update(run_id=run_id, state=final_state)
                p['references'].append(dict(kind='run', id=run_id))
                return {'run_id': run_id}
            return store.update(collection, ident, reserved['version'], 'run_attached', bind)
        except Exception:
            store.update(collection, ident, reserved['version'], 'run_failed', lambda p: p.update(state='ready'))
            raise
    raise FileNotFoundError()
