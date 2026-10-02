# -*- coding: utf-8 -*-
"""软件验证测试：70 项用例，覆盖仿真核心、统计、配对比较、持久化、流转与主题记录。

运行方式（在 PyCharm 中直接运行本文件，或命令行）：
    python 软件验证测试.py
全部通过时输出 70/70；任一失败时以非零退出码结束。
本脚本仅使用 Python 标准库，依赖项目「源代码」目录中的模块。
"""
import math
import json
import sys
import tempfile
from hashlib import sha256
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

from quadrotor_patrol_simulation import (
    Config, FlightState, SensorModel, WindModel, WindStateEstimator,
    StateEstimator, PidController, EventTrigger, HeterogeneousScheduler,
    obstacle_avoidance, segment_clearance, run_simulation,
)
from analysis import percentile, decimate, metrics, public_result
from comparison import compare
from repository import Repository
from workflow import Workflow, ConflictError
from engineering_store import EngineeringStore
from scenarios import SCENARIOS, scenario_config

CASES = []
def case(name, fn):
    CASES.append((name, fn))
def assert_raises(fn, error=ValueError):
    try:
        fn()
    except error:
        return
    raise AssertionError('未抛出预期异常 ' + error.__name__)

# ---------------- A. 仿真核心（32 项） ----------------
def cfg(raw):
    return Config.from_dict(raw)
case('01 数值字段超出范围被拒绝', lambda: assert_raises(lambda: cfg({'dt': 999})))
case('02 随机种子必须为整数', lambda: assert_raises(lambda: cfg({'seed': 1.5})))
case('03 自适应开关必须为布尔值', lambda: assert_raises(lambda: cfg({'adaptive_control': 1})))
case('04 未知配置项被拒绝', lambda: assert_raises(lambda: cfg({'not_a_field': 1})))
case('05 临界电量不得高于返航电量', lambda: assert_raises(lambda: cfg({'critical_threshold': 0.5, 'return_threshold': 0.3})))
case('06 最长保持时间不得小于步长', lambda: assert_raises(lambda: cfg({'max_hold': 0.01, 'dt': 0.05})))
case('07 观测超时不得小于步长', lambda: assert_raises(lambda: cfg({'sensor_timeout': 0.01, 'dt': 0.05})))
case('08 单次仿真步数上限', lambda: assert_raises(lambda: cfg({'duration': 100000, 'dt': 0.01})))
case('09 风速向量模长上限', lambda: assert_raises(lambda: cfg({'wind': [30, 0, 0]})))
case('10 航点数量至少一个', lambda: assert_raises(lambda: cfg({'waypoints': []})))
case('11 航点高度至少一米', lambda: assert_raises(lambda: cfg({'waypoints': [[0, 0, 0.5]]})))
case('12 航点必须位于围栏内', lambda: assert_raises(lambda: cfg({'waypoints': [[500, 0, 5]], 'geofence': 100})))
case('13 障碍物必须包含球心与半径', lambda: assert_raises(lambda: cfg({'obstacles': [{'center': [1, 1, 1]}]})))
case('14 障碍物不得与航点重叠', lambda: assert_raises(lambda: cfg({'obstacles': [{'center': [0, 0, 5], 'radius': 2}]})))

def _wind_case15():
    c = cfg({'wind': [0, 0, 0], 'gust_amplitude': 2.0, 'gust_period': 4.0, 'turbulence_intensity': 0.0})
    w = WindModel(c).sample(1.0, 0.05)  # 相位 pi/2，方向系数回退为东向
    assert abs(w[0] - 2.0) < 1e-9 and abs(w[1]) < 1e-9, w
case('15 阵风相位与方向系数计算', _wind_case15)

def _wind_case16():
    c = cfg({'turbulence_intensity': 0.3, 'gust_amplitude': 1.0})
    a = [WindModel(c).sample(i * 0.05, 0.05) for i in range(100)]
    b = [WindModel(c).sample(i * 0.05, 0.05) for i in range(100)]
    assert a == b
case('16 风场序列固定种子可复现', _wind_case16)

def _sensor_case17():
    c = cfg({'dropout_start': 1.0, 'dropout_duration': 1.0})
    s = SensorModel(c)
    assert s.observe(FlightState(), 1.5) is None and s.observe(FlightState(), 0.5) is not None
case('17 观测中断期间不产生观测', _sensor_case17)

def _sensor_case18():
    c = cfg({'noise_std': 0.05})
    a = [SensorModel(c).observe(FlightState(), i * 0.05) for i in range(50)]
    b = [SensorModel(c).observe(FlightState(), i * 0.05) for i in range(50)]
    assert a == b
