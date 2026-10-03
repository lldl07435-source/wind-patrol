import hashlib
import ipaddress
import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from .models import AuditEvent, RateBucket, Workspace
from . import data
import workspace_adapter as adapter

logger = logging.getLogger('portal')

def respond(payload, status=200):
    return JsonResponse(payload, safe=not isinstance(payload, list), status=status,
                        json_dumps_params={'ensure_ascii': False, 'allow_nan': False})

def csrf_failure(request, reason=''):
    return respond({'error': '页面会话已变化，请刷新后再提交'}, 403)

def body(request):
    if request.content_type != 'application/json':
        raise ValueError('请使用 JSON 请求')
    if len(request.body) > settings.DATA_UPLOAD_MAX_MEMORY_SIZE:
        raise ValueError('请求超过容量限制')
    result = json.loads(request.body)
    if not isinstance(result, dict):
        raise ValueError('请求应为一个对象')
    return result

def audit(user, action, target=''):
    AuditEvent.objects.create(user=user if user and user.is_authenticated else None, action=action, target=str(target)[:100])
    logger.info('操作=%s 用户=%s 对象=%s', action, user.pk if user and user.is_authenticated else '-', str(target)[:100])

def limited(request, action, maximum, seconds, subject=''):
    # 仅使用已配置并由代理覆盖的单地址头，不解析可伪造的地址链。
    now = int(time.time())
    fingerprint = request.META.get('REMOTE_ADDR', '') if not subject else subject
    if not subject and settings.CLIENT_IP_HEADER:
        value = request.headers.get(settings.CLIENT_IP_HEADER, '')
        try:
            fingerprint = str(ipaddress.ip_address(value))
        except ValueError:
            pass
    key = hashlib.sha256(f'{action}:{fingerprint}:{now // seconds}'.encode()).hexdigest()
    with transaction.atomic():
        RateBucket.objects.filter(expires_at__lt=now).delete()
        bucket, _ = RateBucket.objects.get_or_create(key=key, defaults={'expires_at': now + seconds})
        if bucket.count >= maximum:
            return True
        bucket.count += 1
        bucket.save(update_fields=['count'])
    return False

def profile(request):
    user = request.user
    return {'user': {'username': user.username, 'display_name': user.first_name or user.username,
                     'operator': user.is_staff, 'email': user.email} if user.is_authenticated else None,
            'csrf': get_token(request), 'software': adapter.TITLE, 'version': adapter.VERSION,
            'mode': settings.DEPLOYMENT_MODE, 'registration': True}

def accounts(request, operation=''):
    if not operation and request.method == 'GET':
        return respond(profile(request))
    if request.method != 'POST':
        return respond({'error': '请求方法不支持'}, 405)
    try:
        raw = body(request)
        User = get_user_model()
        if operation in ('register', 'login'):
            if limited(request, operation, 10 if operation == 'register' else 25, 3600 if operation == 'register' else 900):
                return respond({'error': '尝试次数较多，请稍后再试'}, 429)
            username = raw.get('username', '')
            password = raw.get('password', '')
            if not isinstance(username, str) or not isinstance(password, str) or len(password) > 128:
                raise ValueError('账户信息格式不正确')
            username = username.strip().lower()
            if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,31}', username):
                raise ValueError('用户名为3至32位字母、数字、下划线或短横线')
            if operation == 'register':
                email = raw.get('email', '')
                display = raw.get('display_name', username)
                if not isinstance(email, str) or len(email) > 254 or not isinstance(display, str) or not 1 <= len(display.strip()) <= 40:
                    raise ValueError('邮箱或显示名称格式不正确')
                if email:
                    validate_email(email)
                user = User(username=username, first_name=display.strip(), email=email.strip())
                validate_password(password, user)
                try:
                    with transaction.atomic():
                        user.set_password(password)
                        user.save()
                        Workspace.objects.create(user=user)
                except IntegrityError:
                    return respond({'error': '该用户名已被使用'}, 409)
            else:
                if limited(request, 'login-user', 12, 900, username):
                    return respond({'error': '尝试次数较多，请稍后再试'}, 429)
                user = authenticate(request, username=username, password=password)
                if user is None:
                    audit(None, 'login_rejected')
                    return respond({'error': '用户名或密码不正确'}, 401)
            login(request, user)
            audit(user, operation)
            return respond(profile(request), 201 if operation == 'register' else 200)
        if not request.user.is_authenticated:
            return respond({'error': '请先登录'}, 401)
        if operation == 'logout':
            adapter.release_user(request.user)
            audit(request.user, 'logout')
            logout(request)
            return respond(profile(request))
        if operation == 'profile':
            display, email = raw.get('display_name', ''), raw.get('email', '')
            if not isinstance(display, str) or not 1 <= len(display.strip()) <= 40 or not isinstance(email, str) or len(email) > 254:
                raise ValueError('显示名称或邮箱格式不正确')
            if email:
                validate_email(email)
            request.user.first_name = display.strip()
            request.user.email = email.strip()
            request.user.save(update_fields=['first_name', 'email'])
            audit(request.user, 'profile_updated')
            return respond(profile(request))
        if operation == 'password':
            current, new = raw.get('current_password', ''), raw.get('new_password', '')
            if not isinstance(current, str) or not isinstance(new, str) or len(current) > 128 or len(new) > 128:
                raise ValueError('密码格式不正确')
            if limited(request, 'password', 8, 900, str(request.user.pk)):
                return respond({'error': '尝试次数较多，请稍后再试'}, 429)
            if not request.user.check_password(current):
                return respond({'error': '当前密码不正确'}, 400)
            validate_password(new, request.user)
            request.user.set_password(new)
            request.user.save(update_fields=['password'])
            update_session_auth_hash(request, request.user)
            audit(request.user, 'password_changed')
            return respond(profile(request))
        return respond({'error': '账户接口不存在'}, 404)
    except ValidationError as exc:
        return respond({'error': '；'.join(exc.messages)}, 400)
    except (ValueError, TypeError, UnicodeError) as exc:
        return respond({'error': str(exc)}, 400)

