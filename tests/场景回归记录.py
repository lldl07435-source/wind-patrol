# -*- coding: utf-8 -*-
"""12 个内置场景回归：与《设计与操作说明书》第 16 节验证表逐项核对。

运行方式：PyCharm 中直接运行，或命令行 python 场景回归记录.py
输出同时便于保存为文本证据；全部一致时以退出码 0 结束。
"""
import sys
from pathlib import Path
SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))
from scenarios import SCENARIOS, scenario_config
from quadrotor_patrol_simulation import Config, run_simulation

EXPECTED = {
    'default': ('DONE', '4/4', 29.40),
    'steady_wind': ('DONE', '4/4', 29.65),
    'gust': ('DONE', '4/4', 34.05),
    'turbulent': ('DONE', '4/4', 33.75),
    'wind_limit': ('ABORTED', '0/4', 0.00),
    'low_battery': ('DONE', '0/4', 6.10),
    'dropout': ('ABORTED', '1/4', 2.95),
    'recovery': ('DONE', '4/4', 29.60),
    'collision': ('ABORTED', '1/4', 5.50),
    'wind': ('DONE', '4/4', 29.30),
    'timeout': ('TIMEOUT', '0/4', 2.00),
    'empty': ('ABORTED', '0/4', 0.00),
}
def main():
    print('12 个内置场景回归（随机种子 42）')
    print('场景 | 最终状态 | 完成航点 | 时长 s | 完整完成 | 与说明书第16节一致')
    ok = True
    for key, (exp_status, exp_vis, exp_time) in EXPECTED.items():
        s = run_simulation(Config.from_dict(scenario_config(key)))['summary']
        same = (s['status'] == exp_status and
                '%s/%s' % (s['visited'], s['total_waypoints']) == exp_vis and
                abs(s['elapsed'] - exp_time) < 0.005)
        ok = ok and same
        print('%s | %s | %s/%s | %.2f | %s | %s' % (
            SCENARIOS[key][0], s['status'], s['visited'], s['total_waypoints'],
            s['elapsed'], '是' if s['mission_complete'] else '否',
            '一致' if same else '不一致'))
    print('结论：' + ('12/12 与说明书第 16 节验证表一致。' if ok else '存在不一致，请检查。'))
    return 0 if ok else 1
if __name__ == '__main__':
    raise SystemExit(main())