case('18 观测噪声序列固定种子可复现', _sensor_case18)

def _est_case19():
    e = StateEstimator()
    e.update([1.0, 0.0, 0.0], 0.1, 0.1)
    assert abs(e.position[0] - 0.65) < 1e-9
case('19 状态估计按残差校正位置', _est_case19)

def _est_case20():
    e = StateEstimator()
    e.update([1.0, 0.0, 0.0], 0.1, 0.1)
    e.update(None, 0.2, 0.1)
    assert abs(e.position[0] - 0.73) < 1e-9  # 上一速度外推
case('20 观测中断时按上一速度外推', _est_case20)

def _ctl_case21():
    c = cfg({})
    est = StateEstimator()
    est.update([0.5, 0, 0], 0.1, 0.1)
    base = PidController(c).command([2, 0, 0], est, 0.05, None, 'CALM')
    calm = PidController(c).command([2, 0, 0], est, 0.05, [1, 0, 0], 'CALM')
    gust = PidController(c).command([2, 0, 0], est, 0.05, [1, 0, 0], 'GUST')
    assert abs((base[0] - calm[0]) - 0.25) < 1e-9 and abs((base[0] - gust[0]) - 0.32) < 1e-9
case('21 风前馈系数随平稳/阵风切换', _ctl_case21)

def _ctl_case22():
    c = cfg({})
    est = StateEstimator()
    controller = PidController(c)
    for _ in range(20):
        controller.command([100, 100, 100], est, 0.05, None, 'CALM')
    assert all(abs(v) <= 2.0 + 1e-9 for v in controller.integral) and all(abs(v) >= 2.0 - 1e-9 for v in controller.integral)
case('22 积分项限幅在正负二之间', _ctl_case22)

def _trig_case23():
    t = EventTrigger(cfg({}))
    assert t.select([1, 0, 0], 0.0)[1] is True
    assert t.select([1.0001, 0, 0], 0.1)[1] is False  # 变化未达阈值且未到期
case('23 指令变化不足阈值时不更新', _trig_case23)

def _trig_case24():
    t = EventTrigger(cfg({}))
    t.select([1, 0, 0], 0.0)
    assert t.select([1.0001, 0, 0], 0.3)[1] is True  # 超过最长保持时间
case('24 指令保持到期后强制更新', _trig_case24)

def _sched_case25():
    s = HeterogeneousScheduler()
    assert abs(s.pipeline(0.0, 1.0, True) - 0.010) < 1e-9  # 6+3+1 毫秒
case('25 虚拟节点链路时延为十毫秒', _sched_case25)

def _sched_case26():
    s = HeterogeneousScheduler()
    s.pipeline(0.0, 0.005, True)
    assert s.missed == 1
case('26 超过期限的链路计入超期', _sched_case26)

def _avoid_case27():
    c = cfg({'obstacles': [{'center': [6.5, 0, 5], 'radius': 1}]})
    out = obstacle_avoidance([0, 0, 0], FlightState(position=[6, 0, 5]), c.obstacles, c.max_accel)
    assert out[0] < 0 and abs(math.sqrt(sum(v * v for v in out)) - 3.0) < 1e-9
case('27 靠近障碍时叠加斥力并限幅', _avoid_case27)

def _clear_case28():
    d = segment_clearance([0, 0, 5], [2, 0, 5], {'center': [1, 0, 5], 'radius': 0.5})
    assert d <= 0
case('28 穿越球面线段判定为碰撞', _clear_case28)

def _sim_case29():
    s = run_simulation(cfg({'seed': 42}))['summary']
    assert s['status'] == 'DONE' and s['visited'] == 4 and abs(s['elapsed'] - 29.40) < 0.005
case('29 默认场景 DONE 四航点 29.40 秒', _sim_case29)

def _sim_case30():
    s = run_simulation(cfg(scenario_config('wind_limit')))['summary']
    assert s['status'] == 'ABORTED' and s['samples'] == 0
case('30 超限风场景立即中止且零采样', _sim_case30)

def _sim_case31():
    r = run_simulation(cfg(scenario_config('collision')))
    assert r['summary']['status'] == 'ABORTED' and any('碰撞' in e['detail'] for e in r['events'])
case('31 碰撞场景中止并留痕', _sim_case31)

def _sim_case32():
    s = run_simulation(cfg(scenario_config('empty')))['summary']
    assert s['status'] == 'ABORTED' and s['samples'] == 0
case('32 零电量场景在运动前中止', _sim_case32)

# ---------------- B. 统计与整理（8 项） ----------------
def _ana_case33():
    assert percentile([], 0.5) is None
