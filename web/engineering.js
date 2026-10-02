"use strict";
const PAGE_RENDERERS = {};
const ENGINEERING_PAGES = [
  {
    id: "cockpit",
    title: "任务驾驶舱",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "mission-create",
    title: "任务创建",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "assets",
    title: "电网资产",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "route-editor",
    title: "航线编辑",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "wind-twin",
    title: "风场数字孪生",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "wind-estimation",
    title: "风扰感知",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "flight-monitor",
    title: "飞行监控",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "control-analysis",
    title: "控制分析",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "dynamic-replan",
    title: "动态重规划",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "visible-inspection",
    title: "可见光巡检",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "thermal-inspection",
    title: "热成像巡检",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "defects",
    title: "缺陷诊断",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "review",
    title: "人工复核",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "work-orders",
    title: "缺陷工单",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "embodied-loop",
    title: "具身决策闭环",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "decision-trace",
    title: "决策解释",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "safety-center",
    title: "安全中心",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "telemetry",
    title: "遥测链路",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "replay",
    title: "历史回放",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "comparison",
    title: "任务对比",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "reports",
    title: "报告中心",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "archives",
    title: "数据归档",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "settings",
    title: "系统设置",
    description: "人工录入的主题记录与复核状态",
  },
  {
    id: "help",
    title: "帮助与版本",
    description: "人工录入的主题记录与复核状态",
  },
];
function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
}
function formatNumber(value) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(1) : "—";
}
function statusBadge(status) {
  const names = {
    active: "运行中",
    completed: "已完成",
    review: "待复核",
    paused: "已暂停",
    draft: "草稿",
    archived: "已归档",
  };
  return `<span class="status-badge ${escapeHtml(status)}">${names[status] || escapeHtml(status)}</span>`;
}
function metricCard(label, value, unit, trend) {
  const symbol = trend > 0 ? "↑" : trend < 0 ? "↓" : "→";
  return `<article class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}<small>${escapeHtml(unit)}</small></strong><em class="${trend > 0 ? "up" : trend < 0 ? "down" : "flat"}">${symbol} ${Math.abs(trend)}%</em></article>`;
}
function emptyState(message) {
  return `<div class="empty-state"><i>○</i><span>${escapeHtml(message)}</span></div>`;
}
function specializedPanel(pageId, model) {
  const count = model.rows.length;
  return `<article class="special-panel"><div class="special-head"><div><h3>本页记录</h3><p>当前主题已有 ${count} 条人工录入记录。下方列表与统计来自本机数据库。</p></div></div><div class="boundary-note">仿真轨迹、风估计和控制指标请在经典控制台运行任务后查看；本页不计算这些指标。</div></article>`;
}
function selectPageModel(state, pageId, subsystem) {
  const rows = (state?.records || []).filter((row) => row.page === pageId);
  const metrics = [
    { label: "记录总数", value: rows.length, unit: "项", trend: 0 },
    {
      label: "运行对象",
      value: rows.filter((row) => row.status === "active").length,
      unit: "项",
      trend: 0,
    },
    {
      label: "高风险记录",
      value: rows.filter((row) => row.risk >= 60).length,
      unit: "项",
      trend: 0,
    },
    {
      label: "平均风险",
      value: rows.length
        ? (rows.reduce((sum, row) => sum + row.risk, 0) / rows.length).toFixed(
            1,
          )
        : "—",
      unit: "分",
      trend: 0,
    },
  ];
  const alerts = rows
    .filter((row) => row.risk >= 60)
    .slice(0, 4)
    .map((row) => ({
      level: row.risk >= 80 ? "critical" : "warning",
      title: `${row.name} 风险升高`,
      detail: `风险评分 ${row.risk}，建议复核约束与观测证据`,
    }));
  const timeline = rows
    .slice(0, 6)
    .map((row) => ({
      title: row.name,
      detail: row.note || "记录已保存",
      time: row.updated + " UTC",
    }));
  return {
    metrics,
    rows,
    alerts,
    timeline,
    capabilities: [
      "创建业务记录",
      "字段校验",
      "本地数据库保存",
      "名称与状态筛选",
      "风险统计",
      "刷新后重新读取",
    ],
  };
}
function renderRecordPage(state, page, index) {
  const model = selectPageModel(state, page.id);
  const metrics = model.metrics.map(item => metricCard(item.label, item.value, item.unit, item.trend)).join("");
  const rows = model.rows.map(row => `<tr><td>${escapeHtml(row.name)}</td><td>${statusBadge(row.status)}</td><td>${formatNumber(row.risk)}</td><td>${escapeHtml(row.updated)}</td></tr>`).join("");
  const alerts = model.alerts.length
    ? model.alerts.map(item => `<li class="alert ${item.level}"><span>${escapeHtml(item.title)}</span><small>${escapeHtml(item.detail)}</small></li>`).join("")
    : emptyState("当前没有高风险记录");
  const steps = model.timeline.map((item, position) => `<li class="timeline-item"><i>${String(position + 1).padStart(2, "0")}</i><div><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.detail)}</span></div><time>${escapeHtml(item.time)}</time></li>`).join("");
  const title = escapeHtml(page.title);
  const id = escapeHtml(page.id);
  return `<section class="engineering-page" data-view="${id}">
    <div class="page-hero"><div><span class="eyebrow">ENGINEERING WORKSPACE · ${String(index + 1).padStart(2, "0")}</span><h2>${title}</h2><p>人工录入的主题记录与复核状态</p></div><div class="hero-actions"><button data-action="refresh">刷新数据</button><button class="primary" data-action="create">新建记录</button></div></div>
    <div class="metric-grid">${metrics}</div>
    ${specializedPanel(page.id, model)}
    <div class="workspace-grid"><article class="panel wide"><div class="panel-head"><div><h3>${title}记录</h3><p>列表来自本地数据库</p></div><label class="search">筛选<input data-filter="${id}" placeholder="输入名称或状态" /></label></div><div class="table-wrap"><table><thead><tr><th>对象</th><th>状态</th><th>风险</th><th>更新时间</th></tr></thead><tbody>${rows}</tbody></table></div></article>
    <article class="panel"><div class="panel-head"><div><h3>高分提醒</h3><p>最近四条评分不低于60分的记录</p></div></div><ul class="alert-list">${alerts}</ul></article></div>
    <div class="workspace-grid"><article class="panel"><div class="panel-head"><div><h3>最近记录</h3><p>按保存顺序显示最近六条</p></div></div><ol class="timeline">${steps}</ol></article>
    <article class="panel"><div class="panel-head"><div><h3>页面能力</h3><p>当前实现</p></div></div><div class="capability-list">${model.capabilities.map(item => `<div><i>✓</i><span>${escapeHtml(item)}</span></div>`).join("")}</div><div class="boundary-note">本页仅使用人工记录；仿真结果请到经典控制台查看。</div></article></div>
  </section>`;
}

