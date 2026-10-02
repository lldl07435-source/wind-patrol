import os
import sys
import subprocess

os.environ.setdefault('LD_MODE', 'cloud')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portal.settings')
from django.conf import settings
if settings.DEPLOYMENT_MODE != 'cloud':
    raise SystemExit('生产入口需要 LD_MODE=cloud')
from portal.process_lock import ProcessLock
lock = ProcessLock(settings.DATA_ROOT)
try:
    subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], check=True)
    subprocess.run([sys.executable, 'manage.py', 'check', '--deploy', '--fail-level', 'WARNING'], check=True)
    import workspace_adapter
    workspace_adapter.health()
finally:
    lock.close()
port = os.environ.get('PORT', '8000')
if not port.isdigit() or not 1024 <= int(port) <= 65535:
    raise SystemExit('PORT 格式错误')
os.execv(sys.executable, [sys.executable, '-m', 'gunicorn', 'portal.wsgi:application',
    '--bind', '0.0.0.0:' + port, '--workers', '1', '--threads', '6', '--timeout', '120',
    '--max-requests', '0', '--access-logfile', '-', '--error-logfile', '-',
    '--limit-request-line', '4094', '--limit-request-fields', '50'])