case('33 空列表百分位返回空值', _ana_case33)

def _ana_case34():
    assert percentile([0, 1, 2, 3], 0.0) == 0 and percentile([0, 1, 2, 3], 1.0) == 3
case('34 百分位零与一取到边界值', _ana_case34)

def _ana_case35():
    rows = [{'x': i} for i in range(5000)]
    out = decimate(rows, 1600)
    assert len(out) == 1600 and out[0] is rows[0] and out[-1] is rows[-1]
case('35 绘图抽样保留首尾且不超上限', _ana_case35)

def _ana_case36():
    assert_raises(lambda: decimate([1], 1), ValueError)
case('36 绘图抽样上限过小被拒绝', _ana_case36)

def _ana_case37():
    r = run_simulation(cfg({'seed': 42}))
    m = metrics(r)
    assert m['path_length_m'] > 0 and m['sensor_availability'] > 0.99 and m['mean_target_distance_m'] is not None
case('37 默认场景指标数值合理', _ana_case37)

def _ana_case38():
    r = run_simulation(cfg(scenario_config('wind_limit')))
    m = metrics(r)
    assert m['path_length_m'] == 0 and m['sensor_availability'] is None
case('38 零采样场景指标返回空值', _ana_case38)

def _ana_case39():
    record = {'id': 'a' * 16, 'name': '测试',
              'created': '2026-09-01T00:00:00+00:00',
              'result': run_simulation(cfg({'seed': 42}))}
    public = public_result(record)
    for key in ('id', 'name', 'created', 'config', 'summary', 'events', 'metrics', 'samples'):
        assert key in public, key
case('39 公开结果包含全部展示字段', _ana_case39)

def _ana_case40():
    record = {'id': 'a' * 16, 'name': '测试',
              'created': '2026-09-01T00:00:00+00:00',
              'result': run_simulation(cfg({'seed': 42}))}
    assert len(public_result(record)['samples']) <= 1600
case('40 公开结果绘图采样不超过上限', _ana_case40)

# ---------------- C. 配对实验（7 项） ----------------
def _cmp_case41():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        assert_raises(lambda: compare({'config': {}, 'seeds': [1, 2, 3, 4, 5, 6]}, repo))
case('41 配对实验种子最多五个', _cmp_case41)

def _cmp_case42():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        assert_raises(lambda: compare({'config': {}, 'seeds': [42, 42]}, repo))
case('42 配对实验种子不得重复', _cmp_case42)

def _cmp_case43():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        assert_raises(lambda: compare({'config': {'duration': 3600, 'dt': 0.01}, 'seeds': [1, 2]}, repo))
case('43 配对实验总步数上限', _cmp_case43)

def _cmp_case44():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        report = compare({'config': {'duration': 2, 'dt': 0.1}, 'seeds': [42]}, repo)
        assert len(report['pairs']) == 1 and set(report['aggregates']) == {'baseline', 'adaptive'}
        assert len(repo.list()) == 2
case('44 单种子配对生成两组任务与聚合', _cmp_case44)

def _cmp_case45():
    base = run_simulation(cfg({'seed': 42, 'adaptive_control': False, 'wind': [3, 0.5, 0]}))
    adap = run_simulation(cfg({'seed': 42, 'adaptive_control': True, 'wind': [3, 0.5, 0]}))
    assert base['samples'][0]['wind_speed'] == adap['samples'][0]['wind_speed']
case('45 配对实验两组风场一致', _cmp_case45)

def _cmp_case46():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        report = compare({'config': {'duration': 2, 'dt': 0.1}, 'seeds': [42]}, repo)
        expected = sha256(json.dumps(report['base_config'], sort_keys=True).encode()).hexdigest()
        assert report['config_sha256'] == expected
case('46 报告配置哈希与基准配置一致', _cmp_case46)

def _cmp_case47():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        report = compare({'config': {'duration': 2, 'dt': 0.1}, 'seeds': [42, 43, 44]}, repo)
        assert len(report['pairs']) == 3 and len(repo.list()) == 6
case('47 多种子配对任务数量正确', _cmp_case47)

# ---------------- D. 任务持久化（9 项） ----------------
def _repo_case48():
    assert_raises(lambda: Repository.make_record('  ', run_simulation(cfg({}))))
case('48 任务名称为空白被拒绝', _repo_case48)

def _repo_case49():
    assert_raises(lambda: Repository.make_record('长' * 81, run_simulation(cfg({}))))
case('49 任务名称超过八十字符被拒绝', _repo_case49)

def _repo_case50():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        record = repo.add('保存读取', run_simulation(cfg({'duration': 2, 'dt': 0.1})))
        assert repo.get(record['id'])['name'] == '保存读取'
