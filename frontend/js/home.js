/**
 * 首页：健康检查、C++ 扩展状态、实时房间概览。
 *
 * 用到的 HTTP 接口（定义位置见 docs/接口清单.md）：
 *   GET  /api/health      -> 服务状态、模块清单、C++ 扩展是否可用
 *   GET  /api/rooms       -> 实时房间与连接数（每 5 秒轮询一次）
 *   POST /api/ext/reload  -> 编译完扩展后热加载
 */
import { $, api, toast, setNetStatus, fmtBytes, fmtTime, escapeHtml } from "/js/common.js";

const MODULE_LABELS = { blog: "博客", files: "文件", chat: "聊天", canvas: "画布", tasks: "任务", polls: "投票", search: "搜索" };

function renderStats(data) {
  const task = data.tasks || {};
  const online = data.realtime?.connections || 0;
  const cards = [
    ["文章", data.posts || 0, "篇"],
    ["共享文件", data.files || 0, "个"],
    ["任务完成", `${task.done || 0} / ${data.tasks ? Object.values(task).reduce((a, b) => a + b, 0) : 0}`, ""],
    ["文件容量", fmtBytes(data.file_bytes || 0), ""],
    ["活跃投票", data.active_polls || 0, "个"],
    ["实时在线", online, "人"],
  ];
  $("#workspace-stats").innerHTML = cards.map(([label, value, suffix]) =>
    `<div class="stat-card"><span class="stat-label">${label}</span><strong>${value}</strong><span class="stat-suffix">${suffix}</span></div>`
  ).join("");
}

function renderActivity(items) {
  const host = $("#activity-feed");
  host.innerHTML = items.length ? items.slice(0, 8).map((item) =>
    `<li><span class="grow"><span class="title">${escapeHtml(item.actor)} ${escapeHtml(item.action)}</span>` +
    `<div class="meta">${escapeHtml(item.detail || "")} · ${escapeHtml(fmtTime(item.created_at))}</div></span></li>`
  ).join("") : '<li class="empty">还没有活动记录</li>';
}

function markActiveNav() {
  const here = location.pathname === "/" ? "/index.html" : location.pathname;
  document.querySelectorAll("#nav a").forEach((a) => {
    if (a.getAttribute("href") === here) a.classList.add("active");
  });
}

function renderHealth(data) {
  const rows = [
    ["服务状态", data.status === "ok" ? "正常" : data.status],
    ["版本", data.version],
    ["模块", data.modules.map((m) => MODULE_LABELS[m] || m).join(" / ")],
    ["C++ 扩展", data.cpp_available ? "已启用（cpp）" : "未编译，使用 Python 回退"],
  ];
  $("#health").innerHTML = rows
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
    .join("");
}

function renderRooms(stats) {
  const entries = Object.entries(stats.rooms || {});
  const host = $("#rooms");
  if (!entries.length) {
    host.innerHTML = '<li class="empty">暂无连接</li>';
    return;
  }
  host.innerHTML = entries
    .map(([room, count]) =>
      `<li><span class="grow"><span class="title">${room}</span></span>` +
      `<span class="tag ok">${count} 人在线</span></li>`)
    .join("");
}

async function refresh() {
  try {
    const [health, rooms, stats, activity] = await Promise.all([
      api.get("/api/health"), api.get("/api/rooms"), api.get("/api/stats"), api.get("/api/activity?limit=8"),
    ]);
    renderHealth(health);
    renderRooms(rooms);
    renderStats(stats);
    renderActivity(activity);
    setNetStatus("on", "服务正常");
  } catch (err) {
    setNetStatus("off", "服务不可用");
    toast(`无法连接后端：${err.message}`, "err");
  }
}

$("#refresh").addEventListener("click", refresh);
$("#reload-ext").addEventListener("click", async () => {
  try {
    const res = await api.post("/api/ext/reload", {});
    toast(res.available ? "C++ 扩展已加载" : "未找到扩展，继续使用 Python 回退",
          res.available ? "ok" : "warn");
    refresh();
  } catch (err) {
    toast(`重新加载失败：${err.message}`, "err");
  }
});

markActiveNav();
refresh();
setInterval(refresh, 5000); // 房间状态每 5 秒刷新一次
