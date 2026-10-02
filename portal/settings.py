import os
import secrets
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
import workspace_adapter as adapter

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get('LD_DATA_ROOT', adapter.DEFAULT_DATA_ROOT)).resolve()
DATA_ROOT.mkdir(parents=True, exist_ok=True)
DEPLOYMENT_MODE = os.environ.get('LD_MODE', 'local')
if DEPLOYMENT_MODE not in ('local', 'cloud'):
    raise ImproperlyConfigured('LD_MODE 必须为 local 或 cloud')
DEBUG = False
SECRET_KEY = os.environ.get('LD_SECRET_KEY', '')
if DEPLOYMENT_MODE == 'cloud' and len(SECRET_KEY) < 50:
    raise ImproperlyConfigured('云端必须设置至少50字符的 LD_SECRET_KEY')
if not SECRET_KEY:
    # 本机密钥只生成一次，重启后现有会话仍能校验。
    key_file = DATA_ROOT / '.portal-secret'
    try:
        with key_file.open('x', encoding='ascii') as stream:
            stream.write(secrets.token_urlsafe(48))
        key_file.chmod(0o600)
    except FileExistsError:
        pass
    SECRET_KEY = key_file.read_text(encoding='ascii').strip()
ALLOWED_HOSTS = [s.strip() for s in os.environ.get('LD_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if s.strip()]
if '*' in ALLOWED_HOSTS or not ALLOWED_HOSTS:
    raise ImproperlyConfigured('必须指定实际域名，禁止通配 Host')
CSRF_TRUSTED_ORIGINS = [s.strip() for s in os.environ.get('LD_CSRF_ORIGINS', '').split(',') if s.strip()]
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'portal']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'portal.middleware.Guard',
    'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'portal.urls'
WSGI_APPLICATION = 'portal.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': DATA_ROOT / 'accounts.sqlite3',
    'OPTIONS': {'timeout': 20, 'transaction_mode': 'IMMEDIATE'}}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
SESSION_COOKIE_NAME = adapter.COOKIE_NAME
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = DEPLOYMENT_MODE == 'cloud'
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_NAME = adapter.COOKIE_NAME + '_csrf'
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_FAILURE_VIEW = 'portal.views.csrf_failure'
SECURE_SSL_REDIRECT = DEPLOYMENT_MODE == 'cloud'
SECURE_REDIRECT_EXEMPT = [r'^healthz$']
SECURE_HSTS_SECONDS = 31536000 if DEPLOYMENT_MODE == 'cloud' else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = DEPLOYMENT_MODE == 'cloud'
SECURE_HSTS_PRELOAD = DEPLOYMENT_MODE == 'cloud'
# 只有由可信反向代理剥除并重新写入此头时才启用。
if os.environ.get('LD_TRUST_PROXY') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CLIENT_IP_HEADER = os.environ.get('LD_CLIENT_IP_HEADER', '') if os.environ.get('LD_TRUST_PROXY') == '1' else ''
if CLIENT_IP_HEADER not in ('', 'X-Real-IP', 'CF-Connecting-IP'):
    raise ImproperlyConfigured('客户端IP头必须由可信代理覆盖写入')
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 30
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_TZ = True
MAX_WORKSPACE_BYTES = int(os.environ.get('LD_WORKSPACE_MB', '100')) * 1024 * 1024
MAX_ACCOUNT_RECORDS = int(os.environ.get('LD_MAX_RECORDS', '500'))
LOGGING = {'version': 1, 'disable_existing_loggers': False,
    'formatters': {'plain': {'format': '{asctime} {levelname} {message}', 'style': '{'}},
    'handlers': {'file': {'class': 'logging.handlers.RotatingFileHandler',
        'filename': DATA_ROOT / '运行日志.log', 'maxBytes': 2000000, 'backupCount': 5,
        'encoding': 'utf-8', 'formatter': 'plain'}},
    'loggers': {'portal': {'handlers': ['file'], 'level': 'INFO', 'propagate': False},
        'django.security': {'handlers': ['file'], 'level': 'WARNING', 'propagate': False}}}
