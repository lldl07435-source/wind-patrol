# -*- coding: utf-8 -*-
"""面向多风环境的具身智能无人机电力自主巡检系统软件 V1.0。
采用三维质点模型模拟多风环境下的感知、决策、执行和反馈闭环，
感知、决策和控制节点在仿真时钟下计算任务时序。
运行方式和配置示例见随附操作说明书。
"""
from __future__ import annotations
import argparse
import csv
import html
import json
import math
import random
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
SOFTWARE_NAME = "面向多风环境的具身智能无人机电力自主巡检系统软件"
VERSION = "V1.0"
def number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是数值")
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name} 必须在 [{low}, {high}] 内且有限")
    return result
def vector(value: Any, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} 必须包含三个坐标")
    return tuple(number(v, name, -10000, 10000) for v in value)
def norm(values) -> float:
    return math.sqrt(sum(v * v for v in values))
def distance(a, b) -> float:
    return norm([x - y for x, y in zip(a, b)])
def limit(values, maximum: float) -> list[float]:
    size = norm(values)
    scale = min(1.0, maximum / max(size, 1e-12))
    return [v * scale for v in values]
@dataclass
class Config:
    dt: float = 0.05  # 仿真步长，单位秒
    duration: float = 120.0  # 仿真时长上限，单位秒
    seed: int = 42  # 随机种子，用于复现观测噪声
    waypoints: list = field(default_factory=lambda: [
        [0, 0, 5], [12, 0, 5], [12, 12, 5], [0, 12, 5]])
    obstacles: list = field(default_factory=list)
    wind: list = field(default_factory=lambda: [0.2, 0.0, 0.0])
    gust_amplitude: float = 0.6  # 阵风幅值，单位米每秒
    gust_period: float = 6.0  # 阵风主周期，单位秒
    turbulence_intensity: float = 0.08  # 随机紊流相对强度，0 至1
    max_operating_wind: float = 12.0  # 软件安全策略采用的风速上限
    adaptive_control: bool = True  # 是否启用估计风前馈补偿和动态限速
    noise_std: float = 0.03  # 位置噪声标准差，单位米
    dropout_start: float = 0.0
    dropout_duration: float = 0.0
    sensor_timeout: float = 2.0
    initial_battery: float = 1.0  # 归一化电量，1 表示满电
    battery_rate: float = 0.0008
    return_threshold: float = 0.25
    critical_threshold: float = 0.08
    max_speed: float = 3.0
    max_accel: float = 3.0
    arrival_radius: float = 0.6  # 航点到达容差，单位米
    geofence: float = 100.0  # 以原点为球心的围栏半径，单位米
    kp: float = 1.4
    ki: float = 0.02
    kd: float = 1.8
    event_threshold: float = 0.08
    max_hold: float = 0.25
    @classmethod
    def from_dict(cls, raw: dict) -> Config:
        if not isinstance(raw, dict):
            raise ValueError("配置根节点必须是 JSON 对象")
        unknown = set(raw) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"不支持的配置项: {sorted(unknown)}")
        cfg = cls(**raw)
        ranges = {
            "dt": (0.01, 0.2), "duration": (0.01, 3600),
            "noise_std": (0, 5), "dropout_start": (0, 3600),
            "dropout_duration": (0, 3600), "sensor_timeout": (0.1, 30),
            "initial_battery": (0, 1), "battery_rate": (0, 0.1),
            "return_threshold": (0.01, 0.9),
            "critical_threshold": (0, 0.8), "max_speed": (0.1, 20),
            "max_accel": (0.1, 20), "arrival_radius": (0.1, 3),
            "geofence": (5, 1000), "kp": (0, 10), "ki": (0, 2),
            "kd": (0, 10), "event_threshold": (0, 5),
            "max_hold": (0.01, 2),
            "gust_amplitude": (0, 20), "gust_period": (0.5, 120),
            "turbulence_intensity": (0, 1),
            "max_operating_wind": (0.5, 30),
        }
        for key, bounds in ranges.items():
            setattr(cfg, key, number(getattr(cfg, key), key, *bounds))
        if type(cfg.seed) is not int or not 0 <= cfg.seed <= 2**32 - 1:
            raise ValueError("seed 必须是 0 至 4294967295 的整数")
        if type(cfg.adaptive_control) is not bool:
            raise ValueError("adaptive_control 必须是布尔值")
        if cfg.critical_threshold >= cfg.return_threshold:
            raise ValueError("临界电量必须低于返航电量")
        if cfg.max_hold < cfg.dt:
            raise ValueError("max_hold 不得小于 dt")
        if cfg.sensor_timeout < cfg.dt:
            raise ValueError("sensor_timeout 不得小于 dt，否则采样间隔内无法判断观测超时")
        if math.ceil(cfg.duration / cfg.dt) > 100000:
            raise ValueError("单次仿真步数不得超过 100000")
        cfg.wind = list(vector(cfg.wind, "wind"))
        if norm(cfg.wind) > 20:
            raise ValueError("风速向量模长不得超过 20")
        if not isinstance(cfg.waypoints, list) or not 1 <= len(cfg.waypoints) <= 200:
            raise ValueError("航点数量必须在 1 至 200 之间")
        cfg.waypoints = [list(vector(p, "waypoint")) for p in cfg.waypoints]
        for point in cfg.waypoints:
            if point[2] < 1 or norm(point) >= cfg.geofence:
                raise ValueError("航点高度应至少 1 米且位于围栏内")
        if not isinstance(cfg.obstacles, list) or len(cfg.obstacles) > 100:
            raise ValueError("障碍物应为列表且最多 100 个")
        parsed = []
        for item in cfg.obstacles:
            if not isinstance(item, dict) or set(item) != {"center", "radius"}:
                raise ValueError("障碍物必须包含 center 和 radius")
            center = list(vector(item["center"], "center"))
            radius = number(item["radius"], "radius", 0.1, 50)
            for point in [[0, 0, 0]] + cfg.waypoints:
                if distance(center, point) <= radius + cfg.arrival_radius:
                    raise ValueError("起点或航点与障碍物安全区域重叠")
            parsed.append({"center": center, "radius": radius})
        cfg.obstacles = parsed
        return cfg
