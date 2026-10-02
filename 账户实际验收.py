"""在独立数据目录完成真实 HTTP 仿真、登录和重启验收。"""
import hashlib
import http.cookiejar
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError, URLError
import zipfile

ROOT = Path(__file__).resolve().parent
IS_LD = (ROOT / 'ldcell').exists()
OUT = ROOT / ('evidence' if IS_LD else '测试结果') / time.strftime('%Y%m%d_%H%M%S_账户实际验收')
OUT.mkdir(parents=True, exist_ok=False)
DATA = OUT / '独立数据'
password = 'Acceptance-Local-Record-87!'
report = {'time':time.strftime('%Y-%m-%d %H:%M:%S'), 'checks':[], 'mode':'real HTTP with isolated data'}
process = None
log_stream = None

class Browser:
    def __init__(self):
        self.http = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(self, path, payload=None, code=200, binary=False):
        headers = {}
        if payload is not None:
            token = self.call('/api/account')['csrf']
            headers = {'Content-Type':'application/json', 'X-CSRFToken':token}
        req = Request(url + path, None if payload is None else json.dumps(payload).encode(), headers)
        try:
            with self.http.open(req, timeout=60) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:
            status, raw = error.code, error.read(); error.close()
        if status != code:
            raise AssertionError(f'{path}: {status} != {code}; {raw[:1000]!r}')
        return raw if binary else json.loads(raw)

def check(name, value):
    report['checks'].append({'name':name, 'passed':bool(value)})
    if not value:
        raise AssertionError(name)

def start():
    global process, url, log_stream
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    url='http://127.0.0.1:'+str(port)
    log_stream=(OUT / '服务控制台.log').open('ab')
    process=subprocess.Popen([sys.executable,'app.py','--no-browser','--port',str(port),'--data-root',str(DATA)],cwd=ROOT,stdout=log_stream,stderr=log_stream,env={**os.environ,'PYTHONUTF8':'1'})
    probe=Browser()
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        if process.poll() is not None:
            raise RuntimeError('服务启动失败，请检查服务控制台.log')
        try:
            probe.call('/api/account');return
        except (URLError,OSError):
            time.sleep(.1)
    raise RuntimeError('启动等待超时')

def stop():
    global process, log_stream
    if process and process.poll() is None:
        process.terminate();process.wait(10)
    if log_stream:
        log_stream.close()
    process=None;log_stream=None

try:
    start()
    owner,other=Browser(),Browser()
    for browser,username in ((owner,'ownerqa'),(other,'otherqa')):
        response=browser.call('/api/account/register',{'username':username,'password':password},code=201)
        check('注册-'+username,response['user']['username']==username)
    if IS_LD:
        owner.call('/api/start',{'count':12,'speed':10,'scenario':'normal'})
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            records=owner.call('/api/history')
            if records and records[0]['status']=='completed':break
            time.sleep(.1)
        key=records[0]['id'];detail='/api/run?id='+key;download='/api/export?id='+key
        check('真实仿真完成12件',records[0]['summary']['completed']==12)
        check('事件校验通过',owner.call(detail)['verification']['ok'])
    else:
        task=owner.call('/api/run',{'name':'多用户实际巡检验收','config':{}})
        key=task['id'];detail='/api/tasks/'+key;download=detail+'/download'
        check('真实巡检仿真保存',len(owner.call('/api/tasks'))==1)
        asset=owner.call('/api/workflow/assets',{'code':'QA-01','name':'验收杆塔','location':'验收线路'})
        defect=owner.call('/api/workflow/defects',{'asset_id':asset['id'],'task_id':key,'title':'模拟缺陷','severity':'low','reason':'隔离验收'})
        check('资产缺陷保存',bool(defect['id']))
        other.call('/api/workflow/defects',{'asset_id':asset['id'],'task_id':key,'title':'非法关联','severity':'low','reason':'隔离测试'},code=404)
        check('拒绝跨用户资产关联',len(other.call('/api/workflow')['defects'])==0)
    other.call(detail,code=404);other.call(download,code=404)
    check('其他账户无法下载或读取',other.call('/api/account/data')['total_records']==0)
    for path,filename in ((download,'任务结果.zip'),('/api/account/export','个人工作区.zip')):
        raw=owner.call(path,binary=True);(OUT / filename).write_bytes(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            check('ZIP完整-'+filename,bundle.testzip() is None and len(bundle.namelist())>0)
    owner.call('/api/account/logout',{})
    owner.call(detail,code=401)
    check('退出后数据不可读',owner.call('/api/account')['user'] is None)
    stop();start()
    owner=Browser();owner.call('/api/account/login',{'username':'ownerqa','password':password})
    check('重启后记录恢复',bool(owner.call(detail)))
    if not IS_LD:
        snapshot=owner.call('/api/workflow')
        check('重启后资产与缺陷恢复',len(snapshot['assets'])==1 and len(snapshot['defects'])==1)
    check('重启后审计日志保留',bool(owner.call('/api/account/data')['audit']))
    report['run_id']=key
    report['passed']=True
except Exception as error:
    report['passed']=False;report['error']=type(error).__name__+': '+str(error)
finally:
    stop()
    report['files']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file()}
    (OUT / '实际接口验收.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'folder':str(OUT),'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')},ensure_ascii=True))
raise SystemExit(int(not report['passed']))
