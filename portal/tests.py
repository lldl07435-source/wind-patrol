import io
import json
import tempfile
import zipfile
import unittest
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase, override_settings
from .models import AuditEvent, RateBucket
from . import data
import workspace_adapter as adapter

PASSWORD = 'Wind-Ld-Experiment-74!'
IS_LD = adapter.COOKIE_NAME == 'ldflex_session'

class AccountTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.override = override_settings(DATA_ROOT=Path(self.temp.name))
        self.override.enable()
        self.client = Client(enforce_csrf_checks=True)
    def tearDown(self):
        data.close_all()
        self.override.disable()
        self.temp.cleanup()
    def csrf(self, client=None):
        return (client or self.client).get('/api/account').json()['csrf']
    def post(self, path, payload, client=None, csrf=None, **headers):
        client = client or self.client
        return client.post(path, json.dumps(payload), content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf or self.csrf(client), **headers)
    def register(self, username='alice', client=None):
        return self.post('/api/account/register', {'username': username, 'password': PASSWORD, 'display_name': '实验同学'}, client)
    def make_record(self, username='alice'):
        user = get_user_model().objects.get(username=username)
        ctx = data.context(user)
        if IS_LD:
            from ldcell.storage import RunLog
            log = RunLog(ctx.root, {'scenario': 'normal', 'owner_check': username})
            log.event('acceptance', {'user': username})
            log.finish({'completed': 1, 'unknown': 0, 'scenario': 'normal'})
            return log.id
        from quadrotor_patrol_simulation import Config, run_simulation
        return ctx.repo.add('账户隔离验收-' + username, run_simulation(Config.from_dict({'duration': 6})))['id']
    def detail(self, key):
        return '/api/run?id=' + key if IS_LD else '/api/tasks/' + key
    def export(self, key):
        return '/api/export?id=' + key if IS_LD else '/api/tasks/' + key + '/download'

    def test_home_requires_login(self):
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertIn('/login.html', self.client.get('/')['Location'])
    def test_anonymous_cannot_read_business_data(self):
        routes = ['/api/state', '/api/history', '/api/ports', '/api/run?id=aaa'] if IS_LD else ['/api/tasks', '/api/workflow', '/api/comparisons', '/api/engineering/records']
        for route in routes:
            self.assertEqual(self.client.get(route).status_code, 401)
    def test_registration_login_and_logout(self):
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.client.get('/api/account').json()['user']['username'], 'alice')
        self.assertEqual(self.post('/api/account/logout', {}).status_code, 200)
        self.assertIsNone(self.client.get('/api/account').json()['user'])
        self.assertEqual(self.post('/api/account/login', {'username':'ALICE', 'password':PASSWORD}).status_code, 200)
    def test_password_is_hashed(self):
        self.register()
        user = get_user_model().objects.get(username='alice')
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))
    def test_duplicate_casefold_username(self):
        self.register()
        other = Client(enforce_csrf_checks=True)
        self.assertEqual(self.register('ALICE', other).status_code, 409)
    def test_weak_password_rejected(self):
        self.assertEqual(self.post('/api/account/register', {'username':'alice', 'password':'123456789012'}).status_code, 400)
        self.assertEqual(get_user_model().objects.count(), 0)
    def test_invalid_username_rejected(self):
        for username in ['../owner', 'a', 'a b c']:
            self.assertEqual(self.register(username).status_code, 400)
    def test_login_missing_csrf_rejected(self):
        response = self.client.post('/api/account/login', json.dumps({'username':'alice','password':PASSWORD}), content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertIn('error', response.json())
    def test_cross_site_login_rejected(self):
        self.assertEqual(self.post('/api/account/login', {}, HTTP_ORIGIN='https://evil.example').status_code, 403)
    def test_untrusted_host_rejected(self):
        self.assertEqual(self.client.get('/api/account', HTTP_HOST='evil.example').status_code, 403)
    def test_login_rotates_csrf(self):
        old = self.csrf()
        self.register()
        route = '/api/stop' if IS_LD else '/api/validate'
        self.assertEqual(self.post(route, {}, csrf=old).status_code, 403)
    def test_session_cookie_http_only(self):
        response = self.register()
        self.assertTrue(response.cookies[settings.SESSION_COOKIE_NAME]['httponly'])
        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME]['samesite'], 'Lax')
    def test_wrong_password_generic_response(self):
        self.register()
        other = Client(enforce_csrf_checks=True)
        response = self.post('/api/account/login', {'username':'alice','password':'wrong'}, other)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], '用户名或密码不正确')
    def test_rate_limit_survives_new_browser(self):
        for _ in range(12):
            self.post('/api/account/login', {'username':'alice','password':'wrong'})
        other = Client(enforce_csrf_checks=True)
        response = self.post('/api/account/login', {'username':'alice','password':'wrong'}, other)
        self.assertEqual(response.status_code, 429)
        self.assertGreater(RateBucket.objects.count(), 0)
    def test_unconfigured_proxy_ip_does_not_bypass_limit(self):
        from .views import limited
        factory = RequestFactory()
        with override_settings(CLIENT_IP_HEADER=''):
            first = factory.get('/', HTTP_X_REAL_IP='10.1.0.1')
            second = factory.get('/', HTTP_X_REAL_IP='10.1.0.2')
            self.assertFalse(limited(first, 'proxy-test', 1, 60))
            self.assertTrue(limited(second, 'proxy-test', 1, 60))
    def test_configured_proxy_separates_client_limits(self):
        from .views import limited
        factory = RequestFactory()
        with override_settings(CLIENT_IP_HEADER='X-Real-IP'):
            first = factory.get('/', HTTP_X_REAL_IP='10.1.0.1')
            second = factory.get('/', HTTP_X_REAL_IP='10.1.0.2')
            self.assertFalse(limited(first, 'proxy-test', 1, 60))
            self.assertFalse(limited(second, 'proxy-test', 1, 60))
    def test_two_accounts_have_separate_workspaces(self):
        self.register()
        other = Client(enforce_csrf_checks=True)
        self.register('bob', other)
        users = list(get_user_model().objects.order_by('username'))
        self.assertNotEqual(data.workspace(users[0]), data.workspace(users[1]))
        key = self.make_record()
        self.assertEqual(self.client.get(self.detail(key)).status_code, 200)
        self.assertEqual(other.get(self.detail(key)).status_code, 404)
    def test_other_account_cannot_download_known_id(self):
        self.register()
        key = self.make_record()
        other = Client(enforce_csrf_checks=True)
        self.register('bob', other)
        self.assertEqual(other.get(self.export(key)).status_code, 404)
        self.assertEqual(self.client.get(self.export(key)).status_code, 200)
    def test_other_account_cannot_see_counts(self):
        self.register()
        self.make_record()
        other = Client(enforce_csrf_checks=True)
        self.register('bob', other)
        self.assertEqual(other.get('/api/account/data').json()['total_records'], 0)
    def test_workspace_export_only_own_data(self):
        self.register()
        self.make_record()
        response = self.client.get('/api/account/export')
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertNotIn('accounts.sqlite3', archive.namelist())
            self.assertTrue(any(n.endswith('.sqlite3') for n in archive.namelist()))
    def test_password_change_invalidates_other_sessions(self):
        self.register()
        other = Client(enforce_csrf_checks=True)
        self.post('/api/account/login', {'username':'alice','password':PASSWORD}, other)
        response = self.post('/api/account/password', {'current_password':PASSWORD,'new_password':'Next-Ld-Experiment-81!'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(other.get('/api/account').json()['user'])
        self.assertIsNotNone(self.client.get('/api/account').json()['user'])
    def test_wrong_current_password_rejected(self):
        self.register()
        self.assertEqual(self.post('/api/account/password', {'current_password':'wrong','new_password':'Next-Ld-Experiment-81!'}).status_code, 400)
    def test_quota_is_enforced(self):
        self.register()
        ctx = data.context(get_user_model().objects.get(username='alice'))
        with override_settings(MAX_ACCOUNT_RECORDS=0):
            with self.assertRaises(ValueError):
                data.check_quota(ctx)
    def test_account_search_uses_own_records(self):
        self.register()
        key = self.make_record()
        self.assertEqual(self.client.get('/api/account/data?q=' + key).json()['matching'], 1)
        self.assertEqual(self.client.get('/api/account/data?q=no-such-task').json()['matching'], 0)
    def test_audit_contains_no_password(self):
        self.register()
        self.assertNotIn(PASSWORD, str(list(AuditEvent.objects.values())))
    def test_unknown_paths_and_traversal(self):
        self.register()
        self.assertEqual(self.client.get('/portal/settings.py').status_code, 404)
        self.assertNotEqual(self.client.get('/api/run?id=../accounts.sqlite3').status_code, 200)
    def test_invalid_json_rejected(self):
        self.register()
        route = '/api/stop' if IS_LD else '/api/validate'
        response = self.client.post(route, '[1]', content_type='application/json', HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(response.status_code, 400)
    def test_health_requires_migrations_and_kernel(self):
        self.assertEqual(self.client.get('/healthz').status_code, 200)
    @unittest.skipUnless(IS_LD, '实物接口属于 LD-Flex')
    def test_cloud_cookie_and_hardware_policy(self):
        self.register()
        if IS_LD:
            user = get_user_model().objects.get(username='alice');user.is_staff=True;user.save()
            with override_settings(DEPLOYMENT_MODE='cloud'):
                self.assertEqual(self.client.get('/api/ports').json(), [])
                self.assertEqual(self.post('/api/arm', {'confirmed':True}).status_code, 403)
    @unittest.skipUnless(IS_LD, '实物接口属于 LD-Flex')
    def test_operator_no_device_is_chinese_conflict(self):
        self.register()
        if IS_LD:
            user=get_user_model().objects.get(username='alice');user.is_staff=True;user.save()
            response=self.post('/api/arm', {'confirmed':True})
            self.assertEqual(response.status_code,409)
            self.assertIn('尚未连接',response.json()['error'])
    @unittest.skipUnless(IS_LD, '实物接口属于 LD-Flex')
    def test_ordinary_user_cannot_operate_hardware(self):
        self.register()
        if IS_LD:
            self.assertEqual(self.post('/api/connect', {'port':'COM4'}).status_code,403)
    def test_business_persists_after_context_restart(self):
        self.register()
        key=self.make_record()
        data.close_all()
        self.assertEqual(self.client.get(self.detail(key)).status_code,200)
    @unittest.skipUnless(not IS_LD, '巡检资产属于风巡智航')
    def test_foreign_asset_and_defect_denied(self):
        self.register()
        if not IS_LD:
            key=self.make_record()
            asset=self.post('/api/workflow/assets',{'code':'QA-001','name':'验收杆塔','location':'测试线路'}).json()
            other=Client(enforce_csrf_checks=True);self.register('bob',other)
            response=self.post('/api/workflow/defects',{'asset_id':asset['id'],'task_id':key,'title':'隔离测试','severity':'low','reason':'测试'},other)
            self.assertNotEqual(response.status_code,200)
            self.assertEqual(len(other.get('/api/workflow').json()['assets']),0)