@dataclass
class FlightState:
    position: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    velocity: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    battery: float = 1.0
class SensorModel:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.random = random.Random(cfg.seed)
    def observe(self, state: FlightState, time: float):
        start = self.cfg.dropout_start
        if start <= time < start + self.cfg.dropout_duration:
            return None
        return [v + self.random.gauss(0, self.cfg.noise_std)
                for v in state.position]
class WindModel:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.random = random.Random(cfg.seed ^ 0x5A17)
        self.turbulence = [0.0, 0.0, 0.0]
    def sample(self, time: float, dt: float) -> list[float]:
        phase = 2.0 * math.pi * time / self.cfg.gust_period
        base_norm = max(norm(self.cfg.wind), 1.0)
        gust = self.cfg.gust_amplitude * math.sin(phase)
        direction = [v / base_norm for v in self.cfg.wind]
        if norm(direction) < 1e-9:
            direction = [1.0, 0.0, 0.0]
        # 一阶相关噪声比逐步独立噪声更接近连续紊流，也保持固定种子可复现。
        alpha = math.exp(-dt / 0.8)
        sigma = self.cfg.turbulence_intensity * base_norm
        for i in range(3):
            noise = self.random.gauss(0.0, sigma)
            self.turbulence[i] = alpha * self.turbulence[i] + (1 - alpha) * noise
        return [self.cfg.wind[i] + gust * direction[i] + self.turbulence[i]
                for i in range(3)]
class WindStateEstimator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.vector = list(cfg.wind)
        self.previous_speed = norm(self.vector)
    def update(self, measured: list[float], dt: float) -> tuple[list[float], str, float]:
        gain = 1.0 - math.exp(-dt / 0.45)
        self.vector = [old + gain * (new - old)
                       for old, new in zip(self.vector, measured)]
        speed = norm(measured)
        rate = abs(speed - self.previous_speed) / max(dt, 1e-9)
        self.previous_speed = speed
        if speed >= self.cfg.max_operating_wind:
            regime = "LIMIT"
        elif rate > 2.5 or self.cfg.gust_amplitude >= 2.0:
            regime = "GUST"
        elif self.cfg.turbulence_intensity >= 0.25:
            regime = "TURBULENT"
        elif speed >= 1.5:
            regime = "STEADY"
        else:
            regime = "CALM"
        gust_factor = speed / max(norm(self.cfg.wind), 0.5)
        return list(self.vector), regime, gust_factor
