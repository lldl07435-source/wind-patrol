"""工程工作台的记录存储。"""
import math
import sqlite3
from pathlib import Path
from uuid import uuid4
from contextlib import contextmanager
class EngineeringStore:
    def __init__(self, output):
        root = Path(output)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / 'engineering.sqlite3'
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY, page TEXT NOT NULL, name TEXT NOT NULL,
                status TEXT NOT NULL, risk REAL NOT NULL, note TEXT NOT NULL,
                updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()
    def list(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM records ORDER BY updated DESC, id DESC')]
    def create(self, raw):
        page = raw.get('page')
        name = raw.get('name')
        note = raw.get('note', '')
        status = raw.get('status', 'draft')
        if not isinstance(page, str) or not 1 <= len(page) <= 48 or not all(
                c in 'abcdefghijklmnopqrstuvwxyz-' for c in page):
            raise ValueError('页面标识不合法')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError('名称应为1 至80 个字符')
        if not isinstance(note, str) or len(note) > 1000:
            raise ValueError('备注不能超过1000 个字符')
        if status not in ('draft', 'active', 'review', 'paused', 'completed', 'archived'):
            raise ValueError('记录状态不合法')
        risk = raw.get('risk', 0)
        if isinstance(risk, bool) or not isinstance(risk, (int, float)) or not math.isfinite(risk) or not 0 <= risk <= 100:
            raise ValueError('风险评分应为0 至100 的有限数值')
        identifier = uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO records (id,page,name,status,risk,note) VALUES (?,?,?,?,?,?)',
                       (identifier, page, name.strip(), status, risk, note))
            result = dict(db.execute('SELECT * FROM records WHERE id=?', (identifier,)).fetchone())
        return result
