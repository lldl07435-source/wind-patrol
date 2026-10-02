import atexit
import io
import sqlite3
import threading
import time
import zipfile
from pathlib import Path
from django.conf import settings
from .models import Workspace
import workspace_adapter as adapter

_contexts = {}
_lock = threading.RLock()
compute_slots = threading.BoundedSemaphore(2)

def workspace(user):
    record, _ = Workspace.objects.get_or_create(user=user)
    root = settings.DATA_ROOT / 'users' / record.storage_key.hex
    root.mkdir(parents=True, exist_ok=True)
    return root

def context(user):
    root = workspace(user)
    with _lock:
        now = time.monotonic()
        for key, (instance, used) in list(_contexts.items()):
            if now - used > 1800 and not instance.busy():
                instance.close()
                del _contexts[key]
        if root not in _contexts:
            if len(_contexts) >= 12:
                idle = next((key for key, (item, _) in _contexts.items() if not item.busy()), None)
                if idle is None:
                    raise RuntimeError('工作区繁忙，请稍后再试')
                _contexts.pop(idle)[0].close()
            _contexts[root] = (adapter.Context(root), now)
        item = _contexts[root][0]
        _contexts[root] = (item, now)
        return item

def close_all():
    with _lock:
        for item, _ in _contexts.values():
            item.close()
        _contexts.clear()

atexit.register(close_all)

def usage(root):
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink())

def check_quota(ctx, extra_records=1):
    if usage(ctx.root) >= settings.MAX_WORKSPACE_BYTES:
        raise ValueError('个人工作区已达到容量上限，请联系站点管理员扩容')
    if ctx.record_count() + extra_records > settings.MAX_ACCOUNT_RECORDS:
        raise ValueError('个人记录数量已达到上限，请联系站点管理员')

def archive(root):
    # SQLite backup 获得一致快照；不把正被写入的数据库文件直接压缩。
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(root.rglob('*')):
            if not path.is_file() or path.is_symlink() or path.name.startswith('.') or path.suffix in ('.lock', '.pid') or path.name.endswith(('-wal', '-shm', '-journal')):
                continue
            if path.suffix == '.sqlite3':
                source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                target = sqlite3.connect(':memory:')
                try:
                    source.backup(target)
                    bundle.writestr(path.relative_to(root).as_posix(), target.serialize())
                finally:
                    source.close()
                    target.close()
            else:
                bundle.write(path, path.relative_to(root).as_posix())
    return output.getvalue()
