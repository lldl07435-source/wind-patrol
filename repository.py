"""保存任务、对比结果和导出文件。"""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import csv
import io
import json
import re
import zipfile
import sqlite3
from contextlib import contextmanager
from analysis import metrics
from quadrotor_patrol_simulation import write_report
class Repository:
    def __init__(self, output_root):
        self.output_root = Path(output_root).resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.database = self.output_root / 'tasks.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tasks ('
                       'id TEXT PRIMARY KEY, name TEXT NOT NULL, '
                       'created TEXT NOT NULL, summary TEXT NOT NULL, '
                       'result TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS comparisons ('
                       'id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()
    @staticmethod
    def make_record(name, result):
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError('任务名称应为1 至80 个字符')
        return {'id': uuid4().hex[:16], 'name': name.strip(),
                'created': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'result': result}
    @staticmethod
    def insert(db, record):
        db.execute('INSERT INTO tasks VALUES (?, ?, ?, ?, ?)', (
            record['id'], record['name'], record['created'],
            json.dumps(record['result']['summary'], allow_nan=False),
            json.dumps(record['result'], ensure_ascii=False, allow_nan=False)))
    def add(self, name, result):
        record = self.make_record(name, result)
        with self.connect() as db:
            self.insert(db, record)
        return record
    def get(self, key):
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{16}', key):
            raise ValueError('任务编号格式不正确')
        with self.connect() as db:
            row = db.execute('SELECT * FROM tasks WHERE id = ?', (key,)).fetchone()
        if row is None:
            raise KeyError('任务不存在，请检查数据目录')
        return {'id': row['id'], 'name': row['name'], 'created': row['created'],
                'result': json.loads(row['result'])}
    def list(self):
        with self.connect() as db:
            rows = db.execute('SELECT id, name, created, summary FROM tasks '
                              'ORDER BY rowid DESC').fetchall()
        return [dict(id=r['id'], name=r['name'], created=r['created'],
                     summary=json.loads(r['summary'])) for r in rows]
    def save_comparison(self, records, report):
        # 两组任务与汇总同事务提交，避免出现只有一半的对比证据。
        with self.connect() as db:
            for record in records:
                self.insert(db, record)
            db.execute('INSERT INTO comparisons VALUES (?, ?)',
                       (report['id'], json.dumps(report, ensure_ascii=False,
                                                allow_nan=False)))
        return report
    def comparisons(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute(
                'SELECT payload FROM comparisons ORDER BY rowid DESC')]
    def export(self, key):
        record = self.get(key)
        # 新目录名由服务端生成，不接受名称中的路径分隔符。
        target = self.output_root / (key + '_' + uuid4().hex[:8])
        write_report(record['result'], target)
        (target / 'metrics.json').write_text(json.dumps(
            metrics(record['result']), ensure_ascii=False, indent=2,
            allow_nan=False), encoding='utf-8')
        (target / 'task.json').write_text(json.dumps(
            {k: record[k] for k in ('id', 'name', 'created')},
            ensure_ascii=False, indent=2), encoding='utf-8')
        return target
    def zip_bytes(self, key):
        record = self.get(key)
        result = record['result']
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('task.json', json.dumps(
                {field: record[field] for field in ('id', 'name', 'created')},
                ensure_ascii=False, indent=2))
            for field in ('config', 'summary', 'events'):
                archive.writestr(field + '.json', json.dumps(
                    result[field], ensure_ascii=False, indent=2, allow_nan=False))
            archive.writestr('metrics.json', json.dumps(
                metrics(result), ensure_ascii=False, indent=2, allow_nan=False))
            stream = io.StringIO(newline='')
            columns = ['time', 'mode', 'x', 'y', 'z', 'speed', 'battery',
                       'target_index', 'target_distance', 'sensor_valid',
                       'command_emitted', 'virtual_latency', 'wind_x',
                       'wind_y', 'wind_z', 'wind_speed',
                       'wind_estimate_speed', 'wind_regime', 'gust_factor']
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(result['samples'])
            archive.writestr('trajectory.csv', stream.getvalue().encode('utf-8-sig'))
        return buffer.getvalue()