class StateEstimator:
    def __init__(self):
        self.position = [0.0, 0.0, 0.0]
        self.velocity = [0.0, 0.0, 0.0]
        self.last_observation = 0.0
    def update(self, observation, time: float, dt: float):
        predicted = [p + v * dt for p, v in
                     zip(self.position, self.velocity)]
        if observation is not None:
            residual = [o - p for o, p in zip(observation, predicted)]
            self.position = [p + 0.65 * r for p, r in zip(predicted, residual)]
            self.velocity = [v + 0.08 * r / dt for v, r in
                             zip(self.velocity, residual)]
            self.last_observation = time
        else:
            self.position = predicted
class PidController:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.integral = [0.0, 0.0, 0.0]
    def reset(self):
        self.integral = [0.0, 0.0, 0.0]
    def command(self, target, estimate: StateEstimator, dt: float,
                wind_estimate=None, wind_regime="CALM"):
        error = [t - p for t, p in zip(target, estimate.position)]
        for i in range(3):
            self.integral[i] = max(-2.0, min(2.0,
                self.integral[i] + error[i] * dt))
        cfg = self.cfg
        result = [cfg.kp * error[i] + cfg.ki * self.integral[i]
                  - cfg.kd * estimate.velocity[i] for i in range(3)]
        if cfg.adaptive_control and wind_estimate is not None:
            # 抵消模型中的风速差阻力项；阵风/紊流时提高阻尼并降低突变。
            damping = 0.32 if wind_regime in {"GUST", "TURBULENT"} else 0.25
            result = [value - damping * wind_estimate[i]
                      for i, value in enumerate(result)]
        return limit(result, cfg.max_accel)
class EventTrigger:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.last_time = -math.inf  # 确保首次指令立即更新
        self.last_command = [0.0, 0.0, 0.0]
        self.count = 0
    def select(self, command, time: float, force: bool = False):
        changed = distance(command, self.last_command)
        expired = time - self.last_time >= self.cfg.max_hold - 1e-10
        if force or changed >= self.cfg.event_threshold or expired:
            self.last_time = time
            self.last_command = list(command)
            self.count += 1
            return list(command), True
        return list(self.last_command), False
class HeterogeneousScheduler:
    def __init__(self):
        self.available = {"CPU": 0.0, "GPU": 0.0, "FCU": 0.0}
        self.count = {key: 0 for key in self.available}
        self.missed = 0
        self.max_latency = 0.0
    def pipeline(self, time: float, deadline: float, sensor_valid: bool):
        # 各节点服务时长为预设参数，单位秒。
        tasks = [("GPU", 0.006)] if sensor_valid else []
        tasks += [("CPU", 0.003), ("FCU", 0.001)]
        ready = time
        for node, cost in tasks:
            ready = max(ready, self.available[node]) + cost
            self.available[node] = ready
            self.count[node] += 1
        latency = ready - time
        self.max_latency = max(self.max_latency, latency)
        self.missed += int(latency > deadline + 1e-10)
        return latency
