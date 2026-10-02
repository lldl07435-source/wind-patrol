import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
if os.environ.get('LD_MODE', 'local') != 'local':
    raise SystemExit('此工具只用于本机账户设置')
username = input('先在网页注册、停止服务，再输入你的用户名：').strip().lower()
if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,31}', username):
    raise SystemExit('用户名格式不正确')
env = {**os.environ, 'PYTHONUTF8': '1'}
result = subprocess.run([sys.executable, 'manage.py', 'import_legacy', username], cwd=ROOT, env=env)
if (ROOT / 'ldcell').is_dir():
    operator = subprocess.run([sys.executable, 'manage.py', 'grant_operator', username], cwd=ROOT, env=env)
    if operator.returncode:
        raise SystemExit(operator.returncode)
print('重新启动软件，以此账户登录即可查看自己的工作区。')
raise SystemExit(result.returncode)
