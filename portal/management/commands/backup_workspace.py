from datetime import datetime
import hashlib
import json
import sqlite3
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from portal.data import archive
from portal.process_lock import ProcessLock

class Command(BaseCommand):
    help = '停服后备份账户库和所有个人工作区'
    def add_arguments(self, parser):
        parser.add_argument('destination', type=Path)
    def handle(self, *args, **options):
        try:
            lock = ProcessLock(settings.DATA_ROOT)
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc
        try:
            target = options['destination'] / datetime.now().astimezone().strftime('backup_%Y%m%d_%H%M%S')
            target.mkdir(parents=True, exist_ok=False)
            source = sqlite3.connect((settings.DATA_ROOT / 'accounts.sqlite3').as_uri() + '?mode=ro', uri=True)
            dest = sqlite3.connect(target / 'accounts.sqlite3')
            try:
                source.backup(dest)
            finally:
                source.close()
                dest.close()
            users = settings.DATA_ROOT / 'users'
            if users.exists():
                for root in users.iterdir():
                    if root.is_dir() and not root.is_symlink():
                        (target / (root.name + '.zip')).write_bytes(archive(root))
            key = settings.DATA_ROOT / '.portal-secret'
            if key.exists():
                (target / '.portal-secret').write_bytes(key.read_bytes())
            manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir() if p.is_file()}
            (target / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            self.stdout.write(str(target))
        finally:
            lock.close()
