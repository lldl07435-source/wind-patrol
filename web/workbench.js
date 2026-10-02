"use strict";
const $ = (id) => document.getElementById(id);
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const states = {
  pending: "待复核",
  confirmed: "已确认",
  assigned: "处理中",
  resolved: "待验收",
  closed: "已关闭",
  rejected: "已驳回",
};
const actions = {
  confirm: "确认缺陷",
  reject: "驳回",
  dispatch: "生成工单",
  resolve: "提交处理结果",
  accept: "验收关闭",
  return: "退回处理",
  reopen: "重新复核",
  create: "登记",
};
const allowed = {
  pending: ["confirm", "reject"],
  confirmed: ["dispatch"],
  assigned: ["resolve"],
  resolved: ["accept", "return"],
  closed: ["reopen"],
  rejected: ["reopen"],
};
let token = "",
  scenarios = [],
  tasks = [],
  workflow = { assets: [], defects: [], events: [] },
  reports = [],
  pendingTransition = null;
let loadSequence = 0;
function notify(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
}
async function request(path, data) {
  const options =
    data === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": token,
          },
          body: JSON.stringify(data),
        };
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "请求失败，请刷新后核查");
  return payload;
}
const n = (value, digits = 2) =>
  value == null ? "无数据" : Number(value).toFixed(digits);
