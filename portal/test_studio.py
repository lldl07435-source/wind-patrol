import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from . import data
from .studio_store import Studio, calibration
import workspace_adapter as adapter


class StudioApiTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.override = override_settings(DATA_ROOT=Path(self.temp.name))
        self.override.enable()
        self.user = get_user_model().objects.create_user('studio_a', password='Local-Audit-2026!x')
        self.other = get_user_model().objects.create_user('studio_b', password='Local-Audit-2026!y')
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.csrf = self.client.get('/api/account').json()['csrf']
        self.boot = self.client.get('/api/studio/bootstrap').json()
        self.cfg = self.boot['presets'][0]['config']
        if self.boot['domain'] == 'ld':
            self.cfg.update(count=4, speed=10)
        else:
            self.cfg['duration'] = 2

    def tearDown(self):
        data.close_all()
        self.override.disable()
        self.temp.cleanup()

    def post(self, route, raw):
        return self.client.post('/api/'+route, json.dumps(raw), content_type='application/json', HTTP_X_CSRFTOKEN=self.csrf)

    def plan(self):
        r = self.post('studio/plans', dict(name='可复现实验', objective='检查运行结果与参数和数据的对应关系', config=self.cfg))
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def device(self):
        r = self.post('studio/devices', dict(name='现场设备', model='STM32', interface='serial'))
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def ready(self, p):
        r = self.post('studio/plans/'+p['id']+'/ready', dict(version=p['version'], confirmed=True))
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_auth_csrf_and_static_entry(self):
        self.assertEqual(Client().get('/api/studio/bootstrap').status_code, 401)
        self.assertEqual(Client().get('/').status_code, 302)
        self.assertEqual(self.client.post('/api/studio/plans','{}',content_type='application/json').status_code, 403)
        for path in ('/', '/classic.html', '/studio.css', '/studio.js', '/lucide.js'):
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertContains(self.client.get('/'), '实验工作区')

    def test_plan_persists_and_events_keep_actual_time(self):
        p = self.plan()
        data.close_all()
        r = self.client.get('/api/studio/plans/'+p['id']).json()
        self.assertEqual(r['plan']['config'], self.cfg)
        self.assertEqual(len(r['events']), 1)
        self.assertIn('T', r['events'][0]['time'])

    def test_confirm_required(self):
        p = self.plan()
        r = self.post('studio/plans/'+p['id']+'/ready', dict(version=1, confirmed=False))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get('/api/studio/plans/'+p['id']).json()['plan']['state'], 'draft')

    def test_stale_version_rejected(self):
        p = self.plan(); self.ready(p)
        self.assertEqual(self.post('studio/plans/'+p['id']+'/ready', dict(version=1,confirmed=True)).status_code, 409)

    def test_no_run_before_ready(self):
        p = self.plan()
        self.assertEqual(self.post('studio/plans/'+p['id']+'/start',dict(version=1)).status_code, 409)

    def test_start_binds_real_run_and_reconciles(self):
        p = self.ready(self.plan())
        r = self.post('studio/plans/'+p['id']+'/start',dict(version=p['version']))
        self.assertEqual(r.status_code, 200, r.content)
        ctx = data.context(self.user)
        if self.boot['domain'] == 'ld':
            ctx.engine.worker.join(timeout=10)
        saved = self.client.get('/api/studio/plans/'+p['id']).json()['plan']
        self.assertEqual(saved['state'], 'review')
        self.assertTrue(saved['run_id'])
        self.assertIn(dict(kind='run',id=saved['run_id']), saved['references'])
        self.assertEqual(self.post('studio/plans/'+p['id']+'/start',dict(version=saved['version'])).status_code,409)

    def test_dispatch_failure_returns_to_ready(self):
        p = self.ready(self.plan())
        with patch.object(adapter, 'handle', wraps=adapter.handle) as handler:
            original=adapter.handle
            def fail(request, route, raw):
                if route in ('start','run'):
                    raise RuntimeError('测试计算槽占用')
                # 已持有真实函数，避免 mock 自身递归。
                return handler._mock_wraps(request,route,raw)
            handler.side_effect=fail
            self.assertEqual(self.post('studio/plans/'+p['id']+'/start',dict(version=p['version'])).status_code,409)
        item=self.client.get('/api/studio/plans/'+p['id']).json()
        self.assertEqual(item['plan']['state'],'ready')
        self.assertEqual(item['events'][0]['action'],'run_failed')

    def test_review_requires_result_and_substantive_conclusion(self):
        p=self.plan()
        self.assertEqual(self.post('studio/plans/'+p['id']+'/complete',dict(version=1,conclusion='空结论')).status_code,400)

    def test_archive_restore_keeps_original_and_version(self):
        p=self.plan()
        r=self.post('studio/plans/'+p['id']+'/archive',dict(version=1,archived=True)).json()
        self.assertTrue(r['archived'])
        restored=self.post('studio/plans/'+p['id']+'/archive',dict(version=r['version'],archived=False)).json()
        self.assertEqual(restored['objective'],p['objective'])
        self.assertEqual(restored['version'],3)

    def test_cross_account_read_write_download_search_favorite(self):
        p=self.plan();d=self.device()
        self.client.force_login(self.other)
        for route in ('studio/plans/'+p['id'],'studio/plans/'+p['id']+'/download'):
            self.assertEqual(self.client.get('/api/'+route).status_code,404)
        self.assertEqual(self.client.get('/api/studio/search').json(),[])
        self.assertEqual(self.post('studio/plans/'+p['id']+'/ready',dict(version=1,confirmed=True)).status_code,404)
        self.assertEqual(self.post('studio/devices/'+d['id']+'/calibrate',dict(version=1)).status_code,404)
        self.assertEqual(self.post('studio/favorite',dict(kind='plan',id=p['id'])).status_code,404)

    def test_cross_account_device_link_rejected(self):
        d=self.device();self.client.force_login(self.other)
        r=self.post('studio/plans',dict(name='不能关联',objective='不能关联其他账户设备',config=self.cfg,device_id=d['id']))
        self.assertEqual(r.status_code,404)

    def test_bad_params_rejected_without_record(self):
        bad=dict(self.cfg)
        bad['seed']=True
        self.assertEqual(self.post('studio/plans',dict(name='坏参数',objective='检查参数',config=bad)).status_code,400)
        self.assertEqual(self.client.get('/api/studio/bootstrap').json()['plans'],[])

    def test_recipe_validation_and_persistence(self):
        r=self.post('studio/recipes',dict(name='常用参数',config=self.cfg))
        self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(self.client.get('/api/studio/bootstrap').json()['recipes'][0]['config'],self.cfg)

    def test_calibration_error_units_and_source(self):
        d=self.device()
        r=self.post('studio/devices/'+d['id']+'/calibrate',dict(version=1,label='通行周期',unit='s',reference=1,observed=1.1,tolerance=.05,source='demo',expires='2026-01-01'))
        self.assertEqual(r.status_code,200,r.content)
        c=r.json()['calibrations'][0]
        self.assertAlmostEqual(c['error'],.1)
        self.assertFalse(c['passed'])
        self.assertEqual(c['source'],'demo')
        notices=self.client.get('/api/studio/bootstrap').json()['notices']
        self.assertEqual(len(notices),1)

    def test_bad_calibration_is_atomic(self):
        d=self.device()
        self.assertEqual(self.post('studio/devices/'+d['id']+'/calibrate',dict(version=1,label='项目',unit='s',reference=1,observed=True,tolerance=1)).status_code,400)
        self.assertEqual(self.client.get('/api/studio/bootstrap').json()['devices'][0]['calibrations'],[])

    def test_preferences_private_and_survive_context_reload(self):
        self.assertEqual(self.post('studio/preferences',dict(theme='dark',density='compact')).status_code,200)
        data.close_all()
        self.assertEqual(self.client.get('/api/studio/bootstrap').json()['preferences']['theme'],'dark')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/api/studio/bootstrap').json()['preferences']['theme'],'light')

    def test_favorite_toggle_and_search(self):
        p=self.plan()
        r=self.post('studio/favorite',dict(kind='plan',id=p['id']))
        self.assertIn('plan:'+p['id'],r.json()['favorites'])
        self.assertEqual(len(self.client.get('/api/studio/search?q=可复现').json()),1)
        self.assertEqual(self.post('studio/favorite',dict(kind='plan',id=p['id'])).json()['favorites'],[])

    def test_concurrent_favorites_keep_both_changes(self):
        from concurrent.futures import ThreadPoolExecutor
        store=Studio(data.context(self.user).root)
        def add(identity):
            store.preferences(lambda pref: pref['favorites'].append(identity))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(add, ['plan:a','plan:b']))
        self.assertEqual(set(store.preferences()['favorites']), {'plan:a','plan:b'})

    def test_unbound_dispatch_enters_review_after_timeout(self):
        p=self.ready(self.plan());store=Studio(data.context(self.user).root)
        store.update('plans',p['id'],p['version'],'run_requested',lambda item:item.update(state='running'))
        with store.db() as db:
            row=db.execute('SELECT payload FROM records WHERE id=?',(p['id'],)).fetchone()
            raw=json.loads(row[0]);raw['updated']='2026-01-01T00:00:00+00:00'
            db.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(raw),p['id']))
        current=self.client.get('/api/studio/plans/'+p['id']).json()['plan']
        self.assertEqual(current['state'],'review')
        self.assertEqual(current['run_status'],'unresolved')
        self.assertEqual(self.post('studio/plans/'+p['id']+'/start',dict(version=current['version'])).status_code,409)

    def test_profile_updates_only_current_user(self):
        r=self.post('account/profile',dict(display_name='实验成员',email='local@example.com'))
        self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(r.json()['user']['display_name'],'实验成员')
        self.other.refresh_from_db()
        self.assertEqual(self.other.first_name,'')

    def test_report_package_hashes_and_isolation(self):
        p=self.plan()
        response=self.client.get('/api/studio/plans/'+p['id']+'/download')
        self.assertEqual(response.status_code,200,response.content)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            for name,digest in manifest.items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),digest)
            self.assertEqual(json.loads(archive.read('experiment.json'))['name'],p['name'])
            self.assertFalse(any('.portal-secret' in name or 'accounts.sqlite3' in name for name in archive.namelist()))

    def test_native_run_archive_package(self):
        p=self.ready(self.plan())
        r=self.post('studio/plans/'+p['id']+'/start',dict(version=p['version'])).json()
        if self.boot['domain']=='ld':data.context(self.user).engine.worker.join(timeout=10)
        p=self.client.get('/api/studio/plans/'+p['id']).json()['plan']
        r=self.post('studio/plans/'+p['id']+'/complete',dict(version=p['version'],conclusion='根据真实运行结果核对参数，当前结果符合本次实验目的。'))
        self.assertEqual(r.status_code,200,r.content)
        response=self.client.get('/api/studio/plans/'+p['id']+'/download')
        self.assertEqual(response.status_code,200,response.content)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertTrue(any(name.startswith('runs/') for name in archive.namelist()))
