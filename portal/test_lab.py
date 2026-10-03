import copy
import io
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from .experiment_lab import Lab, parse_csv, compare_ld, compare_wind
from . import data
import workspace_adapter as adapter

LD_CSV = 'time_s,job_id,cycle_s,route,outcome\n1,1,1,0,completed\n3,2,2,1,completed\n'
WIND_CSV = 'time_s,x_m,y_m,z_m\n0,0,0,0\n1,1,0,1\n2,2,0,2\n'

class DataMathTests(unittest.TestCase):
    def test_known_cycle_error(self):
        base = parse_csv('ld', LD_CSV)
        observed = copy.deepcopy(base)
        observed[0]['cycle_s'] += 1
        observed[1]['cycle_s'] -= 1
        result = compare_ld(base,observed)
        self.assertEqual(result['rmse'],1)
        self.assertEqual(result['bias'],0)

    def test_job_ids_not_row_order(self):
        base = parse_csv('ld', LD_CSV)
        self.assertEqual(compare_ld(base,list(reversed(base)))['rmse'],0)

    def test_unmatched_jobs_rejected(self):
        base = parse_csv('ld', LD_CSV)
        observed = copy.deepcopy(base)
        for row in observed:
            row['job_id'] += 'x'
        with self.assertRaises(ValueError):
            compare_ld(base,observed)

    def test_unknown_not_counted_as_completed(self):
        base = parse_csv('ld', LD_CSV)
        observed = copy.deepcopy(base)
        observed[0].update(outcome='unknown',cycle_s=None)
        result = compare_ld(base, observed)
        self.assertEqual(result['count'],1)
        self.assertEqual(result['outcome_mismatches'],1)

    def test_duplicate_excluded(self):
        base = parse_csv('ld', LD_CSV)
        result=compare_ld(base,base+[base[0]])
        self.assertEqual(result['count'],1)
        self.assertEqual(result['duplicate_jobs'],1)

    def test_route_mismatch_excluded(self):
        base = parse_csv('ld', LD_CSV)
        observed=copy.deepcopy(base);observed[0]['route']=1
        self.assertEqual(compare_ld(base,observed)['route_mismatches'],1)
        self.assertEqual(compare_ld(base,observed)['count'],1)

    def test_interpolation_known_error(self):
        base = parse_csv('wind', WIND_CSV)
        observed = parse_csv('wind', 'time_s,x_m,y_m,z_m\n0.5,0.5,1,0.5\n1.5,1.5,1,1.5\n')
        self.assertEqual(compare_wind(base,observed)['rmse'],1)

    def test_no_extrapolation(self):
        base=parse_csv('wind', WIND_CSV)
        observed=base+[dict(time_s=3,x_m=3,y_m=0,z_m=3)]
        result=compare_wind(base,observed)
        self.assertEqual(result['coverage'],.75)
        self.assertEqual(result['skipped_samples'],1)

    def test_large_gap_rejected(self):
        base=parse_csv('wind','time_s,x_m,y_m,z_m\n0,0,0,0\n10,10,0,10\n')
        with self.assertRaises(ValueError):
            compare_wind(base,[dict(time_s=5,x_m=5,y_m=0,z_m=5)],max_gap=1)

    def test_time_offset(self):
        base=parse_csv('wind',WIND_CSV)
        observed=[dict(r,time_s=r['time_s']+10) for r in base]
        self.assertEqual(compare_wind(base,observed,offset=-10)['rmse'],0)

    def test_ned_conversion(self):
        row=parse_csv('wind','time_s,x_m,y_m,z_m\n0,2,3,-4\n','NED')[0]
        self.assertEqual((row['x_m'],row['y_m'],row['z_m']),(3,2,4))

    def test_bad_csv_cases(self):
        for text in ('time_s,x_m,y_m,z_m\n0,nan,0,0\n',
                     'time_s,x_m,y_m,z_m\n0,0,0,0\n0,1,1,1\n',
                     'time_s,x_m,y_m,z_m\n0,0,0\n',
                     'time_s,x_m,y_m,z_m\n0,0,0,0,5\n',
                     'time_s,x_m,y_m,z_m\n1,0,0,0\n0,1,1,1\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_csv('wind',text)

    def test_persistence_and_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            lab=Lab(directory,'ld')
            item=lab.add('演示','demo',parse_csv('ld',LD_CSV),source_text=LD_CSV)
            saved=Lab(directory,'ld').get(item['id'])
            self.assertEqual(saved['kind'],'demo')
            self.assertEqual(saved['source_text'],LD_CSV)
            self.assertEqual(saved['count'],2)

class LabApiTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.override=override_settings(DATA_ROOT=Path(self.temp.name))
        self.override.enable()
        self.user=get_user_model().objects.create_user(username='experiment_a',password='Bench-Tests!2026')
        self.other=get_user_model().objects.create_user(username='experiment_b',password='Bench-Tests!2026')
        self.client=Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.domain='ld' if adapter.COOKIE_NAME=='ldflex_session' else 'wind'
        self.text=LD_CSV if self.domain=='ld' else WIND_CSV

    def tearDown(self):
        data.close_all();self.override.disable();self.temp.cleanup()

    def post(self,route,payload):
        token=self.client.get('/api/account').json()['csrf']
        return self.client.post('/api/lab/'+route,json.dumps(payload),content_type='application/json',HTTP_X_CSRFTOKEN=token)

    def add(self):
        response=self.post('import',dict(name='实验记录',kind='demo',csv=self.text))
        self.assertEqual(response.status_code,200,response.content)
        return response.json()['id']

    def test_auth_and_csrf(self):
        anon=Client()
        self.assertEqual(anon.get('/api/lab/datasets').status_code,401)
        self.assertEqual(self.client.post('/api/lab/import','{}',content_type='application/json').status_code,403)
        self.assertEqual(anon.get('/lab.html').status_code,302)

    def test_import_list_and_immutable_source(self):
        key=self.add()
        rows=self.client.get('/api/lab/datasets').json()
        self.assertEqual(rows[0]['id'],key)
        self.assertEqual(rows[0]['kind'],'demo')
        self.assertNotIn('rows',rows[0])

    def test_account_isolation_all_paths(self):
        key=self.add()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/api/lab/datasets').json(),[])
        for route in ('datasets/'+key,'datasets/'+key+'/download'):
            self.assertEqual(self.client.get('/api/lab/'+route).status_code,404)
        self.assertEqual(self.post('compare',dict(base=key,observed='a'*32)).status_code,404)

    def test_zip_keeps_original_and_hash(self):
        key=self.add()
        response=self.client.get('/api/lab/datasets/'+key+'/download')
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(archive.read('original.csv').decode('utf-8'),self.text)
            self.assertEqual(json.loads(archive.read('metadata.json'))['kind'],'demo')
            self.assertIn('data.csv',archive.namelist())

    def test_compare_and_report_isolation(self):
        a,b=self.add(),self.add()
        response=self.post('compare',dict(base=a,observed=b,frame_confirmed=True))
        self.assertEqual(response.status_code,200,response.content)
        key=response.json()['id']
        self.assertEqual(response.json()['metrics']['rmse'],0)
        self.assertEqual(self.client.get('/api/lab/reports/'+key+'/download').status_code,200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/api/lab/reports/'+key+'/download').status_code,404)

    def test_self_comparison_rejected(self):
        key=self.add()
        self.assertEqual(self.post('compare',dict(base=key,observed=key)).status_code,400)

    def test_no_forged_native_source_kind(self):
        self.assertEqual(self.post('import',dict(name='假标注',kind='hardware',csv=self.text)).status_code,400)

    def test_path_traversal_rejected(self):
        self.assertEqual(self.client.get('/api/lab/datasets/../../secret').status_code,404)
        self.assertEqual(self.client.get('/api/lab/datasets/not-a-key').status_code,400)

    def test_bad_csv_has_no_partial_write(self):
        self.assertEqual(self.post('import',dict(name='bad',kind='demo',csv='bad')).status_code,400)
        self.assertEqual(self.client.get('/api/lab/datasets').json(),[])

    def test_page_and_assets(self):
        for name in ('lab.html','lab.css','lab.js'):
            self.assertEqual(self.client.get('/'+name).status_code,200)

    def test_native_simulation_import(self):
        ctx=data.context(self.user)
        if self.domain=='ld':
            from ldcell.storage import RunLog
            from ldcell.simulation import Simulation, run_to_end
            log=RunLog(ctx.root,dict(scenario='normal'))
            sim=Simulation(count=4,event=log.event)
            run_to_end(sim)
            log.finish(sim.summary(),sim.rows)
            key=log.id
        else:
            from quadrotor_patrol_simulation import Config,run_simulation
            key=ctx.repo.add('原生基准',run_simulation(Config.from_dict({'duration':6})))['id']
        response=self.post('native',dict(name='原生导入',source_id=key))
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['kind'],'simulation')
        self.assertGreater(response.json()['count'],1)

    def test_native_source_not_other_account(self):
        key='0'*16 if self.domain=='wind' else '20261003_000000_000001_aaaaaa'
        self.assertIn(self.post('native',dict(name='其他用户数据',source_id=key)).status_code,(400,404))
