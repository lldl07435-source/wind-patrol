import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from portal.data import workspace
from portal.process_lock import ProcessLock
from portal.views import audit
import workspace_adapter as adapter

class Command(BaseCommand):
    help = '停服后，把旧的单用户记录复制到指定空账户，原始目录保留'
    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--source', type=Path, default=adapter.DEFAULT_DATA_ROOT)
    def handle(self, *args, **options):
        lock = None
        try:
            lock = ProcessLock(settings.DATA_ROOT)
            user = get_user_model().objects.get(username=options['username'].lower())
            root = workspace(user)
            source = options['source'].resolve()
            if source == root or source in root.parents or root in source.parents:
                if source != settings.DATA_ROOT:
                    raise CommandError('来源与目标目录存在包含关系，请核对路径')
            ctx = adapter.Context(root)
            if ctx.record_count() or any(root.glob('legacy-import*.json')):
                raise CommandError('目标账户已有运行或导入记录，请选空账户')
            if adapter.has_business_data(ctx):
                raise CommandError('目标账户已有业务数据，请选空账户')
            ctx.close()
            stamp = datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')
            staging = settings.DATA_ROOT / 'imports' / ('pending_' + stamp + '_' + user.username)
            staging.mkdir(parents=True, exist_ok=False)
            manifest = {'time': datetime.now().astimezone().isoformat(), 'username': user.username, 'files': {}}
            for name in adapter.LEGACY_NAMES:
                path = source / name
                if not path.exists():
                    continue
                if path.is_symlink() or (path.is_dir() and any(p.is_symlink() for p in path.rglob('*'))):
                    raise CommandError('导入不接受符号链接')
                destination = staging / name
                if path.is_dir():
                    shutil.copytree(path, destination, ignore=shutil.ignore_patterns('*.lock', '*.pid', '*-wal', '*-shm', '*-journal'))
                elif path.suffix == '.sqlite3':
                    src = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                    dst = sqlite3.connect(destination)
                    try:
                        src.backup(dst)
                    finally:
                        src.close()
                        dst.close()
                else:
                    shutil.copy2(path, destination)
            if not any(staging.iterdir()):
                raise CommandError('来源目录没有可导入的旧数据')
            for path in staging.rglob('*'):
                if path.is_file():
                    manifest['files'][path.relative_to(staging).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            (staging / ('legacy-import_' + stamp + '.json')).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            backup = settings.DATA_ROOT / 'imports' / ('empty_workspace_' + stamp + '_' + user.username)
            root.rename(backup)
            try:
                staging.rename(root)
            except OSError:
                backup.rename(root)
                raise
            audit(user, 'legacy_import')
            self.stdout.write(self.style.SUCCESS('旧数据已复制到此账户，原始目录和空工作区备份均保留。'))
        except (get_user_model().DoesNotExist, RuntimeError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        finally:
            if lock:
                lock.close()