def account_data(request, operation=''):
    if not request.user.is_authenticated:
        return respond({'error': '请先登录'}, 401)
    if request.method != 'GET':
        return respond({'error': '请求方法不支持'}, 405)
    try:
        ctx = data.context(request.user)
    except RuntimeError as exc:
        return respond({'error': str(exc)}, 409)
    if operation == 'export':
        if limited(request, 'export', 5, 600, str(request.user.pk)):
            return respond({'error': '导出频繁，请稍后再试'}, 429)
        if ctx.busy():
            return respond({'error': '请等待当前运行结束后导出完整工作区'}, 409)
        audit(request.user, 'workspace_export')
        response = HttpResponse(data.archive(ctx.root), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="my-workspace.zip"'
        return response
    info = ctx.overview(request)
    info.update(bytes_used=data.usage(ctx.root), bytes_limit=settings.MAX_WORKSPACE_BYTES,
                record_limit=settings.MAX_ACCOUNT_RECORDS,
                audit=[{'action': r.action, 'target': r.target, 'time': r.created_at.isoformat()}
                       for r in AuditEvent.objects.filter(user=request.user).order_by('-id')[:30]])
    return respond(info)

def api(request, route):
    if not request.user.is_authenticated:
        return respond({'error': '请先登录'}, 401)
    try:
        raw = body(request) if request.method == 'POST' else None
        if request.method not in ('GET', 'POST'):
            return respond({'error': '请求方法不支持'}, 405)
        result = adapter.handle(request, route, raw)
        if isinstance(result, HttpResponse):
            return result
        if request.method == 'POST':
            audit(request.user, route)
        return respond(result)
    except FileNotFoundError:
        return respond({'error': '记录不存在'}, 404)
    except KeyError:
        return respond({'error': '记录不存在或请求缺少必填项'}, 404)
    except PermissionError as exc:
        return respond({'error': str(exc)}, 403)
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        return respond({'error': str(exc)}, 400)
    except RuntimeError as exc:
        return respond({'error': str(exc)}, 409)
    except (OSError, sqlite3.Error, ImportError):
        logger.exception('工作区请求失败 route=%s user=%s', route, request.user.pk)
        return respond({'error': '操作未完成，请检查服务运行日志'}, 500)

def page(request, name=''):
    filename = 'index.html' if name == 'classic.html' else name or 'studio.html'
    allowed = {'login.html', 'account.css', 'account.js', 'data.html', 'session.js'} | set(adapter.STATIC_FILES)
    if filename == 'favicon.ico':
        return HttpResponse(status=204)
    if filename not in allowed:
        return respond({'error': '资源不存在'}, 404)
    if filename.endswith('.html') and filename != 'login.html' and not request.user.is_authenticated:
        return redirect('/login.html?next=' + request.path)
    if filename == 'login.html' and request.user.is_authenticated:
        return redirect('/')
    suffixes = {'.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css'}
    return HttpResponse((adapter.WEB_ROOT / filename).read_bytes(), content_type=suffixes[Path(filename).suffix] + '; charset=utf-8')

def health(request):
    if request.method != 'GET':
        return respond({'error': '请求方法不支持'}, 405)
    try:
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT 1 FROM portal_workspace LIMIT 1')
        adapter.health()
    except Exception:
        return respond({'status': 'unavailable'}, 503)
    return respond({'status': 'ok', 'version': adapter.VERSION})
