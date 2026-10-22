/**
 * 公共前端工具：接口调用、WebSocket 自动重连、格式化与提示。
 * 原生 ES 模块，无需构建工具。
 */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// 尽早恢复外观偏好；主题开关由 initAuthUi 在页面状态栏中添加。
try {
  document.documentElement.dataset.theme = localStorage.getItem("webapp-theme") === "dark" ? "dark" : "light";
} catch { /* 隐私浏览模式可能禁用本地存储 */ }

export async function copyText(value) {
  try {
    await navigator.clipboard.writeText(String(value));
    return true;
  } catch {
    const field = document.createElement("textarea");
    field.value = String(value);
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    return copied;
  }
}

/* ------------------------------------------------------------------ 接口 */
/**
 * 所有 HTTP 请求的统一出口。
 *
 * 约定（与后端保持一致）：
 *   - 请求/响应体都是 JSON（上传除外，走 multipart/form-data）；
 *   - 非 2xx 时后端返回 {"detail": "..."}，这里把它抛成 Error，
 *     调用方只需要 try/catch 并展示 err.message 即可；
 *   - 204/空响应或非 JSON 响应会退化成纯文本，避免 JSON.parse 报错。
 */
async function request(path, options = {}) {
  const res = await fetch(path, options);
  const type = res.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await res.json() : await res.text();
  if (res.status === 401 && !location.pathname.startsWith("/login")) {
    // 身份失效（例如换了 APP_SECRET）：直接送回登记页，别让页面停在一堆报错上
    location.replace(`/login.html?next=${encodeURIComponent(location.pathname + location.search)}`);
  }
  if (!res.ok) {
    const detail = payload && payload.detail ? payload.detail : `HTTP ${res.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

/** 各页面调用的接口封装，路径与 docs/接口清单.md 一一对应。 */
export const api = {
  // GET，用于取列表/详情，例如 api.get('/api/posts')
  get: (path) => request(path),
  // POST + JSON 请求体，例如 api.post('/api/posts', {title, content})
  post: (path, body) =>
    request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  patch: (path, body) =>
    request(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  // DELETE，用于删除文章/文件
  del: (path) => request(path, { method: "DELETE" }),
  // multipart/form-data 上传：用 XHR 而不是 fetch，只为拿到上传进度事件
  upload: (path, formData, onProgress) =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", path);
      xhr.upload.onprogress = (e) => {
        if (onProgress && e.lengthComputable) onProgress(e.loaded / e.total);
      };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch { /* 忽略非 JSON */ }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error(data.detail || `HTTP ${xhr.status}`));
      };
      xhr.onerror = () => reject(new Error("网络错误，上传失败"));
      xhr.send(formData);
    }),
};

/* ------------------------------------------------------- WebSocket 长连接 */
/**
 * 构造 /ws 的地址。注意 http->ws、https->wss 的对应关系：
 * WebSocket 复用同一个 HTTP 端口完成握手（详见 backend/app/routers/ws.py 顶部说明），
 * 因此页面用 https 打开时，必须用 wss 才不会触发混合内容拦截。
 */
/**
 * 构造 /ws 的地址。昵称不再放在查询串里——它来自身份 Cookie，由服务端解析。
 * 注意 http->ws、https->wss 的对应关系：页面用 https 打开时必须用 wss，
 * 否则会被浏览器当作混合内容拦截。
 */
export function wsUrl(room) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const qs = new URLSearchParams({ room });
  return `${proto}//${location.host}/ws?${qs}`;
}

/**
 * 带自动重连与心跳的 WebSocket 封装。
 * 事件：open / close / message / error / status
 */
export class LiveSocket extends EventTarget {
  constructor({ room, heartbeatMs = 25000 }) {
    super();
    this.room = room;
    this.heartbeatMs = heartbeatMs;
    this.ws = null;
    this.retry = 0;
    this.closedByUser = false;
    this.timer = null;
  }

  connect() {
    this.closedByUser = false;
    this._emit("status", { state: "connecting" });
    let socket;
    try {
      socket = new WebSocket(wsUrl(this.room));
    } catch (err) {
      this._scheduleReconnect();
      return;
    }
    this.ws = socket;

    socket.onopen = () => {
      this.retry = 0;
      this._emit("open", {});
      this._emit("status", { state: "open" });
      this.timer = setInterval(() => this.send({ type: "ping" }), this.heartbeatMs);
    };

    socket.onmessage = (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      this._emit("message", data);
    };

    socket.onerror = () => this._emit("error", {});

    socket.onclose = () => {
      clearInterval(this.timer);
      this.timer = null;
      this._emit("close", {});
      if (!this.closedByUser) this._scheduleReconnect();
      else this._emit("status", { state: "closed" });
    };
  }

  _scheduleReconnect() {
    this.retry += 1;
    const delay = Math.min(1000 * 2 ** (this.retry - 1), 15000);
    this._emit("status", { state: "retrying", retry: this.retry, delay });
    setTimeout(() => { if (!this.closedByUser) this.connect(); }, delay);
  }

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(typeof obj === "string" ? obj : JSON.stringify(obj));
      return true;
    }
    return false;
  }

  close() {
    this.closedByUser = true;
    clearInterval(this.timer);
    if (this.ws) this.ws.close();
  }

  _emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }
}

