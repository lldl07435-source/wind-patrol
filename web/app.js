"use strict";

// 所有界面状态仅保存在当前浏览器会话，不写入远程服务。
const state = {
  config: null,
  result: null,
  tasks: [],
  scenarios: [],
  token: "",
  page: "overview",
  frame: 0,
  timer: null,
  busy: false,
  resultRequest: 0,
};
const $ = (id) => document.getElementById(id);
const clone = (value) => JSON.parse(JSON.stringify(value));
const labels = {
  overview: "任务态势",
  wind: "风场感知",
  scene: "策略配置",
  route: "航线规划",
  flight: "轨迹回放",
  sensor: "观测与控制",
  nodes: "具身智能闭环",
  events: "安全事件",
  compare: "任务对比",
  reports: "结果归档",
  help: "使用帮助",
};
const windLabels = {
  CALM: "平稳",
  STEADY: "持续风",
  GUST: "阵风",
  TURBULENT: "紊流",
  LIMIT: "超限",
};
const modes = {
  PATROL: "巡检",
  RETURN: "返航",
  LAND: "降落",
  DONE: "降落完成",
  ABORTED: "异常中止",
  TIMEOUT: "时长上限",
  START: "任务启动",
  WAYPOINT: "航点完成",
};
const groups = [
  [
    "时间与观测",
    [
      ["dt", "仿真步长 s", 0.01, 0.2, 0.01],
      ["duration", "时长上限 s", 0.01, 3600, 1],
      ["seed", "随机种子", 0, 4294967295, 1],
      ["noise_std", "位置噪声 m", 0, 5, 0.01],
      ["dropout_start", "中断开始 s", 0, 3600, 0.1],
      ["dropout_duration", "中断持续 s", 0, 3600, 0.1],
      ["sensor_timeout", "观测超时 s", 0.1, 30, 0.1],
    ],
  ],
  [
    "运动与环境",
    [
      ["max_speed", "最大速度 m/s", 0.1, 20, 0.1],
      ["max_accel", "最大指令加速度 m/s²", 0.1, 20, 0.1],
      ["arrival_radius", "航点容差 m", 0.1, 3, 0.1],
      ["geofence", "球形围栏半径 m", 5, 1000, 1],
      ["wind.0", "东向风速 m/s", -20, 20, 0.1],
      ["wind.1", "北向风速 m/s", -20, 20, 0.1],
      ["wind.2", "上向风速 m/s", -20, 20, 0.1],
    ],
  ],
  [
    "多风环境策略",
    [
      ["gust_amplitude", "阵风幅值 m/s", 0, 20, 0.1],
      ["gust_period", "阵风周期 s", 0.5, 120, 0.1],
      ["turbulence_intensity", "紊流强度 0至1", 0, 1, 0.01],
      ["max_operating_wind", "安全风速上限 m/s", 0.5, 30, 0.1],
    ],
  ],
  [
    "电量与控制",
    [
      ["initial_battery", "初始电量 0至1", 0, 1, 0.01],
      ["battery_rate", "基础耗电率 /s", 0, 0.1, 0.0001],
      ["return_threshold", "返航电量阈值", 0.01, 0.9, 0.01],
      ["critical_threshold", "临界电量阈值", 0, 0.8, 0.01],
      ["kp", "位置比例增益 Kp", 0, 10, 0.1],
      ["ki", "位置积分增益 Ki", 0, 2, 0.01],
      ["kd", "速度反馈增益 Kd", 0, 10, 0.1],
      ["event_threshold", "指令更新阈值", 0, 5, 0.01],
      ["max_hold", "最长保持时间 s", 0.01, 2, 0.01],
    ],
  ],
];

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text; // 不把用户输入解释为HTML。
  if (className) node.className = className;
  return node;
}

function notice(text, error = false) {
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
}

async function api(path, body) {
  const options = { headers: {} };
  if (body !== undefined) {
    options.method = "POST";
    options.headers = {
      "Content-Type": "application/json",
      "X-CSRFToken": state.token,
    };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok)
    throw new Error(value.error || `请求失败 ${response.status}`);
  return value;
}

function action(fn) {
  return async (...args) => {
    try {
      await fn(...args);
    } catch (error) {
      notice(error.message || "操作失败", true);
    }
  };
}

