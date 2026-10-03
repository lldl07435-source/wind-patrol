import hashlib
import json
import math
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import Client,TestCase,override_settings
from . import data
import workspace_adapter as adapter

class TwinTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.settings=override_settings(DATA_ROOT=Path(self.temp.name));self.settings.enable()
        self.user=get_user_model().objects.create_user('twin_a',password='Actual-Test-2026!x')
        self.other=get_user_model().objects.create_user('twin_b',password='Actual-Test-2026!y')
        self.client=Client(enforce_csrf_checks=True);self.client.force_login(self.user)
        self.token=self.client.get('/api/account').json()['csrf'];self.ctx=data.context(self.user)
        boot=self.client.get('/api/studio/bootstrap').json();self.domain=boot['domain'];self.cfg=boot['presets'][0]['config']
        self.cfg.update(count=4,speed=10) if self.domain=='ld' else self.cfg.update(duration=2)
    def tearDown(self):
        data.close_all();self.settings.disable();self.temp.cleanup()
    def post(self,route,raw):
        return self.client.post('/api/'+route,json.dumps(raw),content_type='application/json',HTTP_X_CSRFTOKEN=self.token)
    def saved(self,scenario='normal',task_kind='belt'):
        if self.domain=='wind':
            from quadrotor_patrol_simulation import Config,run_simulation
            return self.ctx.repo.add('原始三维记录',run_simulation(Config.from_dict(self.cfg)))['id']
        from ldcell.simulation import Simulation,run_to_end
        from ldcell.storage import RunLog
        log=RunLog(self.ctx.root,{**self.cfg,'task_kind':task_kind,'scenario':scenario});s=Simulation(count=4,scenario=scenario,task_kind=task_kind,event=log.event)
        run_to_end(s);log.finish(s.summary(),s.rows);return log.id
    def test_replay_requires_login_and_own_account(self):
        key=self.saved();self.assertEqual(Client().get('/api/twin/runs/'+key).status_code,401)
        self.client.force_login(self.other);self.assertEqual(self.client.get('/api/twin/runs/'+key).status_code,404)
    def test_full_motion_and_final_status_preserved(self):
        key=self.saved();r=self.client.get('/api/twin/runs/'+key);self.assertEqual(r.status_code,200,r.content);p=r.json()
        self.assertFalse(p['live']);self.assertEqual(p['run_id'],key);self.assertEqual(p['source'],'simulation')
        self.assertEqual(p['frame_count'],len(p['frames']));self.assertTrue(p['frames'])
        self.assertEqual(p['frames'],sorted(p['frames'],key=lambda x:x['time_s']))
        if self.domain=='wind':
            raw=self.ctx.repo.get(key)['result']['samples'];self.assertEqual(len(raw),len(p['frames']))
            for raw_row,frame in zip(raw,p['frames']):self.assertEqual(frame['position'],[raw_row['x'],raw_row['y'],raw_row['z']])
        else:self.assertEqual(p['frames'][-1]['completed'],4);self.assertEqual(p['frames'][-1]['unknown'],0)
    def test_cursor_only_filters_returned_motion(self):
        key=self.saved();all_rows=self.client.get('/api/twin/runs/'+key).json();cut=all_rows['duration_s']/2
        sliced=self.client.get('/api/twin/runs/'+key+'?after='+str(cut)).json()
        self.assertEqual(sliced['frames'],[f for f in all_rows['frames'] if f['time_s']>cut]);self.assertEqual(sliced['frame_count'],all_rows['frame_count'])
    def test_invalid_cursor_and_write_method_rejected(self):
        self.assertEqual(self.client.get('/api/twin/live?after=NaN').status_code,400)
        self.assertEqual(self.client.get('/api/twin/live?after=-2').status_code,400)
        self.assertEqual(self.post('twin/live',{}).status_code,400)
    def test_download_is_full_even_with_cursor_and_hash_verifies(self):
        key=self.saved();r=self.client.get('/api/twin/runs/'+key+'/download?after=1');self.assertEqual(r.status_code,200,r.content)
        result=json.loads(r.content);p=result['replay'];canonical=json.dumps(p,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        self.assertEqual(result['sha256'],hashlib.sha256(canonical.encode()).hexdigest());self.assertEqual(len(p['frames']),p['frame_count'])
    def test_assets_are_local_and_imports_served(self):
        for file in ('twin.html','twin-viewer.js','twin-models.js','twin-timeline.js','twin-orbit.js','three.module.js','three.core.js','twin.css'):
            self.assertEqual(self.client.get('/'+file).status_code,200,file)
    def test_preferences_isolate_and_validate_hid_mapping(self):
        r=self.post('manual/preferences',dict(axes=[1,0,2,3],reverse=[True,False,False,True],model='hex',deadzone=.18));self.assertEqual(r.status_code,200,r.content)
        data.close_all();self.assertEqual(self.client.get('/api/manual/preferences').json()['axes'],[1,0,2,3])
        self.client.force_login(self.other);self.assertEqual(self.client.get('/api/manual/preferences').json()['axes'],[0,1,3,2])
        self.token=self.client.get('/api/account').json()['csrf'];self.assertEqual(self.post('manual/preferences',dict(axes=[-1,0,0,0],reverse=[False]*4)).status_code,400)
    def test_manual_requires_csrf(self):
        self.assertEqual(self.client.post('/api/manual/start',json.dumps({'config':self.cfg}),content_type='application/json').status_code,403)
    def test_manual_runtime_start_stop_and_sealed_replay(self):
        r=self.post('manual/start',{'config':self.cfg,'name':'手控验证','profile':'hex'});self.assertEqual(r.status_code,200,r.content)
        live=self.client.get('/api/twin/live').json();key=live['run_id'];self.assertTrue(key)
        if self.domain=='ld':
            self.assertEqual(self.post('manual/control',{'feed':True,'route':1}).status_code,200)
            self.assertEqual(self.post('manual/control',{'feed':True,'route':0}).status_code,409)
            time.sleep(.25)
        else:
            self.assertEqual(self.post('manual/control',{'axes':[0,0,1,0]}).status_code,200);time.sleep(.3)
        self.assertEqual(self.post('manual/stop',{}).status_code,200)
        if self.domain=='ld':self.ctx.engine.worker.join(timeout=5)
        p=self.client.get('/api/twin/runs/'+key).json();self.assertFalse(p['live']);self.assertTrue(p['frames'])
        self.assertEqual(p['summary']['control_mode'],'manual');self.assertEqual(self.client.get('/api/twin/runs/'+key+'/download').status_code,200)
        if self.domain=='wind':self.assertGreater(p['frames'][-1]['position'][2],0);self.assertEqual(self.client.get('/api/tasks/'+key+'/download').status_code,200)
    def test_manual_invalid_input_rejected(self):
        self.post('manual/start',{'config':self.cfg})
        values={'feed':True,'route':99} if self.domain=='ld' else {'axes':[0,0,2,0]}
        self.assertEqual(self.post('manual/control',values).status_code,400)
        if self.domain=='wind':self.assertEqual(self.post('manual/control',{'axes':[True,0,0,0]}).status_code,400)
        self.post('manual/stop',{})
    def test_domain_motion_boundaries(self):
        if self.domain=='ld':
            for kind in ('belt','color','size','weight','barcode','rework'):
                key=self.saved(task_kind=kind);p=self.client.get('/api/twin/runs/'+key).json();self.assertEqual(p['summary']['completed'],4)
                if kind=='barcode':self.assertEqual(p['frames'][-1]['bin_counts'],[1,1,1,1])
            p=self.client.get('/api/twin/runs/'+self.saved('jam')).json();self.assertEqual(p['summary']['unknown'],1)
            self.assertTrue(any(f['state']=='FAULT' for f in p['frames']));self.assertEqual(p['frames'][-1]['completed'],3)
        else:
            from .manual_simulation import ManualFlight
            from quadrotor_patrol_simulation import Config
            with patch.object(ManualFlight,'run'):
                released=[];flight=ManualFlight(self.ctx,Config.from_dict(self.cfg),'边界',lambda:released.append(True))
            flight.thread.join();flight.last_input=time.monotonic()-3;flight.advance();self.assertEqual(flight.status,'ABORTED')
            self.assertIn('输入超时',flight.events[-1]['detail'])
    def test_legacy_logs_do_not_invent_positions(self):
        if self.domain=='wind':
            key=self.saved();p=self.client.get('/api/twin/runs/'+key).json();self.assertEqual(p['fidelity'],'full_trajectory')
        else:
            from .twin import legacy_frames
            frames=legacy_frames([{'kind':'state','data':{'virtual_ms':100,'state':'TRANSIT','route':1,'inputs':4}}])
            self.assertIsNone(frames[0]['progress']);self.assertIsNone(frames[0]['order_id']);self.assertEqual(frames[0]['inputs'],4)
    def test_manual_flight_fence_battery_and_sensor_stop(self):
        if self.domain!='wind':self.skipTest('仅用于飞行手控')
        from .manual_simulation import ManualFlight
        from quadrotor_patrol_simulation import Config
        for kind in ('fence','battery','sensor'):
            cfg=Config.from_dict({**self.cfg,'dropout_start':0,'dropout_duration':1,'sensor_timeout':.2})
            with patch.object(ManualFlight,'run'):
                flight=ManualFlight(self.ctx,cfg,'边界核验',lambda:None)
            flight.thread.join()
            if kind=='fence':flight.position=[cfg.geofence+1,0,2]
            elif kind=='battery':flight.battery=0
            else:flight.sensor_missing=.25
            flight.advance()
            self.assertEqual(flight.status,'ABORTED',kind)
            self.assertEqual(flight.rows[-1]['mode'],'ABORTED')
            self.assertTrue(flight.done.is_set())
