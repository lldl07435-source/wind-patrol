import argparse
import atexit
import os
import sys
import webbrowser

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=None)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--output', '--data-root', dest='data_root')
    args = parser.parse_args()
    if args.data_root:
        os.environ['LD_DATA_ROOT'] = args.data_root
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portal.settings')
    from django.conf import settings
    import workspace_adapter as adapter
    if settings.DEPLOYMENT_MODE != 'local':
        parser.error('云端请使用部署脚本和生产服务启动，不使用本机启动器')
    from portal.process_lock import ProcessLock
    lock = ProcessLock(settings.DATA_ROOT)
    atexit.register(lock.close)
    import django
    django.setup()
    from django.core.management import call_command
    from portal.wsgi import application
    from portal.data import close_all
    from waitress import serve
    call_command('migrate', interactive=False, verbosity=0)
    port = args.port or adapter.DEFAULT_PORT
    if not 1024 <= port <= 65535:
        parser.error('端口必须在1024至65535之间')
    adapter.health()
    url = f'http://127.0.0.1:{port}'
    print(f'{adapter.TITLE} V{adapter.VERSION}\n打开 {url}\n数据目录：{settings.DATA_ROOT}\n保持窗口打开，Ctrl+C 停止。', flush=True)
    if not args.no_browser:
        import threading
        threading.Timer(1, lambda: webbrowser.open(url)).start()
    try:
        serve(application, host='127.0.0.1', port=port, threads=6, max_request_body_size=1024 * 1024, channel_timeout=30)
    except KeyboardInterrupt:
        pass
    finally:
        close_all()
        lock.close()
    return 0

if __name__ == '__main__':
    sys.exit(main())