function numberText(value, digits = 2) {
  return value === null || value === undefined
    ? "无采样"
    : Number(value).toFixed(digits);
}

function cards(target, data) {
  const container = $(target);
  container.replaceChildren();
  data.forEach(([label, value, note]) => {
    const card = el("div", undefined, "card");
    card.append(el("div", label, "label"), el("div", value, "value"));
    if (note) card.append(el("div", note, "note"));
    container.append(card);
  });
}

function table(target, headers, rows) {
  const node = el("table");
  const head = el("thead");
  const tr = el("tr");
  headers.forEach((text) => tr.append(el("th", text)));
  head.append(tr);
  const body = el("tbody");
  rows.forEach((values) => {
    const row = el("tr");
    values.forEach((value) => {
      const cell = el("td");
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value;
      row.append(cell);
    });
    body.append(row);
  });
  if (!rows.length) {
    const row = el("tr");
    const cell = el("td", "暂无记录");
    cell.colSpan = headers.length;
    row.append(cell);
    body.append(row);
  }
  node.append(head, body);
  $(target).replaceChildren(node);
}

function detail(target, entries) {
  const list = el("dl");
  entries.forEach(([key, value]) =>
    list.append(el("dt", key), el("dd", value)),
  );
  $(target).replaceChildren(list);
}

function button(text, handler) {
  const node = el("button", text);
  node.type = "button";
  node.addEventListener("click", action(handler));
  return node;
}

function showPage(name) {
  state.page = name;
  document
    .querySelectorAll(".page")
    .forEach((node) => node.classList.toggle("active", node.id === name));
  document
    .querySelectorAll("nav button")
    .forEach((node) =>
      node.classList.toggle("active", node.dataset.page === name),
    );
  $("page-title").textContent = labels[name];
  renderResult();
  if (name === "route") drawRoute();
}

function stopPlayback() {
  clearInterval(state.timer);
  state.timer = null;
  $("play").textContent = "播放回放";
}

function getConfigField(key) {
  const parts = key.split(".");
  return parts.length === 2
    ? state.config[parts[0]][Number(parts[1])]
    : state.config[key];
}

function setConfigField(key, value) {
  const parts = key.split(".");
  if (parts.length === 2) state.config[parts[0]][Number(parts[1])] = value;
  else state.config[key] = value;
}

function updateJSON() {
  $("json-config").value = JSON.stringify(state.config, null, 2);
}

function renderParameters() {
  const target = $("parameter-groups");
  target.replaceChildren();
  groups.forEach(([title, fields]) => {
    const section = el("article");
    section.append(el("h2", title));
    const grid = el("div", undefined, "form-grid");
    fields.forEach(([key, label, min, max, step]) => {
      const field = el("div", undefined, "field");
      const labelNode = el("label", label);
      const input = el("input");
      input.type = "number";
      input.min = min;
      input.max = max;
      input.step = step;
      input.id = `param-${key}`;
      labelNode.htmlFor = input.id;
      input.value = getConfigField(key);
      input.addEventListener("change", () => {
        // 空输入保留为null，以便服务端明确拒绝而不是悄悄转换为0。
        setConfigField(key, input.value === "" ? null : Number(input.value));
        updateJSON();
        notice("配置已修改，请重新校验并运行；当前结果仍属于上一次任务。");
      });
      field.append(labelNode, input, el("small", `${key} · ${min} 至 ${max}`));
      grid.append(field);
    });
    section.append(grid);
    target.append(section);
  });
  updateJSON();
}

function useScenario(key) {
  const scenario = state.scenarios.find((item) => item.id === key);
  state.config = clone(scenario.config);
  $("task-name").value = scenario.name;
  renderParameters();
  renderRoute();
  notice(`已载入“${scenario.name}”。${scenario.description} 请点击运行仿真。`);
}

function renderScenarios() {
  $("scenario-cards").replaceChildren();
  state.scenarios.forEach((scenario) => {
    const node = button("", () => useScenario(scenario.id));
    node.className = "scenario";
    node.dataset.scenario = scenario.id;
    node.append(el("strong", scenario.name), el("small", scenario.description));
    $("scenario-cards").append(node);
  });
}

