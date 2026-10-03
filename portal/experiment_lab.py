"""仿真与实测数据的个人实验库。原始运行仍由原来的仓储保管。"""
import bisect
import csv
import hashlib
import io
import json
import math
import re
import sqlite3
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LIMIT = 20000
CSV_LIMIT = 750000
COLUMNS = {'ld': ['time_s', 'job_id', 'cycle_s', 'route', 'outcome'],
           'wind': ['time_s', 'x_m', 'y_m', 'z_m']}
KINDS = {'simulation': '原生仿真', 'hardware': '本机设备记录',
         'measured_import': '实测导入（用户标注）', 'simulation_import': '仿真导入（用户标注）',
         'demo': '接口演示数据'}

def finite(value, field, minimum=-1e7, maximum=1e7):
    if isinstance(value, bool):
        raise ValueError(field + '必须是有限数值')
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise ValueError(field + '必须是有限数值') from None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(field + '超出允许范围')
    return number

def validate(domain, rows):
    if domain not in COLUMNS or not isinstance(rows, list) or not 1 <= len(rows) <= LIMIT:
        raise ValueError('数据应包含1至20000行')
    output = []
    previous = -1.0
    for index, item in enumerate(rows, 1):
        if not isinstance(item, dict):
            raise ValueError(f'第{index}行格式不正确')
        row = {'time_s': finite(item.get('time_s'), f'第{index}行时间', 0)}
        if row['time_s'] < previous or (domain == 'wind' and row['time_s'] == previous):
            raise ValueError(f'第{index}行时间应递增；飞行轨迹不接受重复时间')
        previous = row['time_s']
        if domain == 'wind':
            for field in ('x_m', 'y_m', 'z_m'):
                row[field] = finite(item.get(field), f'第{index}行{field}', -100000, 100000)
        else:
            job = str(item.get('job_id', '')).strip()
            if not 1 <= len(job) <= 40 or job[0] in '=+-@' or any(c in job for c in '\r\n\x00'):
                raise ValueError(f'第{index}行物料编号格式不正确')
            route = str(item.get('route', ''))
            outcome = item.get('outcome')
            if route not in ('0', '1') or outcome not in ('completed', 'unknown'):
                raise ValueError(f'第{index}行出口为0/1，结果为completed/unknown')
            cycle = item.get('cycle_s')
            if outcome == 'completed':
                cycle = finite(cycle, f'第{index}行周期', 0, 600)
            else:
                cycle = None
            row.update(job_id=job, route=int(route), outcome=outcome, cycle_s=cycle)
        output.append(row)
    return output

def parse_csv(domain, text, frame='ENU'):
    if not isinstance(text, str) or len(text.encode('utf-8')) > CSV_LIMIT:
        raise ValueError('CSV 文件最多750 KB')
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff'), newline=''))
    if reader.fieldnames != COLUMNS[domain]:
        raise ValueError('CSV 表头应为：' + ','.join(COLUMNS[domain]))
    rows = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError('CSV 每行的列数应与表头一致')
        rows.append(row)
        if len(rows) > LIMIT:
            raise ValueError('CSV 最多20000行')
    result = validate(domain, rows)
    if frame not in ('ENU', 'NED') or (domain == 'ld' and frame != 'ENU'):
        raise ValueError('坐标系应为ENU或NED')
    if domain == 'wind' and frame == 'NED':
        for row in result:
            row['x_m'], row['y_m'], row['z_m'] = row['y_m'], row['x_m'], -row['z_m']
    return result

def csv_bytes(domain, rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=COLUMNS[domain])
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return stream.getvalue().encode('utf-8-sig')

def stats(values):
    if not values:
        return {'count': 0, 'mae': None, 'rmse': None, 'bias': None, 'p95': None, 'maximum': None}
    absolute = sorted(abs(x) for x in values)
    return {'count': len(values), 'mae': sum(absolute) / len(values),
            'rmse': math.sqrt(sum(x*x for x in values) / len(values)),
            'bias': sum(values) / len(values), 'p95': absolute[math.ceil(.95*len(values))-1],
            'maximum': absolute[-1]}

def compare_ld(base, observed):
    # 物料编号才是配对依据；绝不能按第几行凑出一组“实测误差”。
    counts_a = Counter(r['job_id'] for r in base)
    counts_b = Counter(r['job_id'] for r in observed)
    a = {r['job_id']: r for r in base if counts_a[r['job_id']] == 1}
    b = {r['job_id']: r for r in observed if counts_b[r['job_id']] == 1}
    common = sorted(a.keys() & b.keys())
    errors = [b[k]['cycle_s']-a[k]['cycle_s'] for k in common
              if a[k]['outcome'] == b[k]['outcome'] == 'completed' and a[k]['route'] == b[k]['route']]
    if not errors:
        raise ValueError('没有可配对的已完成物料；请核对物料编号与目标出口')
    return {'unit': 's', 'metric': '单件周期误差（对照减基准）', **stats(errors),
            'matched_jobs': len(common), 'unmatched_base': len(base)-len(common),
            'unmatched_observed': len(observed)-len(common),
            'route_mismatches': sum(a[k]['route'] != b[k]['route'] for k in common),
            'outcome_mismatches': sum(a[k]['outcome'] != b[k]['outcome'] for k in common),
            'duplicate_jobs': sum(n > 1 for n in counts_a.values()) + sum(n > 1 for n in counts_b.values())}

