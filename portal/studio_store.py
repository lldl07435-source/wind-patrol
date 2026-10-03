"""实验计划与设备档案。业务结果仍使用原有运行库。"""
import json
import math
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, date


def now():
    return datetime.now(timezone.utc).isoformat()


def text(value, label, limit=2000, required=False):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise ValueError(label + '格式或长度不正确')
    value = value.strip()
    if required and not value:
        raise ValueError('请填写' + label)
    return value


def key(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('记录编号格式不正确')
    return value


class Studio:
    LIMITS = {'plans': 500, 'devices': 100, 'recipes': 200}

    def __init__(self, root):
        self.path = root / 'studio.sqlite3'
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY, collection TEXT NOT NULL, version INTEGER NOT NULL,
                payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS records_collection ON records(collection);
                CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT, time TEXT, action TEXT, payload TEXT);
                CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT);
            ''')

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=20)
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _event(self, db, item, action, details):
        db.execute('INSERT INTO events(record_id,time,action,payload) VALUES(?,?,?,?)',
                   (item['id'], now(), action, json.dumps(details, ensure_ascii=False, allow_nan=False)))

    def list(self, collection):
        if collection not in self.LIMITS:
            raise ValueError('不支持的记录类型')
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute(
                'SELECT payload FROM records WHERE collection=? ORDER BY rowid DESC', (collection,))]

    def get(self, collection, ident):
        with self.db() as db:
            row = db.execute('SELECT payload FROM records WHERE collection=? AND id=?', (collection, key(ident))).fetchone()
        if row is None:
            raise FileNotFoundError()
        return json.loads(row[0])

    def create(self, collection, payload):
        if collection not in self.LIMITS:
            raise ValueError('不支持的记录类型')
        item = dict(payload, id=uuid.uuid4().hex, created=now(), updated=now(), version=1, archived=False)
        with self.db() as db:
            count = db.execute('SELECT count(*) FROM records WHERE collection=?', (collection,)).fetchone()[0]
            if count >= self.LIMITS[collection]:
                raise ValueError('该类记录已达到工作区容量上限')
            db.execute('INSERT INTO records VALUES(?,?,?,?)', (item['id'], collection, 1, json.dumps(item, ensure_ascii=False, allow_nan=False)))
            self._event(db, item, 'created', {'collection': collection})
        return item

    def update(self, collection, ident, expected, action, change):
        if type(expected) is not int:
            raise ValueError('请刷新后重试')
        with self.db() as db:
            row = db.execute('SELECT version,payload FROM records WHERE collection=? AND id=?', (collection, key(ident))).fetchone()
            if row is None:
                raise FileNotFoundError()
            if row[0] != expected:
                raise RuntimeError('记录已被另一页面修改，请刷新后重试')
            item = json.loads(row[1])
            details = change(item)
            item.update(version=expected + 1, updated=now())
            db.execute('UPDATE records SET version=?,payload=? WHERE id=?',
                       (item['version'], json.dumps(item, ensure_ascii=False, allow_nan=False), ident))
            self._event(db, item, action, details or {})
        return item

    def events(self, ident=None, limit=80):
        with self.db() as db:
            if ident:
                rows = db.execute('SELECT seq,record_id,time,action,payload FROM events WHERE record_id=? ORDER BY seq DESC', (key(ident),))
            else:
                rows = db.execute('SELECT seq,record_id,time,action,payload FROM events ORDER BY seq DESC LIMIT ?', (limit,))
            return [dict(seq=r[0], id=r[1], time=r[2], action=r[3], details=json.loads(r[4])) for r in rows]

    def preferences(self, updates=None):
        with self.db() as db:
            row = db.execute('SELECT payload FROM preferences WHERE id=1').fetchone()
            pref = dict(theme='light', density='comfortable', favorites=[], dismissed=[])
            if row:
                pref.update(json.loads(row[0]))
            if updates:
                if callable(updates):
                    updates(pref)
                else:
                    pref.update(updates)
                db.execute('INSERT OR REPLACE INTO preferences VALUES(1,?)', (json.dumps(pref, ensure_ascii=False),))
        return pref


def device_payload(raw, domain):
    name = text(raw.get('name'), '设备名称', 80, True)
    model = text(raw.get('model', ''), '型号', 80)
    serial = text(raw.get('serial', ''), '资产编号', 80)
    note = text(raw.get('note', ''), '设备备注')
    interface = raw.get('interface', 'serial' if domain == 'ld' else 'csv')
    if interface not in ('serial', 'csv', 'simulation'):
        raise ValueError('接口类型不正确')
    return dict(name=name, model=model, serial=serial, interface=interface, note=note, calibrations=[])


def calibration(raw):
    label = text(raw.get('label'), '测量项', 80, True)
    unit = text(raw.get('unit'), '单位', 20, True)
    values = {}
    for field in ('reference', 'observed', 'tolerance'):
        value = raw.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e7:
            raise ValueError('校准观测应为有限数值')
        values[field] = value
    if values['tolerance'] < 0:
        raise ValueError('允许偏差不能为负数')
    expires = raw.get('expires', '')
    if expires:
        try:
            date.fromisoformat(expires)
        except (ValueError, TypeError):
            raise ValueError('有效期应为年月日') from None
    source = raw.get('source', 'measured')
    if source not in ('measured', 'demo'):
        raise ValueError('请标注现场观测或演示数据')
    delta = values['observed'] - values['reference']
    return dict(id=uuid.uuid4().hex, time=now(), label=label, unit=unit, **values, error=delta,
                passed=abs(delta) <= values['tolerance'], expires=expires, source=source,
                note=text(raw.get('note', ''), '测量备注', 1000))
