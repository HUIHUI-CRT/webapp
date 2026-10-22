/**
 * 博客页：列表 / 发布 / 详情 / 删除。
 *
 * 用到的 HTTP 接口：
 *   GET    /api/posts       列表（只含摘要）
 *   GET    /api/posts/{id}  详情（完整正文）
 *   POST   /api/posts       创建，成功返回 201
 *   DELETE /api/posts/{id}  删除
 */
import { $, api, toast, fmtTime, escapeHtml } from "/js/common.js";

const state = { current: null };
const DRAFT_KEY = "webapp-blog-draft";
let postsCache = [];

function markActiveNav() {
  document.querySelectorAll("#nav a").forEach((a) => {
    if (a.getAttribute("href") === location.pathname) a.classList.add("active");
  });
}

async function loadPosts() {
  const host = $("#posts");
  try {
    postsCache = await api.get("/api/posts?limit=200");
    renderPosts();
  } catch (err) {
    host.innerHTML = `<li class="empty">加载失败：${escapeHtml(err.message)}</li>`;
    toast(`加载文章失败：${err.message}`, "err");
  }
}

function renderPosts() {
  const host = $("#posts");
  const query = $("#post-search").value.trim().toLocaleLowerCase();
  const posts = postsCache.filter((post) =>
    `${post.title} ${post.excerpt}`.toLocaleLowerCase().includes(query));
  $("#count").textContent = query ? `显示 ${posts.length} / ${postsCache.length} 篇` : `共 ${posts.length} 篇`;
  if (!posts.length) {
    host.innerHTML = postsCache.length
      ? '<li class="empty">没有匹配的文章，试试其他关键词。</li>'
      : '<li class="empty">还没有文章，用右侧表单发布第一篇吧。</li>';
    return;
  }
  host.innerHTML = posts.map((p) => `
    <li data-id="${p.id}">
      <span class="grow">
        <a class="title" href="#" data-id="${p.id}">${escapeHtml(p.title)}</a>
        <div class="meta">${escapeHtml(p.author || "匿名")} · ${fmtTime(p.created_at)} · ${escapeHtml(p.excerpt)}</div>
      </span>
      <button class="ghost small" data-open="${p.id}">查看</button>
    </li>`).join("");
}

function saveDraft() {
  const title = $("#title").value;
  const content = $("#content").value;
  try {
    if (!title && !content) {
      localStorage.removeItem(DRAFT_KEY);
      $("#draft-status").textContent = "草稿仅保存在此设备";
      return;
    }
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ title, content, savedAt: Date.now() }));
    $("#draft-status").textContent = "草稿已自动保存到此设备";
  } catch {
    $("#draft-status").textContent = "浏览器未允许保存本地草稿";
  }
}

function restoreDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
    if (!draft) return;
    $("#title").value = draft.title || "";
    $("#content").value = draft.content || "";
    $("#draft-status").textContent = "已恢复上次未发布的草稿；编辑后会自动保存";
  } catch {
    localStorage.removeItem(DRAFT_KEY);
  }
}

async function openPost(id) {
  try {
    const post = await api.get(`/api/posts/${id}`);
    state.current = post;
    $("#detail-card").hidden = false;
    $("#detail-title").textContent = post.title;
    $("#detail-time").textContent = `${post.author || "匿名"} · ${fmtTime(post.created_at)}`;
    $("#detail-content").textContent = post.content;
    $("#detail-card").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    toast(`打开文章失败：${err.message}`, "err");
  }
}

$("#posts").addEventListener("click", (event) => {
  const open = event.target.closest("[data-open]");
  const link = event.target.closest("a[data-id]");
  if (open) { event.preventDefault(); openPost(open.dataset.open); }
  else if (link) { event.preventDefault(); openPost(link.dataset.id); }
});

$("#form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = $("#title").value.trim();
  const content = $("#content").value;
  if (!title || !content.trim()) { toast("标题和正文都不能为空", "warn"); return; }
  const button = $("#submit");
  button.disabled = true;
  try {
    const post = await api.post("/api/posts", { title, content });
    toast("发布成功", "ok");
    $("#form").reset();
    localStorage.removeItem(DRAFT_KEY);
    $("#draft-status").textContent = "草稿仅保存在此设备";
    await loadPosts();
    openPost(post.id);
  } catch (err) {
    toast(`发布失败：${err.message}`, "err");
  } finally {
    button.disabled = false;
  }
});

$("#post-search").addEventListener("input", renderPosts);
$("#form").addEventListener("input", saveDraft);
$("#form").addEventListener("reset", () => setTimeout(saveDraft));

$("#close-detail").addEventListener("click", () => {
  $("#detail-card").hidden = true;
  state.current = null;
});

$("#delete-post").addEventListener("click", async () => {
  if (!state.current) return;
  if (!confirm(`确定删除《${state.current.title}》？`)) return;
  try {
    await api.del(`/api/posts/${state.current.id}`);
    toast("已删除", "ok");
    $("#detail-card").hidden = true;
    state.current = null;
    loadPosts();
  } catch (err) {
    toast(`删除失败：${err.message}`, "err");
  }
});

markActiveNav();
restoreDraft();
loadPosts();
const requestedPost = new URLSearchParams(location.search).get("post");
if (requestedPost && /^\d+$/.test(requestedPost)) openPost(requestedPost);