/* ------------------------------------------------------------------ 提示 */
export function toast(message, kind = "", timeout = 2600) {
  let host = $("#toast");
  if (!host) {
    host = document.createElement("div");
    host.id = "toast";
    document.body.appendChild(host);
  }
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  host.appendChild(node);
  setTimeout(() => node.remove(), timeout);
}

/* ------------------------------------------------------------------ 格式化 */
export function fmtBytes(bytes) {
  const n = Number(bytes) || 0;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let value = n;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1; }
  return `${i === 0 ? value : value.toFixed(value < 10 ? 2 : 1)} ${units[i]}`;
}

export function fmtTime(ts) {
  const date = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (Number.isNaN(date.getTime())) return String(ts || "");
  const pad = (v) => String(v).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
         `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

/** 从地址栏读取查询参数（房间、昵称等），并回写到地址栏便于分享。 */
export function param(name, fallback = "") {
  return new URLSearchParams(location.search).get(name) || fallback;
}

export function setParams(pairs) {
  const qs = new URLSearchParams(location.search);
  Object.entries(pairs).forEach(([k, v]) => qs.set(k, v));
  history.replaceState(null, "", `${location.pathname}?${qs}`);
}

/** 随机昵称，方便多窗口测试。 */
export function randomName(prefix = "访客") {
  return `${prefix}${Math.floor(100 + Math.random() * 900)}`;
}

/** 设置顶栏连接状态指示灯。 */
export function setNetStatus(state, text) {
  const dot = $("#net-dot");
  const label = $("#net-text");
  if (!dot || !label) return;
  dot.className = `dot ${state}`;
  label.textContent = text;
}

export const COLORS = ["#e5484d", "#2b7de9", "#12a594", "#f5a524", "#8e4ec6",
                       "#e93d82", "#3e63dd", "#30a46c", "#f76808", "#0d9488"];

/* ------------------------------------------------------------------ 登录状态 */
/**
 * 顶栏的身份相关 UI：
 *   - 已登记昵称 -> 右上角显示「昵称 · 换个名字」；
 *   - 还没登记   -> 自动跳转登记页。
 * 登记页本身不渲染这些。
 */
export async function initAuthUi() {
  if (location.pathname === "/login.html") return;
  try {
    const info = await api.get("/api/session");
    const status = $(".status");
    if (!status) return;

    const theme = document.createElement("button");
    theme.type = "button";
    theme.className = "ghost small theme-switch";
    const updateThemeLabel = () => {
      const dark = document.documentElement.dataset.theme === "dark";
      theme.textContent = dark ? "☀️ 浅色" : "🌙 深色";
      theme.setAttribute("aria-label", dark ? "切换浅色模式" : "切换深色模式");
    };
    theme.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("webapp-theme", next); } catch { /* 忽略不可用的本地存储 */ }
      updateThemeLabel();
    });
    updateThemeLabel();
    status.prepend(theme);

    if (!info.authenticated || !info.user) {
      location.replace(`/login.html?next=${encodeURIComponent(location.pathname + location.search)}`);
      return;
    }

    const who = document.createElement("span");
    who.className = "tag";
    who.textContent = info.user.name;
    who.title = "当前身份（全站通用）";
    status.appendChild(who);

    const out = document.createElement("a");
    out.href = "#";
    out.textContent = "换个名字";
    out.style.marginLeft = "10px";
    out.addEventListener("click", async (event) => {
      event.preventDefault();
      try {
        await api.post("/api/logout", {});
        location.replace("/login.html");
      } catch (err) {
        toast(`操作失败：${err.message}`, "err");
      }
    });
    status.appendChild(out);
  } catch {
    /* 网络异常时静默：页面本身已有自己的错误提示 */
  }
}

// 各页面脚本都在 </body> 前加载，此时 DOM 已可操作，直接初始化即可。
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAuthUi);
} else {
  initAuthUi();
}
