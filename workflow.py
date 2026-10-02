"""资产、缺陷复核和本地工单状态流转。"""
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
import sqlite3
class ConflictError(ValueError):
    """其他窗口已修改该记录，调用方需要刷新后重新确认。"""
def text_field(raw, key, maximum):
    value = raw.get(key)
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValueError(key + '不能为空或超过长度限制')
    return value.strip()
class Workflow:
    transitions = {
        'pending': {'confirm': 'confirmed', 'reject': 'rejected'},
        'confirmed': {'dispatch': 'assigned'},
        'assigned': {'resolve': 'resolved'},
        'resolved': {'accept': 'closed', 'return': 'assigned'},
        'rejected': {'reopen': 'pending'},
        'closed': {'reopen': 'pending'},
    }
    def __init__(self, root, repository):
        self.path = Path(root) / 'engineering.sqlite3'
        self.repository = repository
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS assets ('
                       'id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, '
                       'name TEXT NOT NULL, location TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS defects ('
                       'id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id), '
                       'task_id TEXT NOT NULL, title TEXT NOT NULL, severity TEXT NOT NULL, '
                       'status TEXT NOT NULL, revision INTEGER NOT NULL, '
                       'work_order TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)')
            db.execute('CREATE TABLE IF NOT EXISTS workflow_events ('
                       'seq INTEGER PRIMARY KEY AUTOINCREMENT, '
                       'defect_id TEXT NOT NULL REFERENCES defects(id), '
                       'action TEXT NOT NULL, from_status TEXT, to_status TEXT NOT NULL, '
                       'reason TEXT NOT NULL, revision INTEGER NOT NULL, '
                       'created TEXT DEFAULT CURRENT_TIMESTAMP)')
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        try:
            with db:
                yield db
        finally:
            db.close()
    def snapshot(self):
        # 同一读取事务避免列表与审计记录来自两个不同更新时刻。
        with self.connect() as db:
            db.execute('BEGIN')
            return {name: [dict(r) for r in db.execute(query)] for name, query in {
                'assets': 'SELECT * FROM assets ORDER BY code',
                'defects': 'SELECT d.*, a.code AS asset_code FROM defects d '
                           'JOIN assets a ON d.asset_id = a.id ORDER BY d.rowid DESC',
                'events': 'SELECT * FROM workflow_events ORDER BY seq DESC',
            }.items()}
    def asset(self, raw):
        code = text_field(raw, 'code', 40)
        name = text_field(raw, 'name', 80)
        location = text_field(raw, 'location', 120)
        key = uuid4().hex
        with self.connect() as db:
            try:
                db.execute('INSERT INTO assets VALUES (?, ?, ?, ?)',
                           (key, code, name, location))
            except sqlite3.IntegrityError as exc:
                raise ValueError('资产编号已存在，请选择原资产') from exc
        return {'id': key, 'code': code, 'name': name, 'location': location}
    def defect(self, raw):
        asset_id = text_field(raw, 'asset_id', 32)
        task_id = text_field(raw, 'task_id', 16)
        self.repository.get(task_id)
        title = text_field(raw, 'title', 120)
        reason = text_field(raw, 'reason', 1000)
        severity = raw.get('severity')
        if severity not in {'low', 'medium', 'high'}:
            raise ValueError('缺陷等级应为低、中或高')
        key = uuid4().hex
        with self.connect() as db:
            if not db.execute('SELECT id FROM assets WHERE id = ?', (asset_id,)).fetchone():
                raise ValueError('关联资产不存在')
            db.execute('INSERT INTO defects '
                       '(id, asset_id, task_id, title, severity, status, revision) '
                       'VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (key, asset_id, task_id, title, severity, 'pending', 1))
            db.execute('INSERT INTO workflow_events '
                       '(defect_id, action, to_status, reason, revision) '
                       'VALUES (?, ?, ?, ?, ?)', (key, 'create', 'pending', reason, 1))
        return {'id': key, 'status': 'pending', 'revision': 1}
    def transition(self, raw):
        key = text_field(raw, 'id', 32)
        action = text_field(raw, 'action', 20)
        reason = text_field(raw, 'reason', 1000)
        revision = raw.get('revision')
        if type(revision) is not int or revision < 1:
            raise ValueError('记录版本必须为正整数')
        with self.connect() as db:
            # 获取写锁后读取版本，状态与审计事件共同提交或共同回滚。
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM defects WHERE id = ?', (key,)).fetchone()
            if row is None:
                raise ValueError('缺陷记录不存在')
            if row['revision'] != revision:
                raise ConflictError('记录已更新，请刷新后重新核对')
            target = self.transitions.get(row['status'], {}).get(action)
            if target is None:
                raise ValueError('当前状态不允许该操作')
            order = row['work_order']
            if action == 'dispatch':
                order = uuid4().hex
            db.execute('UPDATE defects SET status = ?, revision = ?, work_order = ? '
                       'WHERE id = ?', (target, revision + 1, order, key))
            db.execute('INSERT INTO workflow_events '
                       '(defect_id, action, from_status, to_status, reason, revision) '
                       'VALUES (?, ?, ?, ?, ?, ?)',
                       (key, action, row['status'], target, reason, revision + 1))
        return {'id': key, 'status': target, 'revision': revision + 1, 'work_order': order}