function editItem(kind, index = null) {
  const waypoint = kind === "waypoints";
  const list = state.config[kind];
  const item =
    index === null
      ? waypoint
        ? [0, 0, 5]
        : { center: [5, 5, 5], radius: 1 }
      : list[index];
  const values = waypoint ? item : [...item.center, item.radius];
  $("edit-title").textContent =
    `${index === null ? "新增" : "编辑"}${waypoint ? "航点" : "障碍物"}`;
  $("edit-fields").replaceChildren();
  ["东向 X", "北向 Y", "高度 Z", "半径"]
    .slice(0, values.length)
    .forEach((name, i) => {
      const field = el("div", undefined, "field");
      const label = el("label", name + " m");
      const input = el("input");
      input.type = "number";
      input.step = "any";
      input.required = true;
      input.value = values[i];
      input.id = `edit-${i}`;
      label.htmlFor = input.id;
      field.append(label, input);
      $("edit-fields").append(field);
    });
  $("edit-form").onsubmit = action(async (event) => {
    event.preventDefault();
    const parsed = values.map((_, i) => Number($(`edit-${i}`).value));
    if (parsed.some((value) => !Number.isFinite(value)))
      throw new Error("坐标必须为有限数值");
    const updated = waypoint
      ? parsed
      : { center: parsed.slice(0, 3), radius: parsed[3] };
    const candidate = clone(state.config);
    if (index === null) candidate[kind].push(updated);
    else candidate[kind][index] = updated;
    await api("/api/validate", { config: candidate });
    state.config = candidate;
    $("edit-dialog").close();
    updateJSON();
    renderRoute();
    notice("已保存并通过配置校验。重新运行后才会产生新结果。");
  });
  $("edit-dialog").showModal();
}

function renderRoute() {
  const actions = (kind, index) => {
    const box = el("div");
    box.append(button("编辑", () => editItem(kind, index)));
    box.append(
      button("删除", () => {
        if (kind === "waypoints" && state.config.waypoints.length === 1)
          throw new Error("至少保留一个航点");
        if (!confirm("确认删除当前条目？此操作只修改未运行的配置。")) return;
        state.config[kind].splice(index, 1);
        renderRoute();
        updateJSON();
      }),
    );
    if (kind === "waypoints" && index > 0)
      box.append(
        button("上移", () => {
          const points = state.config.waypoints;
          [points[index - 1], points[index]] = [
            points[index],
            points[index - 1],
          ];
          renderRoute();
          updateJSON();
        }),
      );
    return box;
  };
  table(
    "waypoint-table",
    ["序号", "X m", "Y m", "Z m", "操作"],
    state.config.waypoints.map((point, i) => [
      i + 1,
      ...point,
      actions("waypoints", i),
    ]),
  );
  table(
    "obstacle-table",
    ["序号", "中心 X Y Z", "半径 m", "操作"],
    state.config.obstacles.map((item, i) => [
      i + 1,
      item.center.join(", "),
      item.radius,
      actions("obstacles", i),
    ]),
  );
  drawRoute();
}

