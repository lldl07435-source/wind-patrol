import os
from pathlib import Path
import stat
import sys

UID = GID = 10001

def prepare_data():
    if os.name != 'posix':
        raise RuntimeError('此入口用于 Linux 容器，本机请运行 app.py')
    root = Path(os.environ.get('LD_DATA_ROOT', '/var/data'))
    if str(root) != '/var/data' or root.resolve() != root:
        raise RuntimeError('容器持久目录必须为 /var/data，且不能是符号链接')
    root.mkdir(mode=0o750, parents=True, exist_ok=True)
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise RuntimeError('持久目录不是普通目录')
    if os.geteuid() == 0:
        # 新挂载的磁盘可能属于 root；只整理这个数据卷。
        os.chown(root, UID, GID, follow_symlinks=False)
        os.chmod(root, 0o750)
        for base, directories, files in os.walk(root, followlinks=False):
            directories[:] = [name for name in directories if not (Path(base) / name).is_symlink()]
            for name in directories + files:
                item = Path(base) / name
                info = item.lstat()
                if stat.S_ISLNK(info.st_mode):
                    continue
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    raise RuntimeError('数据卷包含非普通文件，请先检查')
                if info.st_uid != UID or info.st_gid != GID:
                    os.chown(item, UID, GID, follow_symlinks=False)
        os.setgroups([])
        os.setgid(GID)
        os.setuid(UID)
    if os.geteuid() != UID or os.getegid() != GID:
        raise RuntimeError('服务必须以 uid/gid 10001 运行')
    os.umask(0o077)

def main():
    prepare_data()
    command = sys.argv[1:] or [sys.executable, 'serve_cloud.py']
    os.execvp(command[0], command)

if __name__ == '__main__':
    main()