class Mission:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.mode = "PATROL"  # 初始状态为按序巡检
        self.index = 0  # 当前目标航点索引，从0 开始
        self.visited = 0
        self.events = []
        self.target = list(cfg.waypoints[0])
    def event(self, time: float, kind: str, detail: str):
        self.events.append({"time": round(time, 6),
                            "kind": kind, "detail": detail})
    def transition(self, mode: str, time: float, reason: str):
        if self.mode != mode:
            self.event(time, mode, reason)
            self.mode = mode
    def update(self, state, estimate, time, check_sensor=True, wind_speed=0.0):
        cfg = self.cfg
        if wind_speed >= cfg.max_operating_wind:
            self.transition("ABORTED", time, "风速达到软件安全上限")
        elif state.battery <= cfg.critical_threshold:
            self.transition("ABORTED", time, "电量达到临界阈值")
        elif norm(state.position) >= cfg.geofence:
            self.transition("ABORTED", time, "越过球形安全围栏")
        elif check_sensor and time - estimate.last_observation >= cfg.sensor_timeout:
            self.transition("ABORTED", time, "位置观测连续中断超时")
        if self.mode == "ABORTED":
            return
        if state.battery <= cfg.return_threshold and self.mode == "PATROL":
            self.transition("RETURN", time, "低电量提前返航")
        if self.mode == "PATROL":
            self.target = list(cfg.waypoints[self.index])
            if distance(estimate.position, self.target) <= cfg.arrival_radius:
                self.visited += 1
                self.event(time, "WAYPOINT", f"完成航点 {self.index + 1}")
                self.index += 1
                if self.index == len(cfg.waypoints):
                    self.transition("RETURN", time, "全部巡检航点完成")
                else:
                    self.target = list(cfg.waypoints[self.index])
        if self.mode == "RETURN":
            self.target = [0.0, 0.0, cfg.waypoints[0][2]]
            if distance(estimate.position, self.target) <= cfg.arrival_radius:
                self.transition("LAND", time, "到达返航点并开始降落")
        if self.mode == "LAND":
            self.target = [0.0, 0.0, 0.0]
            if norm(state.position) <= cfg.arrival_radius and norm(state.velocity) < 0.4:
                self.transition("DONE", time, "降落完成")
def obstacle_avoidance(command, state, obstacles, maximum):
    """接近球形障碍物时叠加斥力；该方法不进行全局路径搜索。"""
    result = list(command)
    for obstacle in obstacles:
        delta = [p - c for p, c in zip(state.position, obstacle["center"])]
        length = norm(delta)
        clearance = length - obstacle["radius"]
        if clearance < 3.0:
            gain = max(0.0, 3.0 - clearance) * 2.0
            direction = [x / max(length, 1e-9) for x in delta]
            result = [a + gain * d for a, d in zip(result, direction)]
    return limit(result, maximum)
def segment_clearance(start, end, obstacle):
    """计算单步运动线段到球面的最小间距，用于检测穿越碰撞。"""
    change = [b - a for a, b in zip(start, end)]
    squared = sum(x * x for x in change)
    relative = [c - a for c, a in zip(obstacle["center"], start)]
    factor = sum(a * b for a, b in zip(relative, change)) / max(squared, 1e-12)
    factor = max(0.0, min(1.0, factor))
    closest = [a + factor * d for a, d in zip(start, change)]
    return distance(closest, obstacle["center"]) - obstacle["radius"]
