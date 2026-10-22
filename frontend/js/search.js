import { $, api, escapeHtml, fmtTime, toast, param } from "/js/common.js";

const TYPE = { post: "博客", file: "文件", task: "任务", chat: "聊天" };

function markActiveNav() {
  document.querySelectorAll("#nav a").forEach((a) => {
    if (a.getAttribute("href") === location.pathname) a.classList.add("active");
  });
}

function renderResults(items) {
  const host = $("#results");
  $("#result-count").textContent = `找到 ${items.length} 条`;
  if (!items.length) {
    host.innerHTML = '<li class="empty">没有匹配结果，试试更短或不同的关键词。</li>';
    return;
  }
  host.innerHTML = items.map((item) => {
    const time = typeof item.created_at === "number" ? fmtTime(item.created_at * 1000) : fmtTime(item.created_at);
    return `<li class="search-result"><span class="grow"><span class="tag">${TYPE[item.type] || "内容"}</span>
      <a class="title" href="${escapeHtml(item.url)}">${escapeHtml(item.title)}</a>
      <div class="meta">${escapeHtml(item.snippet || "")} · ${escapeHtml(time)}</div></span></li>`;
  }).join("");
}

async function search(event) {
  event?.preventDefault();
  const query = $("#query").value.trim();
  if (!query) return;
  const button = $("#search-submit");
  button.disabled = true;
  $("#results").innerHTML = '<li class="empty">搜索中…</li>';
  try {
    const data = await api.get(`/api/search?q=${encodeURIComponent(query)}`);
    renderResults(data.results);
    const url = new URL(location.href);
    url.searchParams.set("q", query);
    history.replaceState(null, "", url);
  } catch (err) {
    $("#results").innerHTML = `<li class="empty">搜索失败：${escapeHtml(err.message)}</li>`;
    toast(`搜索失败：${err.message}`, "err");
  } finally { button.disabled = false; }
}

$("#search-form").addEventListener("submit", search);
markActiveNav();
$("#query").value = param("q");
if ($("#query").value) search();
