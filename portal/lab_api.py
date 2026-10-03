import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path
from django.http import HttpResponse
from django.conf import settings
from .experiment_lab import Lab, COLUMNS, KINDS, parse_csv, csv_bytes

def candidates(ctx, domain):
    if domain == 'wind':
        return [{'id': r['id'], 'name': r['name'], 'kind': 'simulation'} for r in ctx.repo.list()[:100]]
    from ldcell.storage import history
    return [{'id': r['id'], 'name': r['started_at']+' / '+r['mode'], 'kind': r['mode']}
            for r in history(ctx.root) if r['status'] not in ('running','interrupted','failed')]

def native(ctx, domain, key):
    if domain == 'wind':
        record = ctx.repo.get(key)
        return 'simulation', [dict(time_s=r['time'], x_m=r['x'], y_m=r['y'], z_m=r['z'])
                              for r in record['result']['samples']]
    from ldcell.storage import run_folder, verify
    folder = run_folder(ctx.root, key)
    if not verify(folder)['ok']:
        raise ValueError('运行尚未封存或记录校验未通过；请先结束该次运行')
    meta = json.loads((folder/'meta.json').read_text(encoding='utf-8'))
    events = [json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    rows, origin = [], None
    for event in events:
        if event['kind'] != 'job_result':
            continue
        r = event['data']
        if meta['mode'] == 'hardware':
            start = r['uptime_start']
            if origin is None:
                origin = start
            end = r.get('uptime_end', start)
            time = ((end-origin)&0xffffffff)/1000
            cycle = ((end-start)&0xffffffff)/1000 if r['outcome'] == 'completed' else None
        else:
            time, cycle = r['finished'], r['finished']-r['started']
        rows.append(dict(time_s=time, job_id=str(r['order_id']), cycle_s=cycle,
                         route=r['route'], outcome=r['outcome']))
    return meta['mode'], rows

def handle(request, ctx, domain, route, raw):
    lab = Lab(ctx.root, domain)
    if request.method == 'GET':
        if route == 'lab/config':
            return {'domain': domain, 'title': 'LD-Flex' if domain == 'ld' else '风巡智航',
                    'columns': COLUMNS[domain], 'kinds': KINDS, 'candidates': candidates(ctx, domain),
                    'mode': settings.DEPLOYMENT_MODE}
        if route == 'lab/datasets':
            return lab.list()
        if route == 'lab/reports':
            return lab.list('reports')
        parts = route.split('/')
        if len(parts) == 3 and parts[1] == 'datasets':
            item = lab.get(parts[2]); rows = item['rows']
            # 图表抽样，数据库和下载文件仍保留完整数据。
            stride = max(1, (len(rows)+999)//1000)
            points = rows[::stride]
            if points[-1] != rows[-1]:
                points.append(rows[-1])
            return {**lab.summary(item), 'rows': points, 'plot_sampled': len(points) != len(rows)}
        if len(parts) == 4 and parts[3] == 'download' and parts[1] in ('datasets','reports'):
            item = lab.get(parts[2], parts[1])
            if parts[1] == 'reports':
                payload = json.dumps(item, ensure_ascii=False, indent=2).encode('utf-8')
                response = HttpResponse(payload, content_type='application/json; charset=utf-8')
                filename = 'comparison-'+item['id']+'.json'
            else:
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('metadata.json', json.dumps(lab.summary(item), ensure_ascii=False, indent=2))
                    archive.writestr('data.csv', csv_bytes(domain, item['rows']))
                    if item['source_text'] is not None:
                        archive.writestr('original.csv', item['source_text'].encode('utf-8'))
                response = HttpResponse(buffer.getvalue(), content_type='application/zip')
                filename = 'dataset-'+item['id']+'.zip'
            response['Content-Disposition'] = 'attachment; filename="'+filename+'"'
            return response
        raise FileNotFoundError()
    from portal import data
    data.check_quota(ctx, 0)
    if route == 'lab/import':
        kind = raw.get('kind')
        if kind not in ('measured_import','simulation_import','demo'):
            raise ValueError('导入时请选择实测、仿真或演示来源')
        text = raw.get('csv')
        frame = raw.get('frame','ENU')
        rows = parse_csv(domain, text, frame)
        if data.usage(ctx.root) + len(text.encode('utf-8'))*6 > settings.MAX_WORKSPACE_BYTES:
            raise ValueError('工作区剩余空间不足')
        return lab.add(raw.get('name'),kind,rows,source_text=text,frame=frame,note=raw.get('note',''))
    if route == 'lab/native':
        key = raw.get('source_id')
        kind, rows = native(ctx,domain,key)
        if data.usage(ctx.root) + len(rows)*500 > settings.MAX_WORKSPACE_BYTES:
            raise ValueError('工作区剩余空间不足')
        return lab.add(raw.get('name'),kind,rows,source_id=key,note=raw.get('note',''))
    if route == 'lab/compare':
        if len(lab.list('reports')) >= 500:
            raise ValueError('对照报告已达到500份上限')
        return lab.compare(raw)
    raise FileNotFoundError()
