"""对同一场景运行成对仿真并汇总指标。"""
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4
import json
import math
from analysis import metrics
from quadrotor_patrol_simulation import Config, run_simulation
def compare(raw, repository):
    cfg = Config.from_dict(raw.get('config'))
    seeds = raw.get('seeds', [cfg.seed])
    if (not isinstance(seeds, list) or not 1 <= len(seeds) <= 5 or
            any(type(s) is not int or not 0 <= s < 2**32 for s in seeds)):
        raise ValueError('请提供一至五个有效整数种子')
    if len(set(seeds)) != len(seeds):
        raise ValueError('随机种子不得重复')
    if math.ceil(cfg.duration / cfg.dt) * len(seeds) * 2 > 40000:
        raise ValueError('一次配对实验最多四万步，请减少种子或仿真时长')
    base = asdict(cfg)
    records, pairs = [], []
    for seed in seeds:
        pair = {'seed': seed}
        for label, adaptive in [('baseline', False), ('adaptive', True)]:
            values = dict(base, seed=seed, adaptive_control=adaptive)
            result = run_simulation(Config.from_dict(values))
            record = repository.make_record(
                ('自适应' if adaptive else '基线') + ' 配对种子 ' + str(seed), result)
            records.append(record)
            # 到当前目标的距离不是横向跟踪误差，保留准确的指标名称。
            pair[label] = {'task_id': record['id'], 'summary': result['summary'],
                           'metrics': metrics(result)}
        pairs.append(pair)
    aggregates = {}
    for label in ('baseline', 'adaptive'):
        rows = [p[label] for p in pairs]
        distances = [r['metrics']['mean_target_distance_m'] for r in rows
                     if r['metrics']['mean_target_distance_m'] is not None]
        aggregates[label] = {
            'completion_rate': sum(r['summary']['mission_complete'] for r in rows) / len(rows),
            'mean_elapsed_s': sum(r['summary']['elapsed'] for r in rows) / len(rows),
            'mean_path_length_m': sum(r['metrics']['path_length_m'] for r in rows) / len(rows),
            'mean_target_distance_m': sum(distances) / len(distances) if distances else None,
        }
    report = {
        'id': uuid4().hex, 'created': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'base_config': base, 'seeds': seeds, 'pairs': pairs,
        'aggregates': aggregates,
        'config_sha256': sha256(json.dumps(base, sort_keys=True).encode()).hexdigest(),
        'scope': '仅比较风前馈补偿及动态限速开关；其他参数与随机种子配对相同。',
        'interpretation': '风场在共同时间范围内一致。任务结束时刻可能不同；'
                          '时长和路径长度须结合完成状态解释，不自动判定优胜策略。',
    }
    return repository.save_comparison(records, report)