case('50 任务保存后可按编号读取', _repo_case50)

def _repo_case51():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        assert_raises(lambda: repo.get('zzzz'), ValueError)
case('51 非法任务编号被拒绝', _repo_case51)

def _repo_case52():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        assert_raises(lambda: repo.get('a' * 16), KeyError)
case('52 不存在任务提示数据目录', _repo_case52)

def _repo_case53():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        repo.add('摘要字段', run_simulation(cfg({'duration': 2, 'dt': 0.1})))
        item = repo.list()[0]
        assert 'summary' in item and 'mission_complete' in item['summary']
case('53 任务列表携带摘要字段', _repo_case53)

def _repo_case54():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        record = repo.add('压缩包', run_simulation(cfg({'duration': 2, 'dt': 0.1})))
        import zipfile, io
        z = zipfile.ZipFile(io.BytesIO(repo.zip_bytes(record['id'])))
        assert set(z.namelist()) >= {'task.json', 'config.json', 'summary.json', 'events.json', 'metrics.json', 'trajectory.csv'}
case('54 证据压缩包包含七类文件', _repo_case54)

def _repo_case55():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        record = repo.add('导出目录', run_simulation(cfg({'duration': 2, 'dt': 0.1})))
        target = repo.export(record['id'])
        assert (target / 'report.html').exists() and (target / 'metrics.json').exists()
case('55 服务端导出生成报告与指标', _repo_case55)

def _repo_case56():
    with tempfile.TemporaryDirectory() as d:
        repo = Repository(d)
        repo.save_comparison([], {'id': 'x' * 32, 'payload': 1})
        assert repo.comparisons()[0]['payload'] == 1
case('56 配对报告可保存并读回', _repo_case56)

# ---------------- E. 资产与缺陷流转（8 项） ----------------
def _setup_workflow():
    d = tempfile.TemporaryDirectory()
    repo = Repository(d.name)
    record = repo.add('流转任务', run_simulation(cfg({'duration': 2, 'dt': 0.1})))
    wf = Workflow(d.name, repo)
    return d, repo, wf, record

def _wf_case57():
    d, repo, wf, _ = _setup_workflow()
    try:
        wf.asset({'code': 'T001', 'name': '杆塔绝缘子', 'location': '一号线'})
        assert_raises(lambda: wf.asset({'code': 'T001', 'name': '重复编号', 'location': 'x'}))
    finally:
        d.cleanup()
case('57 资产编号不得重复', _wf_case57)

def _wf_case58():
    d, repo, wf, record = _setup_workflow()
    try:
        assert_raises(lambda: wf.defect({'asset_id': 'no-such-asset', 'task_id': record['id'], 'title': 'x', 'severity': 'low', 'reason': 'x'}))
    finally:
        d.cleanup()
case('58 缺陷必须关联已登记资产', _wf_case58)

def _wf_case59():
    d, repo, wf, record = _setup_workflow()
    try:
        asset = wf.asset({'code': 'T002', 'name': '杆塔', 'location': '一号线'})
        defect = wf.defect({'asset_id': asset['id'], 'task_id': record['id'], 'title': '缺陷', 'severity': 'high', 'reason': '依据'})
        assert defect['status'] == 'pending' and defect['revision'] == 1
    finally:
        d.cleanup()
case('59 缺陷创建后处于待复核状态', _wf_case59)

def _wf_case60():
    d, repo, wf, record = _setup_workflow()
    try:
        asset = wf.asset({'code': 'T003', 'name': '杆塔', 'location': '一号线'})
        defect = wf.defect({'asset_id': asset['id'], 'task_id': record['id'], 'title': '缺陷', 'severity': 'low', 'reason': '依据'})
        out = wf.transition({'id': defect['id'], 'action': 'confirm', 'reason': '成立', 'revision': 1})
        assert out['status'] == 'confirmed' and out['revision'] == 2
    finally:
        d.cleanup()
case('60 确认缺陷进入已确认状态', _wf_case60)

def _wf_case61():
    d, repo, wf, record = _setup_workflow()
    try:
        asset = wf.asset({'code': 'T004', 'name': '杆塔', 'location': '一号线'})
        defect = wf.defect({'asset_id': asset['id'], 'task_id': record['id'], 'title': '缺陷', 'severity': 'low', 'reason': '依据'})
        assert_raises(lambda: wf.transition({'id': defect['id'], 'action': 'dispatch', 'reason': 'x', 'revision': 1}))
    finally:
        d.cleanup()
case('61 当前状态不允许的动作被拒绝', _wf_case61)