ENGINEERING_PAGES.forEach((page, index) => {
  PAGE_RENDERERS[page.id] = state => renderRecordPage(state, page, index);
});
function renderEngineeringPage(pageId) {
  const renderer = PAGE_RENDERERS[pageId] || PAGE_RENDERERS.cockpit;
  const target = document.getElementById("engineering-content");
  if (!target) return;
  target.innerHTML = renderer(window.appState || {});
  const heading = target.querySelector(".page-hero h2");
  target.querySelector(".page-hero p").textContent =
    `${heading.textContent}事项记录与人工复核`;
  target
    .querySelectorAll(".boundary-note")
    .forEach(
      (el) =>
        (el.textContent =
          "本页用于录入和复核业务记录。运行仿真及导出轨迹请进入经典控制台。"),
    );
  // 统计与表格共用持久化记录，避免示例指标被误认为任务实测值。
  const model = selectPageModel(window.appState, pageId);
  const panel = target.querySelector(".special-panel");
  if (panel)
    panel.innerHTML = `<div class="special-head"><div><h3>记录风险分布</h3><p>按当前页面已保存记录统计，风险评分由录入人员填写</p></div><span>${model.rows.length} 条记录</span></div><div class="saved-risk-list">${
      model.rows.length
        ? model.rows
            .slice(0, 6)
            .map(
              (row) =>
                `<div><span>${escapeHtml(row.name)}</span><meter min="0" max="100" value="${row.risk}"></meter><b>${formatNumber(row.risk)}</b></div>`,
            )
            .join("")
        : emptyState("尚无记录，点击“新建记录”开始录入")
    }</div>`;
  target
    .querySelectorAll(".metric-card em")
    .forEach((el) => (el.textContent = "当前已保存数据"));
  target.querySelectorAll(".panel-head p").forEach((el) => {
    if (el.textContent === "按优先级自动汇总")
      el.textContent = "最近高风险记录，最多显示四条";
    if (el.textContent === "所有记录均来自本地工程数据服务")
      el.textContent = "本地数据库记录；时间以 UTC 显示";
    if (el.textContent === "操作、判断与反馈完整留痕")
      el.textContent = "最近创建的记录及备注";
  });
  const riskTitle = target.querySelector(".special-head h3");
  if (riskTitle) riskTitle.textContent = "最近六条记录的风险评分";
  if (!model.rows.length)
    target.querySelector("tbody").innerHTML =
      '<tr><td colspan="4">暂无记录</td></tr>';
  if (window.appState?.error) {
    const warning = document.createElement("p");
    warning.setAttribute("role", "alert");
    warning.textContent = `数据读取失败：${window.appState.error}。请点击刷新重试。`;
    target.prepend(warning);
  }
  document
    .querySelectorAll("[data-engineering-page]")
    .forEach((button) =>
      button.classList.toggle(
        "active",
        button.dataset.engineeringPage === pageId,
      ),
    );
  sessionStorage.setItem("engineeringPage", pageId);
}
function openEngineeringEdition() {
  const classic = document.querySelector("body > aside");
  const main = document.querySelector("body > main");
  const shell = document.getElementById("engineering-shell");
  if (classic) classic.hidden = true;
  if (main) main.hidden = true;
  if (shell) shell.hidden = false;
  renderEngineeringPage(sessionStorage.getItem("engineeringPage") || "cockpit");
}
function closeEngineeringEdition() {
  const classic = document.querySelector("body > aside");
  const main = document.querySelector("body > main");
  const shell = document.getElementById("engineering-shell");
  if (classic) classic.hidden = false;
  if (main) main.hidden = false;
  if (shell) shell.hidden = true;
}
async function loadEngineeringData() {
  try {
    const responses = await Promise.all(
      [
        "/api/engineering/catalog",
        "/api/tasks",
        "/api/engineering/records",
        "/api/bootstrap",
      ].map((url) => fetch(url)),
    );
    if (responses.some((response) => !response.ok))
      throw new Error("工程数据接口不可用");
    const [catalogue, tasks, records, bootstrap] = await Promise.all(
      responses.map((response) => response.json()),
    );
    window.appState = {
      catalogue,
      tasks,
      records,
      token: bootstrap.token,
      current: null,
    };
  } catch (error) {
    window.appState = {
      catalogue: [],
      tasks: [],
      records: [],
      current: null,
      error: String(error),
    };
  }
}
function createRecordDialog() {
  const pageId = sessionStorage.getItem("engineeringPage") || "cockpit";
  const title =
    ENGINEERING_PAGES.find((page) => page.id === pageId)?.title || "业务";
  const dialog = document.createElement("dialog");
  dialog.className = "record-dialog";
  dialog.innerHTML = `<form><h2>新建${escapeHtml(title)}记录</h2><p>保存到你的账户数据库。风险评分为人工录入值。</p><label>名称<input name="name" required maxlength="80" autofocus></label><label>状态<select name="status"><option value="draft">草稿</option><option value="active">运行中</option><option value="review">待复核</option><option value="paused">已暂停</option><option value="completed">已完成</option><option value="archived">已归档</option></select></label><label>风险评分（0—100）<input name="risk" type="number" min="0" max="100" step="0.1" value="0" required></label><label>备注<textarea name="note" maxlength="1000" rows="3"></textarea></label><p role="alert"></p><div class="dialog-actions"><button type="button" data-cancel>取消</button><button type="submit">保存记录</button></div></form>`;
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog
    .querySelector("[data-cancel]")
    .addEventListener("click", () => dialog.close());
  dialog.querySelector("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector("[type=submit]");
    if (button.disabled) return;
    const values = new FormData(form);
    button.disabled = true;
    try {
      const response = await fetch("/api/engineering/records", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": window.appState.token || "",
        },
        body: JSON.stringify({
          page: pageId,
          name: values.get("name"),
          status: values.get("status"),
          risk: Number(values.get("risk")),
          note: values.get("note"),
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "保存失败");
      await loadEngineeringData();
      dialog.close();
      renderEngineeringPage(pageId);
    } catch (error) {
      form.querySelector("[role=alert]").textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  dialog.showModal();
}
async function bindEngineeringEdition() {
  await loadEngineeringData();
  document
    .querySelectorAll("[data-engineering-page]")
    .forEach((button) =>
      button.addEventListener("click", () =>
        renderEngineeringPage(button.dataset.engineeringPage),
      ),
    );
  document
    .getElementById("open-engineering")
    ?.addEventListener("click", openEngineeringEdition);
  document.addEventListener("click", async (event) => {
    const button = event.target.closest(".engineering-page [data-action]");
    if (!button) return;
    if (button.dataset.action === "create") createRecordDialog();
    if (button.dataset.action === "refresh") {
      button.disabled = true;
      await loadEngineeringData();
      renderEngineeringPage(
        sessionStorage.getItem("engineeringPage") || "cockpit",
      );
    }
  });
  document.addEventListener("input", (event) => {
    if (!event.target.matches("[data-filter]")) return;
    const query = event.target.value.trim().toLocaleLowerCase();
    event.target
      .closest(".panel")
      .querySelectorAll("tbody tr")
      .forEach(
        (row) =>
          (row.hidden = !row.textContent.toLocaleLowerCase().includes(query)),
      );
  });
  setInterval(() => {
    const target = document.getElementById("engineering-clock");
    if (target)
      target.textContent = new Date().toLocaleTimeString("zh-CN", {
        hour12: false,
      });
  }, 1000);
  renderEngineeringPage(sessionStorage.getItem("engineeringPage") || "cockpit");
}
window.addEventListener("DOMContentLoaded", bindEngineeringEdition);
window.EngineeringEdition = {
  open: openEngineeringEdition,
  close: closeEngineeringEdition,
  render: renderEngineeringPage,
  pages: ENGINEERING_PAGES,
};