def run_simulation(cfg: Config) -> dict:
    """按设定步长推进仿真时间，不作实时等待，也不向硬件发送指令。"""
    cfg = Config.from_dict(asdict(cfg))
    state = FlightState(battery=cfg.initial_battery)
    sensor = SensorModel(cfg)
    wind_model = WindModel(cfg)
    wind_estimator = WindStateEstimator(cfg)
    estimator = StateEstimator()
    controller = PidController(cfg)
    trigger = EventTrigger(cfg)
    scheduler = HeterogeneousScheduler()
    mission = Mission(cfg)
    rows = []
    min_clearance = math.inf  # 无障碍物时，在摘要中记为null
    mission.event(0.0, "START", "仿真任务启动")
    # 通过整数步索引计算时间，避免连续累加造成误差。
    for step in range(math.ceil(cfg.duration / cfg.dt)):
        time = step * cfg.dt
        dt = min(cfg.dt, cfg.duration - time)  # 末步按剩余时长执行
        observation = sensor.observe(state, time)
        actual_wind = wind_model.sample(time, dt)
        estimated_wind, wind_regime, gust_factor = wind_estimator.update(actual_wind, dt)
        estimator.update(observation, time, dt)
        previous = mission.mode
        mission.update(state, estimator, time, wind_speed=norm(actual_wind))
        if mission.mode in {"DONE", "ABORTED"}:
            break
        if previous != mission.mode:
            controller.reset()
        command = controller.command(
            mission.target, estimator, dt, estimated_wind, wind_regime)
        command = obstacle_avoidance(command, state, cfg.obstacles, cfg.max_accel)
        command, emitted = trigger.select(command, time, previous != mission.mode)
        latency = scheduler.pipeline(time, dt, observation is not None)
        old_position = list(state.position)
        # 先更新速度再更新位置；风速差通过线性阻力项作用。
        acceleration = [a + 0.25 * (w - v) for a, w, v in
                        zip(command, actual_wind, state.velocity)]
        speed_limit = cfg.max_speed
        if cfg.adaptive_control and wind_regime in {"GUST", "TURBULENT"}:
            speed_limit *= 0.72
        state.velocity = limit([v + a * dt for v, a in
                                zip(state.velocity, acceleration)], speed_limit)
        state.position = [p + v * dt for p, v in
                          zip(state.position, state.velocity)]
        if state.position[2] < 0:
            state.position[2] = 0.0  # 地面高度下限
            state.velocity[2] = max(0.0, state.velocity[2])
        consumption = cfg.battery_rate * (1 + 0.1 * norm(command)) * dt
        state.battery = max(0.0, state.battery - consumption)
        for obstacle in cfg.obstacles:
            clearance = segment_clearance(old_position, state.position, obstacle)
            min_clearance = min(min_clearance, clearance)
            if clearance <= 0:
                mission.transition("ABORTED", time + dt, "检测到障碍物碰撞")
        row = {"time": round(time + dt, 6), "mode": mission.mode,
               "x": state.position[0], "y": state.position[1],
               "z": state.position[2], "speed": norm(state.velocity),
               "battery": state.battery, "target_index": mission.index,
               "target_distance": distance(state.position, mission.target),
               "wind_x": actual_wind[0], "wind_y": actual_wind[1],
               "wind_z": actual_wind[2], "wind_speed": norm(actual_wind),
               "wind_estimate_speed": norm(estimated_wind),
               "wind_regime": wind_regime, "gust_factor": gust_factor,
               "sensor_valid": observation is not None,
               "command_emitted": emitted, "virtual_latency": latency}
        rows.append(row)
        if mission.mode == "ABORTED":
            break
    elapsed = rows[-1]["time"] if rows else 0.0
    # 补查末步电量和位置，处理恰在仿真结束时触发的安全事件。
    if mission.mode not in {"ABORTED", "DONE"}:
        # 结束补查只处理末步产生的电量和围栏事件；此时没有新采样时刻，
        # 不把最后一次正常观测到仿真终点的间隔误判为观测中断。
        mission.update(state, estimator, elapsed, check_sensor=False,
                       wind_speed=0.0)
    if mission.mode not in {"ABORTED", "DONE"}:
        mission.transition("TIMEOUT", elapsed, "达到仿真时长上限")
    if rows:
        rows[-1]["mode"] = mission.mode
    summary = {
        "software": SOFTWARE_NAME, "version": VERSION,
        "status": mission.mode, "samples": len(rows),
        "elapsed": elapsed, "visited": mission.visited,
        "total_waypoints": len(cfg.waypoints),
        "mission_complete": mission.mode == "DONE" and
                            mission.visited == len(cfg.waypoints),
        "battery_remaining": state.battery,
        "max_speed": max((r["speed"] for r in rows), default=0),
        "max_wind_speed": max((r["wind_speed"] for r in rows), default=0),
        "mean_wind_speed": (sum(r["wind_speed"] for r in rows) / len(rows)
                            if rows else 0),
        "wind_regime_counts": {key: sum(r["wind_regime"] == key for r in rows)
                               for key in ("CALM", "STEADY", "GUST", "TURBULENT", "LIMIT")},
        "command_updates": trigger.count,
        "min_clearance": None if math.isinf(min_clearance) else min_clearance,
        "virtual_node_jobs": scheduler.count,
        "virtual_deadline_misses": scheduler.missed,
        "virtual_max_latency": scheduler.max_latency,
    }
    return {"config": asdict(cfg), "summary": summary,
            "events": mission.events, "samples": rows}
