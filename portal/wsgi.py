import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portal.settings')
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
from django.conf import settings
if settings.DEPLOYMENT_MODE == 'cloud':
    import atexit
    from .process_lock import ProcessLock
    _lock = ProcessLock(settings.DATA_ROOT)
    atexit.register(_lock.close)
