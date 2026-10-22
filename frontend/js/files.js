/**
 * 文件页：拖拽/点击上传、进度显示、列表、下载、删除。
 *
 * 用到的 HTTP 接口：
 *   GET    /api/files               列表
 *   POST   /api/upload              multipart 上传（字段名 file），带进度回调
 *   GET    /api/download/{filename} 下载（直接用 <a href> 交给浏览器处理）
 *   DELETE /api/files/{id}          删除
 *   GET    /api/ext                 页面顶部提示当前哈希引擎
 */
import { $, api, toast, fmtBytes, fmtTime, escapeHtml, copyText } from "/js/common.js";

let fileCache = [];

function markActiveNav() {
  document.querySelectorAll("#nav a").forEach((a) => {
    if (a.getAttribute("href") === location.pathname) a.classList.add("active");
  });
}

async function loadFiles() {
  const host = $("#files");
  try {
    fileCache = await api.get("/api/files");
    renderFiles();
  } catch (err) {
    host.innerHTML = `<li class="empty">加载失败：${escapeHtml(err.message)}</li>`;
  }
}

function renderFiles() {
    const host = $("#files");
    const query = $("#file-search").value.trim().toLocaleLowerCase();
    const files = fileCache.filter((file) => file.original_name.toLocaleLowerCase().includes(query));
    const sort = $("#file-sort").value;
    files.sort((a, b) => sort === "name"
      ? a.original_name.localeCompare(b.original_name, "zh-CN")
      : sort === "size" ? b.size - a.size : new Date(b.uploaded_at) - new Date(a.uploaded_at));
    $("#count").textContent = query ? `显示 ${files.length} / ${fileCache.length} 个` : `共 ${files.length} 个`;
    if (!files.length) {
      host.innerHTML = fileCache.length
        ? '<li class="empty">没有匹配的文件，试试其他关键词。</li>'
        : '<li class="empty">还没有文件，先上传一个试试。</li>';
      return;
    }
    host.innerHTML = files.map((f) => `
      <li data-id="${f.id}">
        <span class="grow">
          <div class="title">${escapeHtml(f.original_name)}</div>
          <div class="meta">${escapeHtml(f.uploader || "匿名")} 上传 · ${fmtBytes(f.size)} · ${fmtTime(f.uploaded_at)} ·
            <code>${escapeHtml((f.sha256 || "").slice(0, 16))}…</code></div>
        </span>
        <a class="tag" href="${f.download_url}" download>下载</a>
        <button class="ghost small" data-copy="${escapeHtml(f.download_url)}">复制链接</button>
        <button class="ghost small" data-del="${f.id}" data-name="${escapeHtml(f.original_name)}">删除</button>
      </li>`).join("");
}

async function uploadOne(file) {
  const form = new FormData();
  form.append("file", file);
  $("#bar").hidden = false;
  const fill = $("#bar > i");
  fill.style.width = "0%";
  $("#upload-status").textContent = `正在上传 ${file.name} …`;

  const result = await api.upload("/api/upload", form, (ratio) => {
    fill.style.width = `${Math.round(ratio * 100)}%`;
  });

  fill.style.width = "100%";
  $("#upload-status").textContent =
    `${file.name} → ${fmtBytes(result.file.size)}，哈希引擎：${result.engine}`;
  toast(result.duplicate
    ? `${file.name} 内容已存在，秒传完成`
    : `${file.name} 上传成功`, result.duplicate ? "warn" : "ok");
  setTimeout(() => { $("#bar").hidden = true; }, 900);
}

async function uploadMany(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  for (const file of files) {
    try {
      await uploadOne(file);
    } catch (err) {
      $("#upload-status").textContent = `${file.name} 上传失败`;
      toast(`${file.name} 上传失败：${err.message}`, "err");
    }
  }
  loadFiles();
}

/* --------------------------------------------------------------- 交互绑定 */
$("#choose").addEventListener("click", () => $("#picker").click());
$("#drop").addEventListener("click", (e) => { if (e.target.id === "drop") $("#picker").click(); });
$("#picker").addEventListener("change", (e) => { uploadMany(e.target.files); e.target.value = ""; });

const drop = $("#drop");
["dragenter", "dragover"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("hot"); }));
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("hot"); }));
drop.addEventListener("drop", (e) => uploadMany(e.dataTransfer.files));

$("#files").addEventListener("click", async (event) => {
  const copy = event.target.closest("[data-copy]");
  if (copy) {
    const url = new URL(copy.dataset.copy, location.origin).href;
    const copied = await copyText(url);
    toast(copied ? "下载链接已复制" : "复制失败，请直接复制浏览器地址", copied ? "ok" : "warn");
    return;
  }
  const button = event.target.closest("[data-del]");
  if (!button) return;
  if (!confirm(`确定删除 ${button.dataset.name}？`)) return;
  try {
    await api.del(`/api/files/${button.dataset.del}`);
    toast("已删除", "ok");
    loadFiles();
  } catch (err) {
    toast(`删除失败：${err.message}`, "err");
  }
});

$("#file-search").addEventListener("input", renderFiles);
$("#file-sort").addEventListener("change", renderFiles);

async function showEngine() {
  try {
    const info = await api.get("/api/ext");
    $("#engine-hint").textContent = info.available
      ? "哈希由 C++ 扩展计算"
      : "C++ 扩展未编译，当前用 Python 计算哈希";
  } catch { /* 忽略 */ }
}

markActiveNav();
loadFiles();
showEngine();
