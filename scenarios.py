"""界面、批量试验与测试共用的场景配置。"""
from dataclasses import asdict
from copy import deepcopy
from quadrotor_patrol_simulation import Config
SCENARIOS = {
    'default': ('稳定风巡检', '0.2 m/s 稳定风，完成四个航点后自主返航。', {}),
    'steady_wind': ('持续侧风巡检', '北向 4 m/s 持续风，启用估计风前馈补偿。',
                    {'wind': [0, 4, 0], 'gust_amplitude': 0.3}),
    'gust': ('阵风走廊巡检', '东向持续风叠加 3 m/s 周期阵风，动态降低地速。',
             {'wind': [3, 0.5, 0], 'gust_amplitude': 3.0,
              'gust_period': 4.5, 'turbulence_intensity': 0.12}),
    'turbulent': ('河谷紊流巡检', '多方向随机紊流，验证姿态补偿与轨迹稳定性。',
                  {'wind': [2.2, 1.5, 0.1], 'gust_amplitude': 1.2,
                   'turbulence_intensity': 0.35}),
    'wind_limit': ('超限风安全中止', '风速达到软件阈值，任务进入安全中止并留痕。',
                   {'wind': [13, 0, 0], 'gust_amplitude': 0,
                    'max_operating_wind': 12}),
    'low_battery': ('低电量返航', '初始电量20%，检查提前返航；降落不代表巡检完成。',
                    {'initial_battery': 0.2}),
    'dropout': ('持续观测中断', '从1 秒开始中断10 秒，触发观测超时保护。',
                {'dropout_start': 1, 'dropout_duration': 10}),
    'recovery': ('短时中断恢复', '观测中断0.2 秒后恢复，检查估计与任务延续。',
                 {'dropout_start': 1, 'dropout_duration': 0.2}),
    'collision': ('障碍物碰撞检查', '球形障碍位于第一段航线，检验碰撞检测及中止记录。',
                  {'obstacles': [{'center': [6, 0, 5], 'radius': 1}]}),
    'wind': ('轻度横风', '北向风速1 米每秒，观察路径偏移和控制响应。',
             {'wind': [0, 1, 0], 'gust_amplitude': 0.2}),
    'timeout': ('时长上限检查', '仅运行2 秒，检查TIMEOUT 与未完成航点记录。',
                {'duration': 2}),
    'empty': ('临界电量检查', '初始电量为零，任务应立即中止且没有运动采样。',
              {'initial_battery': 0}),
}
def scenario_config(key):
    """返回独立配置，避免编辑一个场景后改变内置模板。"""
    if key not in SCENARIOS:
        raise ValueError('未找到内置场景')
    raw = asdict(Config())
    raw.update(deepcopy(SCENARIOS[key][2]))
    return asdict(Config.from_dict(raw))
def scenario_list():
    return [{'id': key, 'name': value[0], 'description': value[1],
             'config': scenario_config(key)} for key, value in SCENARIOS.items()]
