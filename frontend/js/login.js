/**
 * 登记页：输入一个昵称，之后全站都用它标识身份。
 *
 * 用到的接口：
 *   GET  /api/session  查询是否已经登记过
 *   POST /api/login    提交昵称，服务端下发 HttpOnly 身份 Cookie（30 天）
 *
 * 这里没有密码——本站不做身份核验，昵称只用于区分「谁说的、谁做的」。
 *
 * 防呆设计（曾经踩过的坑）：
 *   浏览器可能缓存旧版页面/脚本，与新版接口错配。旧脚本会读取
 *   `/api/session` 里已经不存在的 `auth_enabled` 字段，误判为「服务端没设
 *   口令」而自动跳转，被拦回来后又跳，形成无限重定向。因此这里规定：
 *   **只有明确拿到 `authenticated === true` 才跳转**，其余情况一律留在本页。
 */
import { $, api, toast } from "/js/common.js";

/** 只接受站内相对路径，防止 ?next=//evil.com 这类开放重定向。 */
function safeNext() {
  const raw = new URLSearchParams(location.search).get("next") || "";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/index.html";
  if (raw.startsWith("/login")) return "/index.html"; // 防止跳回自己造成死循环
  return raw;
}

function showError(message) {
  const box = $("#err");
  if (box) box.textContent = message || "";
}

async function init() {
  try {
    const info = await api.get("/api/session");
    // 关键：必须是明确的 true，缺字段（旧接口）时绝不跳转，避免死循环
    if (info && info.authenticated === true && info.user) {
      location.replace(safeNext());
      return;
    }
  } catch (err) {
    showError(`无法连接服务：${err.message}`);
  }
  const field = $("#username");
  if (field) field.focus();
}

const form = $("#form");
if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("#submit");
    const field = $("#username");
    const name = (field && field.value ? field.value : "").trim();
    if (!name) { showError("请输入一个昵称"); return; }

    if (button) button.disabled = true;
    showError("");
    try {
      const result = await api.post("/api/login", { username: name });
      const display = (result && result.user && result.user.name) || name;
      toast(`欢迎，${display}`, "ok", 1200);
      location.replace(safeNext());
    } catch (err) {
      showError(err.message);
      if (field) field.select();
    } finally {
      if (button) button.disabled = false;
    }
  });
}

init();