def _wf_case62():
    d, repo, wf, record = _setup_workflow()
    try:
        asset = wf.asset({'code': 'T005', 'name': '杆塔', 'location': '一号线'})
        defect = wf.defect({'asset_id': asset['id'], 'task_id': record['id'], 'title': '缺陷', 'severity': 'low', 'reason': '依据'})
        wf.transition({'id': defect['id'], 'action': 'confirm', 'reason': 'x', 'revision': 1})
        assert_raises(lambda: wf.transition({'id': defect['id'], 'action': 'dispatch', 'reason': 'x', 'revision': 1}), ConflictError)
    finally:
        d.cleanup()
case('62 旧版本提交触发冲突提示', _wf_case62)

def _wf_case63():
    d, repo, wf, record = _setup_workflow()
    try:
        asset = wf.asset({'code': 'T006', 'name': '杆塔', 'location': '一号线'})
        defect = wf.defect({'asset_id': asset['id'], 'task_id': record['id'], 'title': '缺陷', 'severity': 'low', 'reason': '依据'})
        wf.transition({'id': defect['id'], 'action': 'confirm', 'reason': 'x', 'revision': 1})
        out = wf.transition({'id': defect['id'], 'action': 'dispatch', 'reason': 'x', 'revision': 2})
        assert out['work_order'] is not None
    finally:
        d.cleanup()
case('63 生成工单时产生工单编号', _wf_case63)

def _wf_case64():
    d, repo, wf, record = _setup_workflow()
    try:
        asset = wf.asset({'code': 'T007', 'name': '杆塔', 'location': '一号线'})
        defect = wf.defect({'asset_id': asset['id'], 'task_id': record['id'], 'title': '缺陷', 'severity': 'low', 'reason': '依据'})
        key = defect['id']
        for action, revision in [('confirm', 1), ('dispatch', 2), ('resolve', 3), ('accept', 4), ('reopen', 5)]:
            wf.transition({'id': key, 'action': action, 'reason': 'x', 'revision': revision})
        snap = wf.snapshot()
        assert snap['defects'][0]['status'] == 'pending' and len(snap['events']) == 6
    finally:
        d.cleanup()
case('64 缺陷完整闭环流转留痕', _wf_case64)

# ---------------- F. 工程主题记录（6 项） ----------------
def _eng_case65():
    with tempfile.TemporaryDirectory() as d:
        store = EngineeringStore(d)
        assert_raises(lambda: store.create({'page': '非法页面_中文', 'name': 'x'}))
case('65 页面标识只允许小写字母与连字符', _eng_case65)

def _eng_case66():
    with tempfile.TemporaryDirectory() as d:
        store = EngineeringStore(d)
        assert_raises(lambda: store.create({'page': 'route-editing', 'name': '长' * 81}))
case('66 主题记录名称长度上限', _eng_case66)

def _eng_case67():
    with tempfile.TemporaryDirectory() as d:
        store = EngineeringStore(d)
        assert_raises(lambda: store.create({'page': 'route-editing', 'name': 'x', 'status': 'unknown'}))
case('67 非法记录状态被拒绝', _eng_case67)

def _eng_case68():
    with tempfile.TemporaryDirectory() as d:
        store = EngineeringStore(d)
        assert_raises(lambda: store.create({'page': 'route-editing', 'name': 'x', 'risk': '高'}))
case('68 风险评分必须为数值', _eng_case68)

def _eng_case69():
    with tempfile.TemporaryDirectory() as d:
        store = EngineeringStore(d)
        assert_raises(lambda: store.create({'page': 'route-editing', 'name': 'x', 'risk': 101}))
case('69 风险评分范围零到一百', _eng_case69)

def _eng_case70():
    with tempfile.TemporaryDirectory() as d:
        store = EngineeringStore(d)
        store.create({'page': 'route-editing', 'name': '廊道复核', 'status': 'active', 'risk': 75, 'note': '记录'})
        assert store.list()[0]['name'] == '廊道复核'
case('70 主题记录创建与列表查询', _eng_case70)

# ---------------- 执行 ----------------
def main():
    print('软件验证测试开始，共 %d 项。' % len(CASES))
    passed = 0
    for index, (name, fn) in enumerate(CASES, 1):
        try:
            fn()
            passed += 1
            print('  %02d 通过  %s' % (index, name))
        except Exception as exc:
            print('  %02d 失败  %s —— %s: %s' % (index, name, type(exc).__name__, exc))
    print('结果：%d / %d 项通过。' % (passed, len(CASES)))
    return 0 if passed == len(CASES) else 1
if __name__ == '__main__':
    raise SystemExit(main())