def write_report(result: dict, directory: Path):
    directory.mkdir(parents=True, exist_ok=False)
    for key in ("config", "summary", "events"):
        with (directory / f"{key}.json").open("w", encoding="utf-8") as stream:
            json.dump(result[key], stream, ensure_ascii=False,
                      indent=2, allow_nan=False)
    columns = ["time", "mode", "x", "y", "z", "speed", "battery",
               "target_index", "target_distance", "sensor_valid",
               "command_emitted", "virtual_latency", "wind_x", "wind_y",
               "wind_z", "wind_speed", "wind_estimate_speed",
               "wind_regime", "gust_factor"]
    with (directory / "trajectory.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        if result['samples'] and 'manual_axes' in result['samples'][0]:columns += ['heading_rad','manual_axes']
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["samples"])
    # 对摘要文本进行HTML 转义，报告不加载外部脚本。
    summary = result["summary"]
    table = "".join(f"<tr><th>{html.escape(str(k))}</th>"
                    f"<td>{html.escape(str(v))}</td></tr>"
                    for k, v in summary.items())
    rows = result["samples"]
    points = [(r["x"], r["y"]) for r in rows]
    extent = max([1.0] + [abs(v) for p in points for v in p])
    # 按固定间隔抽取轨迹绘图；CSV 保留全部采样记录。
    stride = max(1, len(points) // 2000)
    sampled = points[::stride]
    if points:
        sampled.append(points[-1])
    coords = " ".join(f"{300 + x / extent * 260:.2f},"
                      f"{300 - y / extent * 260:.2f}" for x, y in sampled)
    page = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<title>巡检仿真报告</title><style>body{font-family:sans-serif;"
            "max-width:960px;margin:32px auto}td,th{padding:6px;"
            "border:1px solid #ddd}table{border-collapse:collapse}</style>"
            "<h1>多风环境具身智能无人机巡检报告</h1>"
            "<p>本次仿真的风场、控制与节点时延结果。</p>"
            f"<table>{table}</table><h2>水平轨迹</h2>"
            "<svg viewBox='0 0 600 600' width='600' height='600'>"
            "<path d='M40 300H560M300 40V560' stroke='#ccc'/>"
            f"<polyline points='{coords}' fill='none' stroke='#165b91' "
            "stroke-width='2'/></svg></html>")
    (directory / "report.html").write_text(page, encoding="utf-8")
def load_config(path: Path | None) -> Config:
    if path is None:
        return Config.from_dict({})
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("配置文件不能超过 1MB")
    with path.open(encoding="utf-8-sig") as stream:
        return Config.from_dict(json.load(stream))
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=SOFTWARE_NAME)
    parser.add_argument("--config", type=Path, help="JSON 仿真配置路径")
    parser.add_argument("--output", type=Path, help="尚不存在的结果目录")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.output is not None and args.output.exists():
            raise ValueError("结果目录已存在，请更换 --output 路径")
        result = run_simulation(cfg)
        if args.output is not None:
            write_report(result, args.output)
            # 本地运行日志：与结果文件放在同一目录，逐次追加。
            summary = result["summary"]
            with (args.output / "仿真日志.log").open("a", encoding="utf-8") as stream:
                stream.write(
                    f"{datetime.now():%Y-%m-%d %H:%M:%S} "
                    f"配置={args.config or '默认'} 状态={summary['status']} "
                    f"航点={summary['visited']}/{summary['total_waypoints']} "
                    f"时长={summary['elapsed']}s 采样={summary['samples']} "
                    f"完整完成={summary['mission_complete']}\n")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        return 0  # 程序执行成功；是否完成巡检需查看任务摘要
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        print(f"运行失败: {exc}", file=sys.stderr)
        return 2  # 配置或文件操作失败
if __name__ == "__main__":
    code = main()
    # 打包为可执行文件且双击运行（无命令行参数）时，等待按键以便查看结果。
    if getattr(sys, "frozen", False) and len(sys.argv) == 1:
        try:
            input("计算已完成，按回车键关闭窗口。")
        except (EOFError, OSError):
            pass
    raise SystemExit(code)