function stat(label, value) {
  return `<div class="stat"><small>${escapeHTML(label)}</small><strong>${escapeHTML(value)}</strong></div>`;
}
function table(headers, rows) {
  if (!rows.length)
    return '<div class="empty">暂无记录，请先完成上方操作。</div>';
  return `<table><thead><tr>${headers.map((h) => `<th>${escapeHTML(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
function downloadLink(id) {
  return `<a href="/api/tasks/${encodeURIComponent(id)}/download">下载证据</a>`;
}
function renderHistory() {
  $("history-stats").innerHTML =
    stat("已保存任务", tasks.length) +
    stat("巡检完成", tasks.filter((t) => t.summary.mission_complete).length) +
    stat("未完成任务", tasks.filter((t) => !t.summary.mission_complete).length);
  const filter = $("history-filter").value.trim().toLowerCase();
  $("history-table").innerHTML = table(
    [
      "任务名称 / 编号",
      "最终状态",
      "完成航点",
      "仿真时长",
      "创建时间 UTC",
      "证据",
    ],
    tasks
      .filter((t) => (t.name + t.id).toLowerCase().includes(filter))
      .map((t) => [
        `${escapeHTML(t.name)}<small>${escapeHTML(t.id)}</small>`,
        `<span class="badge">${escapeHTML(t.summary.status)}</span>`,
        `${t.summary.visited} / ${t.summary.total_waypoints}`,
        `${n(t.summary.elapsed)} s`,
        escapeHTML(t.created),
        downloadLink(t.id),
      ]),
  );
}
function renderWorkflow() {
  const oldAsset = $("asset-select").value,
    oldTask = $("task-select").value;
  $("asset-select").innerHTML =
    '<option value="">请选择已登记资产</option>' +
    workflow.assets
      .map(
        (a) =>
          `<option value="${a.id}">${escapeHTML(a.code + " · " + a.name)}</option>`,
      )
      .join("");
  $("task-select").innerHTML =
    '<option value="">请选择已保存任务</option>' +
    tasks
      .map((t) => `<option value="${t.id}">${escapeHTML(t.name)}</option>`)
      .join("");
  if (workflow.assets.some((a) => a.id === oldAsset))
    $("asset-select").value = oldAsset;
  if (tasks.some((t) => t.id === oldTask)) $("task-select").value = oldTask;
  $("workflow-stats").innerHTML =
    stat("登记资产", workflow.assets.length) +
    stat(
      "待复核缺陷",
      workflow.defects.filter((d) => d.status === "pending").length,
    ) +
    stat(
      "待验收工单",
      workflow.defects.filter((d) => d.status === "resolved").length,
    );
  $("defect-table").innerHTML = table(
    ["问题 / 资产", "关联任务", "状态 / 版本", "工单编号", "操作"],
    workflow.defects.map((d) => [
      `${escapeHTML(d.title)}<small>${escapeHTML(d.asset_code)} · ${{ low: "低", medium: "中", high: "高" }[d.severity]}风险</small>`,
      downloadLink(d.task_id) + `<small>${escapeHTML(d.task_id)}</small>`,
      `<span class="badge">${states[d.status]}</span><small>版本 ${d.revision}</small>`,
      d.work_order
        ? `<span class="report-id">${escapeHTML(d.work_order)}</span>`
        : "尚未生成",
      (allowed[d.status] || [])
        .map(
          (a) =>
            `<button data-defect="${d.id}" data-action="${a}">${actions[a]}</button>`,
        )
        .join(""),
    ]),
  );
  const names = new Map(workflow.defects.map((d) => [d.id, d.title]));
  $("events").innerHTML =
    workflow.events
      .slice(0, 30)
      .map(
        (e) =>
          `<div><strong>${escapeHTML(names.get(e.defect_id))} · ${actions[e.action]}</strong><p>${escapeHTML(e.reason)}</p><small>${escapeHTML(e.created)} UTC · ${states[e.to_status]} · 版本 ${e.revision}</small></div>`,
      )
      .join("") || '<p class="empty">暂无处理记录</p>';
}
function renderReports() {
  $("comparison-results").innerHTML =
    reports
      .map(
        (r) =>
          `<article class="panel"><div class="panel-heading"><h2>配对实验结果</h2><span class="hint">${escapeHTML(r.created)}</span></div><div class="comparison-summary"><span class="badge">${r.seeds.length} 组配对</span>随机种子 ${r.seeds.join("、")}</div>${table(
            ["策略", "完成率", "平均仿真时长", "平均路径长度", "平均目标距离"],
            ["baseline", "adaptive"].map((label) => {
              const a = r.aggregates[label];
              return [
                label === "baseline" ? "基线控制" : "自适应控制",
                `${n(a.completion_rate * 100, 0)}%`,
                `${n(a.mean_elapsed_s)} s`,
                `${n(a.mean_path_length_m)} m`,
                a.mean_target_distance_m == null
                  ? "无数据"
                  : `${n(a.mean_target_distance_m)} m`,
              ];
            }),
          )}<details><summary>逐种子结果与任务证据</summary>${table(
            ["种子", "基线状态", "基线证据", "自适应状态", "自适应证据"],
            r.pairs.map((p) => [
              p.seed,
              escapeHTML(p.baseline.summary.status),
              downloadLink(p.baseline.task_id),
              escapeHTML(p.adaptive.summary.status),
              downloadLink(p.adaptive.task_id),
            ]),
          )}<pre>${escapeHTML(JSON.stringify(r.base_config, null, 2))}</pre><p class="report-id">配置 SHA-256 ${escapeHTML(r.config_sha256)}</p></details><p class="hint">${escapeHTML(r.interpretation)}</p><button data-report="${r.id}">下载完整实验 JSON</button></article>`,
      )
      .join("") ||
    '<div class="panel empty">尚未运行配对实验。选择场景后开始计算。</div>';
}
async function reload() {
  const sequence = ++loadSequence;
  const result = await Promise.all([
    request("/api/tasks"),
    request("/api/workflow"),
    request("/api/comparisons"),
  ]);
  // 只应用最近一次刷新，避免较早请求覆盖更新后的状态。
  if (sequence !== loadSequence) return;
  [tasks, workflow, reports] = result;
  renderHistory();
  renderWorkflow();
  renderReports();
}
async function submit(form, operation) {
  const button = form.querySelector('button[type="submit"]');
  if (button.disabled) return;
  button.disabled = true;
  try {
    await operation();
  } catch (error) {
    notify(error.message, true);
    if ($("transition-dialog").open)
      $("transition-context").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}
document.querySelectorAll("nav [data-view]").forEach((button) =>
  button.addEventListener("click", () => {
    document
      .querySelectorAll(".view")
      .forEach((view) => (view.hidden = view.id !== button.dataset.view));
    document.querySelectorAll("nav button").forEach((b) => {
      b.classList.toggle("selected", b === button);
      b.setAttribute("aria-current", b === button ? "page" : "false");
    });
  }),
);
$("refresh").addEventListener("click", () =>
  reload()
    .then(() => notify("数据已刷新"))
    .catch((e) => notify(e.message, true)),
);
$("history-filter").addEventListener("input", renderHistory);
$("asset-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit(event.target, async () => {
    const asset = await request(
      "/api/workflow/assets",
      Object.fromEntries(new FormData(event.target)),
    );
    event.target.reset();
    await reload();
    $("asset-select").value = asset.id;
    notify("资产已保存，可登记关联缺陷");
  });
});
$("defect-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit(event.target, async () => {
    await request(
      "/api/workflow/defects",
      Object.fromEntries(new FormData(event.target)),
    );
    event.target.reset();
    await reload();
    notify("缺陷已进入待复核状态");
  });
});
$("defect-table").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-defect]");
  if (!button) return;
  const defect = workflow.defects.find((d) => d.id === button.dataset.defect);
  pendingTransition = {
    id: defect.id,
    revision: defect.revision,
    action: button.dataset.action,
  };
  $("transition-title").textContent = actions[button.dataset.action];
  $("transition-context").textContent =
    defect.title + " · 当前" + states[defect.status];
  $("transition-reason").value = "";
  $("transition-dialog").showModal();
});
$("cancel-transition").addEventListener("click", () =>
  $("transition-dialog").close(),
);
$("transition-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit(event.target, async () => {
    await request("/api/workflow/transition", {
      ...pendingTransition,
      reason: $("transition-reason").value,
    });
    $("transition-dialog").close();
    await reload();
    notify("状态已更新，处理依据已保存");
  });
});
function scenarioChanged() {
  const s = scenarios.find((s) => s.id === $("scenario-select").value);
  $("scenario-description").textContent = s.description;
  $("config-preview").textContent = JSON.stringify(s.config, null, 2);
}
$("scenario-select").addEventListener("change", scenarioChanged);
$("compare-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit(event.target, async () => {
    const values = $("seeds")
      .value.split(/[,，]/)
      .map((s) => s.trim());
    if (values.some((s) => !/^\d+$/.test(s)))
      throw new Error("种子必须为整数，以逗号分隔");
    const seeds = values.map(Number),
      scenario = scenarios.find((s) => s.id === $("scenario-select").value);
    notify("正在计算配对任务，请等待结果。请勿重复提交。");
    await request("/api/comparisons", { config: scenario.config, seeds });
    await reload();
    notify("配对实验已完成，任务与实验报告已共同保存");
  });
});
$("comparison-results").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-report]");
  if (!button) return;
  const report = reports.find((r) => r.id === button.dataset.report);
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "paired-experiment.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
async function init() {
  try {
    const bootstrap = await request("/api/bootstrap");
    token = bootstrap.token;
    scenarios = bootstrap.scenarios;
    $("scenario-select").innerHTML = scenarios
      .map((s) => `<option value="${s.id}">${escapeHTML(s.name)}</option>`)
      .join("");
    scenarioChanged();
    await reload();
  } catch (error) {
    notify(error.message, true);
  }
}
init();