def compare_wind(base, observed, offset=0, max_gap=1):
    offset = finite(offset, '时间偏移', -3600, 3600)
    max_gap = finite(max_gap, '最大插值间隔', .001, 60)
    if len(base) < 2:
        raise ValueError('基准轨迹至少需要两个采样点')
    times = [r['time_s'] for r in base]
    distances, axes = [], [[], [], []]
    for row in observed:
        time = row['time_s'] + offset
        pos = bisect.bisect_left(times, time)
        if pos < len(times) and times[pos] == time:
            point = base[pos]
        elif pos == 0 or pos == len(times):
            continue
        else:
            left, right = base[pos-1], base[pos]
            gap = right['time_s']-left['time_s']
            if gap > max_gap:
                continue
            weight = (time-left['time_s']) / gap
            point = {key: left[key]+(right[key]-left[key])*weight for key in ('x_m','y_m','z_m')}
        errors = [row[key]-point[key] for key in ('x_m','y_m','z_m')]
        distances.append(math.sqrt(sum(x*x for x in errors)))
        for values, error in zip(axes, errors):
            values.append(error)
    if not distances:
        raise ValueError('两条轨迹没有有效重叠时间；检查时间偏移或采样间隔')
    return {'unit': 'm', 'metric': '时间对齐后的三维位置误差', **stats(distances),
            'axis_bias': dict(zip(('x','y','z'), (sum(x)/len(x) for x in axes))),
            'coverage': len(distances)/len(observed), 'skipped_samples': len(observed)-len(distances),
            'offset_s': offset, 'max_gap_s': max_gap}

class Lab:
    def __init__(self, root, domain):
        self.root, self.domain = Path(root), domain
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / 'experiments.sqlite3', timeout=20)
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, name, kind, rows, source_id='', source_text=None, frame='ENU', note=''):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or kind not in KINDS:
            raise ValueError('请输入1至80字名称并选择数据来源')
        if not isinstance(note, str) or len(note) > 1000:
            raise ValueError('实验备注最多1000字')
        rows = validate(self.domain, rows)
        raw = source_text.encode('utf-8') if source_text is not None else csv_bytes(self.domain, rows)
        item = {'id': uuid.uuid4().hex, 'name': name.strip(), 'kind': kind, 'kind_label': KINDS[kind],
                'domain': self.domain, 'created': datetime.now(timezone.utc).isoformat(),
                'source_id': source_id, 'input_frame': frame, 'frame': 'ENU', 'note': note,
                'sha256': hashlib.sha256(raw).hexdigest(), 'count': len(rows), 'rows': rows,
                'normalized_sha256': hashlib.sha256(csv_bytes(self.domain, rows)).hexdigest(),
                'hash_basis': 'UTF-8 CSV content received by server' if source_text is not None else 'normalized UTF-8-BOM CSV',
                'source_text': source_text, 'duration_s': rows[-1]['time_s']-rows[0]['time_s']}
        with self.db() as db:
            if db.execute('SELECT COUNT(*) FROM datasets').fetchone()[0] >= 200:
                raise ValueError('实验数据集达到200组上限')
            db.execute('INSERT INTO datasets VALUES(?,?)', (item['id'], json.dumps(item, ensure_ascii=False, allow_nan=False)))
        return self.summary(item)

    @staticmethod
    def summary(item):
        return {key: value for key, value in item.items() if key not in ('rows', 'source_text')}

    def get(self, key, table='datasets'):
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{32}', key):
            raise ValueError('实验编号格式不正确')
        with self.db() as db:
            row = db.execute('SELECT payload FROM '+table+' WHERE id=?', (key,)).fetchone()
        if not row:
            raise FileNotFoundError()
        return json.loads(row[0])

    def list(self, table='datasets'):
        with self.db() as db:
            return [self.summary(json.loads(r[0])) for r in db.execute('SELECT payload FROM '+table+' ORDER BY rowid DESC')]

    def compare(self, raw):
        if raw.get('base') == raw.get('observed'):
            raise ValueError('请选择两组不同数据')
        a, b = self.get(raw.get('base')), self.get(raw.get('observed'))
        if self.domain == 'wind' and raw.get('frame_confirmed') is not True:
            raise ValueError('请先确认两组轨迹的坐标原点、轴向与单位一致')
        metrics = compare_ld(a['rows'], b['rows']) if self.domain == 'ld' else compare_wind(
            a['rows'], b['rows'], raw.get('offset_s', 0), raw.get('max_gap_s', 1))
        report = {'id': uuid.uuid4().hex, 'created': datetime.now(timezone.utc).isoformat(),
                  'base': self.summary(a), 'observed': self.summary(b), 'metrics': metrics,
                  'method': '物料编号配对；重复编号、未知结果和不同出口不进入周期误差' if self.domain == 'ld'
                  else '局部ENU坐标；按显式时间偏移线性插值；不外推；排除超长采样间隔',
                  'scope': '数据对照结果。数据来源标注与摘要不能独立证明实体装置性能。'}
        with self.db() as db:
            db.execute('INSERT INTO reports VALUES(?,?)', (report['id'], json.dumps(report, ensure_ascii=False, allow_nan=False)))
        return report