function plotPath(
  canvas,
  cfg,
  samples = [],
  projection = "xy",
  frame = samples.length - 1,
) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width,
    h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.font = "16px Microsoft YaHei";
  const axes = { xy: [0, 1], xz: [0, 2], yz: [1, 2] }[projection];
  const names = ["x", "y", "z"];
  const all = [
    [0, 0, 0],
    ...cfg.waypoints,
    ...samples.map((row) => [row.x, row.y, row.z]),
  ];
  cfg.obstacles.forEach((item) => {
    all.push(
      item.center.map((v) => v - item.radius),
      item.center.map((v) => v + item.radius),
    );
  });
  const xs = all.map((p) => p[axes[0]]),
    ys = all.map((p) => p[axes[1]]);
  const minX = Math.min(...xs) - 2,
    maxX = Math.max(...xs) + 2;
  const minY = Math.min(...ys) - 2,
    maxY = Math.max(...ys) + 2;
  const scale = Math.min((w - 100) / (maxX - minX), (h - 85) / (maxY - minY));
  const map = (point) => [
    60 + (point[axes[0]] - minX) * scale,
    h - 45 - (point[axes[1]] - minY) * scale,
  ];
  ctx.strokeStyle = "#e2eaf1";
  ctx.fillStyle = "#657c90";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i++) {
    const x = minX + (i * (maxX - minX)) / 5;
    const y = minY + (i * (maxY - minY)) / 5;
    const px = 60 + (x - minX) * scale,
      py = h - 45 - (y - minY) * scale;
    ctx.beginPath();
    ctx.moveTo(px, 25);
    ctx.lineTo(px, h - 45);
    ctx.stroke();
    ctx.fillText(x.toFixed(1), px - 10, h - 20);
    ctx.beginPath();
    ctx.moveTo(60, py);
    ctx.lineTo(w - 20, py);
    ctx.stroke();
    ctx.fillText(y.toFixed(1), 8, py + 5);
  }
  ctx.fillText(`${names[axes[0]].toUpperCase()} / m`, w - 85, h - 5);
  ctx.fillText(`${names[axes[1]].toUpperCase()} / m`, 10, 18);
  cfg.obstacles.forEach((item) => {
    const [x, y] = map(item.center);
    ctx.beginPath();
    ctx.arc(x, y, item.radius * scale, 0, Math.PI * 2);
    ctx.fillStyle = "#efb46b77";
    ctx.fill();
    ctx.strokeStyle = "#ce883b";
    ctx.stroke();
  });
  ctx.setLineDash([7, 5]);
  ctx.strokeStyle = "#9bb7d0";
  ctx.lineWidth = 2;
  ctx.beginPath();
  [[0, 0, 0], ...cfg.waypoints].forEach((point, i) => {
    const [x, y] = map(point);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.setLineDash([]);
  const projectedLabels = new Map();
  cfg.waypoints.forEach((point, i) => {
    const [x, y] = map(point);
    ctx.fillStyle = "#527994";
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();
    const key = `${x.toFixed(2)},${y.toFixed(2)}`;
    const existing = projectedLabels.get(key) || { x, y, names: [] };
    existing.names.push(`P${i + 1}`);
    projectedLabels.set(key, existing);
  });
  projectedLabels.forEach((item) => {
    ctx.fillText(item.names.join("/"), item.x + 9, item.y - 10);
  });
  const [ox, oy] = map([0, 0, 0]);
  ctx.fillStyle = "#203548";
  ctx.fillRect(ox - 4, oy - 4, 8, 8);
  if (!samples.length) return;
  ctx.beginPath();
  ctx.strokeStyle = "#087cab";
  ctx.lineWidth = 3;
  samples.slice(0, frame + 1).forEach((row, i) => {
    const [x, y] = map([row.x, row.y, row.z]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  const row = samples[frame];
  if (row) {
    const [x, y] = map([row.x, row.y, row.z]);
    ctx.fillStyle = "#e1842b";
    ctx.beginPath();
    ctx.arc(x, y, 7, 0, Math.PI * 2);
    ctx.fill();
  }
}

function drawRoute() {
  if (state.config) plotPath($("route-canvas"), state.config);
}

function chart(id, series) {
  const canvas = $(id),
    ctx = canvas.getContext("2d");
  const w = canvas.width,
    h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.font = "15px Microsoft YaHei";
  const rows = state.result?.samples || [];
  if (!rows.length) {
    ctx.fillStyle = "#6c8091";
    ctx.fillText("暂无运动采样，请先运行仿真。", 25, 50);
    return;
  }
  const maxT = Math.max(rows[rows.length - 1].time, 0.01);
  const values = series.flatMap((item) =>
    rows.map((row) => Number(row[item.key]) * (item.scale || 1)),
  );
  const maxV = Math.max(1, ...values) * 1.12;
  ctx.strokeStyle = "#e0e8ef";
  ctx.fillStyle = "#647a8c";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = h - 35 - (i * (h - 60)) / 4;
    ctx.beginPath();
    ctx.moveTo(55, y);
    ctx.lineTo(w - 20, y);
    ctx.stroke();
    ctx.fillText(((i * maxV) / 4).toFixed(1), 5, y + 5);
    const x = 55 + (i * (w - 80)) / 4;
    ctx.fillText(((i * maxT) / 4).toFixed(1), x - 10, h - 12);
  }
  series.forEach((item) => {
    ctx.beginPath();
    ctx.strokeStyle = item.color;
    ctx.lineWidth = 2;
    rows.forEach((row, i) => {
      const x = 55 + (row.time / maxT) * (w - 80);
      const y =
        h -
        35 -
        ((Number(row[item.key]) * (item.scale || 1)) / maxV) * (h - 60);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
  ctx.fillText("时间 s", w - 65, h - 2);
}

function drawWindChart() {
  const canvas = $("wind-chart"), ctx = canvas.getContext("2d");
  const rows = state.result?.samples || [];
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.font = "14px Microsoft YaHei";
  if (!rows.length) {
    ctx.fillStyle = "#6c8091";
    ctx.fillText("请运行一个多风场景以生成风场曲线。", 28, 52);
    return;
  }
  const maxT = Math.max(rows.at(-1).time, 0.01);
  const threshold = state.result.config.max_operating_wind;
  const maxV = Math.max(threshold * 1.08, ...rows.map((r) => r.wind_speed)) * 1.08;
  const mapX = (t) => 58 + (t / maxT) * (w - 82);
  const mapY = (v) => h - 38 - (v / maxV) * (h - 68);
  ctx.strokeStyle = "#dce8eb";
  ctx.fillStyle = "#607780";
  for (let i = 0; i <= 4; i += 1) {
    const value = (maxV * i) / 4, y = mapY(value);
    ctx.beginPath(); ctx.moveTo(58, y); ctx.lineTo(w - 24, y); ctx.stroke();
    ctx.fillText(value.toFixed(1), 10, y + 4);
  }
  const line = (key, color) => {
    ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 2.5;
    rows.forEach((row, index) => {
      const x = mapX(row.time), y = mapY(row[key]);
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  };
  line("wind_speed", "#10a8a4");
  line("wind_estimate_speed", "#ef8f32");
  ctx.save(); ctx.setLineDash([8, 7]); ctx.strokeStyle = "#c45151";
  ctx.beginPath(); ctx.moveTo(58, mapY(threshold)); ctx.lineTo(w - 24, mapY(threshold)); ctx.stroke(); ctx.restore();
}

function renderFrame() {
  const result = state.result;
  if (!result) {
    $("frame-label").textContent = "请先运行仿真";
    return;
  }
  const rows = result.samples;
  $("timeline").max = Math.max(0, rows.length - 1);
  $("timeline").value = state.frame;
  plotPath(
    $("flight-canvas"),
    result.config,
    rows,
    $("projection").value,
    state.frame,
  );
  const row = rows[state.frame];
  $("frame-label").textContent = row
    ? `仿真时刻 ${numberText(row.time)} s · 绘图采样 ${state.frame + 1} / ${rows.length} · ${modes[row.mode]}`
    : "任务在运动前中止，没有采样记录";
  detail(
    "frame-detail",
    row
      ? [
          ["时间 s", numberText(row.time)],
          ["状态", `${row.mode} ${modes[row.mode]}`],
          [
            "位置 X Y Z m",
            [row.x, row.y, row.z].map((v) => numberText(v)).join(" / "),
          ],
          ["速度 m/s", numberText(row.speed)],
          ["实际风速 m/s", numberText(row.wind_speed)],
          ["风况等级", `${row.wind_regime} ${windLabels[row.wind_regime] || ""}`],
          ["阵风因子", numberText(row.gust_factor)],
          ["剩余电量", numberText(row.battery * 100) + "%"],
          ["观测有效", row.sensor_valid ? "是" : "否"],
          ["指令更新", row.command_emitted ? "是" : "否"],
          ["虚拟时延 ms", numberText(row.virtual_latency * 1000)],
        ]
      : [["运动采样", "0"]],
  );
  detail("flight-summary", [
    ["最终状态", result.summary.status],
    ["全部巡检完成", result.summary.mission_complete ? "是" : "否"],
    [
      "完成航点",
      `${result.summary.visited} / ${result.summary.total_waypoints}`,
    ],
    ["最后事件", result.events.at(-1)?.detail || "无"],
  ]);
}

function renderResult() {
  const result = state.result,
    summary = result?.summary,
    m = result?.metrics;
  cards("summary-cards", [
    [
      "任务状态",
      summary ? modes[summary.status] : "待运行",
      summary?.status || "选择内置场景开始",
    ],
    [
      "完成航点",
      summary ? `${summary.visited} / ${summary.total_waypoints}` : "—",
      "按顺序到达计数",
    ],
    [
      "仿真时长",
      summary ? numberText(summary.elapsed) + " s" : "—",
      "不是墙钟运行耗时",
    ],
    [
      "剩余电量",
      summary ? numberText(summary.battery_remaining * 100) + "%" : "—",
      "归一化电量模型",
    ],
  ]);
  const finalWind = result?.samples?.at(-1);
  const windRegime = finalWind?.wind_regime || "CALM";
  cards("wind-cards", [
    ["当前风况", result ? windLabels[windRegime] : "待运行", windRegime],
    ["最大风速", summary ? numberText(summary.max_wind_speed) + " m/s" : "—", "仿真区间峰值"],
    ["平均风速", summary ? numberText(summary.mean_wind_speed) + " m/s" : "—", "三维风矢量模长"],
    ["估计误差", m?.mean_wind_estimation_error_mps != null ? numberText(m.mean_wind_estimation_error_mps, 3) + " m/s" : "—", "实际与估计风速"],
  ]);
  const badge = $("wind-badge");
  badge.textContent = result ? windLabels[windRegime] : "待运行";
  badge.classList.toggle("limit", windRegime === "LIMIT");
  const strategy = windRegime === "LIMIT"
    ? ["暂停任务", "冻结证据链", "就近安全处置"]
    : windRegime === "GUST" || windRegime === "TURBULENT"
      ? ["降低地速至72%", "提高采样频率", "限制姿态变化率"]
      : windRegime === "STEADY"
        ? ["启用迎风补偿", "延长悬停拍摄", "持续校核电量"]
        : ["按计划航速", "标准采样频率", "持续监测风况"];
  $("wind-strategy").innerHTML = `<div class="strategy-card">
    <div class="strategy-row"><b>飞行策略</b><span>${strategy[0]}</span></div>
    <div class="strategy-row"><b>采集策略</b><span>${strategy[1]}</span></div>
    <div class="strategy-row"><b>安全策略</b><span>${strategy[2]}</span></div>
    <div class="strategy-row"><b>自适应控制</b><span>${result?.config?.adaptive_control === false ? "关闭" : "启用"}</span></div>
  </div>`;
  drawWindChart();
  renderFrame();
  cards("sensor-cards", [
    [
      "观测有效比例",
      m?.sensor_availability != null
        ? numberText(m.sensor_availability * 100) + "%"
        : "—",
    ],
    [
      "指令更新比例",
      m?.command_update_ratio != null
        ? numberText(m.command_update_ratio * 100) + "%"
        : "—",
    ],
    ["轨迹长度", m ? numberText(m.path_length_m) + " m" : "—"],
    ["最大高度", m ? numberText(m.max_altitude_m) + " m" : "—"],
  ]);
  chart("motion-chart", [
    { key: "speed", color: "#197aaa" },
    { key: "z", color: "#d98b32" },
  ]);
  chart("distance-chart", [{ key: "target_distance", color: "#197aaa" }]);
  chart("sensor-chart", [
    { key: "sensor_valid", color: "#197aaa" },
    { key: "command_emitted", color: "#d98b32" },
  ]);
  chart("latency-chart", [
    { key: "virtual_latency", color: "#197aaa", scale: 1000 },
  ]);
  cards("node-cards", [
    [
      "闭环最大时延",
      summary ? numberText(summary.virtual_max_latency * 1000) + " ms" : "—",
    ],
    ["P95虚拟时延", m ? numberText(m.p95_virtual_latency_ms) + " ms" : "—"],
    ["闭环超期次数", summary ? String(summary.virtual_deadline_misses) : "—"],
    ["总采样数", summary ? String(summary.samples) : "—"],
  ]);
  table(
    "node-table",
    ["具身节点", "单任务服务时长", "执行次数"],
    ["GPU", "CPU", "FCU"].map((node, i) => [
      ["感知融合", "智能决策", "自适应执行"][i],
      [6, 3, 1][i] + " ms",
      summary?.virtual_node_jobs[node] ?? "—",
    ]),
  );
  const filter = $("event-filter").value;
  const events = (result?.events || []).filter(
    (e) => filter === "all" || e.kind === filter,
  );
  table(
    "event-table",
    ["仿真时间 s", "事件代码", "类别", "记录内容"],
    events.map((e) => [
      numberText(e.time),
      e.kind,
      modes[e.kind] || e.kind,
      e.detail,
    ]),
  );
  $("summary-json").textContent = summary
    ? JSON.stringify(summary, null, 2)
    : "请先运行仿真。";
}

async function refreshTasks() {
  state.tasks = await api("/api/tasks");
  $("recent-tasks").replaceChildren();
  state.tasks.slice(0, 5).forEach((task) => {
    const row = el("div", undefined, "task-row");
    const text = el("div", task.name);
    text.append(
      el(
        "small",
        `${task.summary.status} · ${numberText(task.summary.elapsed)} s · ${task.summary.visited}/${task.summary.total_waypoints} 航点`,
      ),
    );
    row.append(
      text,
      button("查看", () => loadTask(task.id)),
    );
    $("recent-tasks").append(row);
  });
  if (!state.tasks.length)
    $("recent-tasks").append(
      el("p", "暂无任务。运行后将在这里显示。", "muted"),
    );
  table(
    "compare-table",
    [
      "任务名称",
      "状态",
      "巡检完成",
      "航点",
      "时长 s",
      "电量 %",
      "虚拟最大时延 ms",
      "操作",
    ],
    state.tasks.map((task) => [
      task.name,
      task.summary.status,
      task.summary.mission_complete ? "是" : "否",
      `${task.summary.visited}/${task.summary.total_waypoints}`,
      numberText(task.summary.elapsed),
      numberText(task.summary.battery_remaining * 100),
      numberText(task.summary.virtual_max_latency * 1000),
      button("查看结果", () => loadTask(task.id)),
    ]),
  );
}

async function loadTask(id) {
  const request = ++state.resultRequest;
  stopPlayback();
  $("export-location").textContent = "";
  const result = await api(`/api/tasks/${id}`);
  if (request !== state.resultRequest) return;
  state.result = result;
  state.frame = Math.max(0, state.result.samples.length - 1);
  renderResult();
  notice(
    `正在查看历史结果“${state.result.name}”；表单中的待运行配置保持不变。`,
  );
}

async function runTask() {
  if (state.busy) return;
  const request = ++state.resultRequest;
  stopPlayback();
  state.busy = true;
  $("run").disabled = true;
  $("run-state").textContent = "计算中……";
  notice("正在按仿真步长计算，请等待结果。");
  try {
    const result = await api("/api/run", {
      config: state.config,
      name: $("task-name").value,
    });
    await refreshTasks();
    $("run-state").textContent = `计算完成 · ${result.summary.status}`;
    if (request !== state.resultRequest) {
      notice(`“${result.name}”计算完成，可在任务对比中查看。`);
      return;
    }
    state.result = result;
    await openClassicTwin(result.id);
    showPage('flight');
    state.frame = Math.max(0, state.result.samples.length - 1);
    $("event-filter").value = "all";
    $("export-location").textContent = "";
    renderResult();
    notice(
      `“${state.result.name}”计算完成。${state.result.events.at(-1)?.detail || ""}。`,
    );
  } finally {
    state.busy = false;
    $("run").disabled = false;
    if ($("run-state").textContent === "计算中……")
      $("run-state").textContent = "运行失败";
  }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = el("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function requireResult() {
  if (!state.result) throw new Error("请先运行仿真或选择已有任务");
}

async function boot() {
  const data = await api("/api/bootstrap");
  state.token = data.token;
  state.scenarios = data.scenarios;
  $("software").textContent = `${data.software} ${data.version}`;
  const updateClock = () => {
    $("clock").textContent = new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(new Date());
  };
  updateClock();
  setInterval(updateClock, 1000);
  renderScenarios();
  useScenario("default");
  renderResult();
  await refreshTasks();
  document
    .querySelectorAll("nav button")
    .forEach((node) =>
      node.addEventListener("click", () => showPage(node.dataset.page)),
    );
  $("run").addEventListener("click", action(runTask));
  $("validate").addEventListener(
    "click",
    action(async () => {
      const result = await api("/api/validate", { config: state.config });
      notice(`${result.message} 最多 ${result.steps} 步。`);
    }),
  );
  $("reset-config").addEventListener("click", () => useScenario("default"));
  $("apply-json").addEventListener(
    "click",
    action(async () => {
      const candidate = JSON.parse($("json-config").value);
      await api("/api/validate", { config: candidate });
      // 补全省略字段，与后端Config的默认值保持一致。
      state.config = { ...clone(state.scenarios[0].config), ...candidate };
      renderParameters();
      renderRoute();
      notice("JSON已应用并通过校验。");
    }),
  );
  $("download-config").addEventListener("click", () =>
    downloadBlob(
      new Blob([JSON.stringify(state.config, null, 2)], {
        type: "application/json",
      }),
      "simulation-config.json",
    ),
  );
  $("import-config").addEventListener("click", () => $("config-file").click());
  $("config-file").addEventListener(
    "change",
    action(async (event) => {
      const file = event.target.files[0];
      if (!file) return;
      try {
        if (file.size > 1024 * 1024) throw new Error("配置文件不能超过1MB");
        const candidate = JSON.parse(
          (await file.text()).replace(/^\uFEFF/, ""),
        );
        await api("/api/validate", { config: candidate });
        state.config = { ...clone(state.scenarios[0].config), ...candidate };
        renderParameters();
        renderRoute();
        notice("配置文件已导入并通过校验。");
      } finally {
        event.target.value = "";
      }
    }),
  );
  $("add-waypoint").addEventListener("click", () => editItem("waypoints"));
  $("add-obstacle").addEventListener("click", () => editItem("obstacles"));
  $("cancel-edit").addEventListener("click", () => $("edit-dialog").close());
  $("projection").addEventListener("change", renderFrame);
  $("timeline").addEventListener("input", () => {
    stopPlayback();
    state.frame = Number($("timeline").value);
    renderFrame();
  });
  $("play").addEventListener(
    "click",
    action(() => {
      requireResult();
      if (!state.result.samples.length)
        throw new Error("当前任务没有运动采样，不能回放");
      if (state.timer) {
        stopPlayback();
        return;
      }
      if (state.frame >= state.result.samples.length - 1) state.frame = 0;
      $("play").textContent = "暂停回放";
      state.timer = setInterval(() => {
        state.frame = Math.min(
          state.frame + 3,
          state.result.samples.length - 1,
        );
        renderFrame();
        if (state.frame === state.result.samples.length - 1) stopPlayback();
      }, 50);
    }),
  );
  $("event-filter").addEventListener("change", renderResult);
  $("refresh-tasks").addEventListener("click", action(refreshTasks));
  $("download-result").addEventListener(
    "click",
    action(async () => {
      requireResult();
      const response = await fetch(`/api/tasks/${state.result.id}/download`);
      if (!response.ok) throw new Error("结果下载失败，请确认数据目录与任务编号");
      downloadBlob(await response.blob(), `simulation-${state.result.id}.zip`);
      notice("结果ZIP已交给浏览器下载，请检查浏览器下载列表。");
    }),
  );
  $("export-result").addEventListener(
    "click",
    action(async () => {
      requireResult();
      const resultId = state.result.id;
      const output = await api("/api/export", { id: resultId });
      if (!state.result || state.result.id !== resultId) {
        notice("原任务结果已导出；当前页面已切换到其他任务。");
        return;
      }
      const response = await fetch(output.download);
      if (!response.ok) throw new Error("导出未完成，请重试");
      downloadBlob(await response.blob(), `simulation-${resultId}.zip`);
      $("export-location").textContent = "结果已交给浏览器下载，请检查下载列表。";
      notice(output.message);
    }),
  );
}

action(boot)();

let ldClassicTwin,ldClassicTwinPoll;
async function openClassicTwin(runId){
  let host=document.getElementById('classic-twin');
  if(!host){host=document.createElement('section');host.id='classic-twin';const parent=document.getElementById('wind'==='ld'?'live':'flight');parent.prepend(host);}
  const {TwinPlayer}=await import('/twin-viewer.js');
  ldClassicTwin?.dispose();clearInterval(ldClassicTwinPoll);ldClassicTwin=new TwinPlayer(host,{domain:'wind'});
  if(runId)await ldClassicTwin.load(runId);else{await ldClassicTwin.live();ldClassicTwinPoll=setInterval(()=>ldClassicTwin.live(),160);}
  host.scrollIntoView({block:'start',behavior:'smooth'});
}
window.addEventListener('pagehide',()=>{ldClassicTwin?.dispose();clearInterval(ldClassicTwinPoll);});
