import math
import threading
from pathlib import Path
from django.http import HttpResponse
from django.middleware.csrf import get_token
from analysis import public_result
from quadrotor_patrol_simulation import Config, SOFTWARE_NAME, run_simulation
from repository import Repository
from scenarios import scenario_list
from engineering import full_catalogue
from engineering_store import EngineeringStore
from workflow import Workflow, ConflictError
from comparison import compare

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_ROOT = ROOT.parent / '运行结果' if ROOT.name == '源代码' else ROOT / 'data'
WEB_ROOT = ROOT / 'web'
VERSION = '1.1.1'
DEFAULT_PORT = 8765
COOKIE_NAME = 'windpatrol_session'
TITLE = '风巡智航 多风环境无人机巡检系统'
STATIC_FILES = {'index.html', 'app.js', 'style.css', 'engineering.html', 'engineering.js',
                'workbench.html', 'workbench.js', 'workbench.css'}
WEB_STEPS = 20000
LEGACY_NAMES = ('tasks.sqlite3', 'engineering.sqlite3', '运行日志.log')

def has_business_data(ctx):
    snap = ctx.workflow.snapshot()
    return bool(snap['assets'] or snap['defects'] or ctx.engineering.list() or ctx.repo.comparisons())

def health():
    Config.from_dict({})

class Context:
    def __init__(self, root):
        self.root = root
        self.repo = Repository(root)
        self.engineering = EngineeringStore(root)
        self.workflow = Workflow(root, self.repo)
        self.lock = threading.Lock()
    def busy(self):
        return self.lock.locked()
    def close(self):
        pass
    def record_count(self):
        with self.repo.connect() as db:
            return db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    def overview(self, request):
        rows = self.repo.list()
        query = request.GET.get('q', '').strip().lower()[:80]
        if query:
            rows = [r for r in rows if query in (r['id'] + r['name'] + r['created']).lower()]
        snap = self.workflow.snapshot()
        return {'total_records': self.record_count(), 'matching': len(rows), 'records': [
            {'id': r['id'], 'name': r['name'], 'time': r['created'], 'status': r['summary']['status'],
             'download': '/api/tasks/' + r['id'] + '/download'} for r in rows[:100]],
            'collections': [{'name': '巡检任务', 'count': self.record_count()},
                            {'name': '资产', 'count': len(snap['assets'])},
                            {'name': '缺陷', 'count': len(snap['defects'])},
                            {'name': '工程记录', 'count': len(self.engineering.list())},
                            {'name': '配对实验', 'count': len(self.repo.comparisons())}]}

def release_user(user):
    pass

def handle(request, route, raw):
    from portal import data
    ctx = data.context(request.user)
    if request.method == 'GET':
        if route == 'bootstrap':
            return {'software': SOFTWARE_NAME, 'version': VERSION, 'token': get_token(request),
                    'scenarios': scenario_list(), 'web_steps': WEB_STEPS}
        if route == 'engineering/catalog':
            return {'subsystems': full_catalogue(), 'scope': '软件仿真与决策支持'}
        if route == 'engineering/records':
            return ctx.engineering.list()
        if route == 'tasks':
            return ctx.repo.list()
        if route == 'workflow':
            return ctx.workflow.snapshot()
        if route == 'comparisons':
            return ctx.repo.comparisons()
        if route.startswith('tasks/'):
            parts = route.split('/')
            if len(parts) == 2:
                return public_result(ctx.repo.get(parts[1]))
            if len(parts) == 3 and parts[2] == 'download':
                response = HttpResponse(ctx.repo.zip_bytes(parts[1]), content_type='application/zip')
                response['Content-Disposition'] = 'attachment; filename="simulation-result.zip"'
                return response
        raise FileNotFoundError()
    if route in ('engineering/records', 'workflow/assets', 'workflow/defects', 'workflow/transition'):
        data.check_quota(ctx)
        try:
            if route == 'engineering/records':
                return ctx.engineering.create(raw)
            if route == 'workflow/assets':
                return ctx.workflow.asset(raw)
            if route == 'workflow/defects':
                return ctx.workflow.defect(raw)
            return ctx.workflow.transition(raw)
        except ConflictError as exc:
            raise RuntimeError(str(exc)) from exc
    if route in ('validate', 'run', 'comparisons'):
        cfg = Config.from_dict(raw.get('config'))
        steps = math.ceil(cfg.duration / cfg.dt)
        if steps > WEB_STEPS:
            raise ValueError('网页单任务最多20000步，请缩短时长或增大步长')
        if route == 'validate':
            return {'valid': True, 'steps': steps, 'message': '配置检查通过，可开始仿真。'}
        if not ctx.lock.acquire(blocking=False):
            raise RuntimeError('你的工作区已有任务计算中，请稍后再试')
        if not data.compute_slots.acquire(blocking=False):
            ctx.lock.release()
            raise RuntimeError('计算队列繁忙，请稍后再试')
        try:
            seeds = raw.get('seeds', [cfg.seed])
            data.check_quota(ctx, len(seeds) * 2 if route == 'comparisons' and isinstance(seeds, list) else 1)
            if route == 'comparisons':
                return compare(raw, ctx.repo)
            name = raw.get('name', '')
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
                raise ValueError('任务名称应为1至80个字符')
            return public_result(ctx.repo.add(name, run_simulation(cfg)))
        finally:
            data.compute_slots.release()
            ctx.lock.release()
    if route == 'export':
        # 云端直接下载 ZIP；本机目录不再作为公开响应返回。
        ctx.repo.get(raw.get('id'))
        return {'message': '请使用任务旁的下载按钮保存结果', 'download': '/api/tasks/' + raw['id'] + '/download'}
    raise FileNotFoundError()
