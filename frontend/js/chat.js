/**
 * 聊天页：进入房间、收发消息、在线名单、断线重连。
 *
 * 本页不使用 REST 接口，实时通信全部走 WebSocket：
 *   WS /ws?room=<房间>   定义在 backend/app/routers/ws.py
 * 昵称不在这里输入——它来自登记页写入的身份 Cookie，服务端解析后广播，
 * 所以同一个人在聊天、画布、任务里显示的是同一个名字，也无法通过改 URL 冒充。
 */
import {
  $, LiveSocket, toast, fmtTime, escapeHtml, param, setParams,
  setNetStatus, copyText, api,
} from "/js/common.js";

let socket = null;
let me = "";
let myId = null; // 服务端分配的本连接 ID，用于判断消息是否由自己发出
const transcript = [];

function markActiveNav() {
  document.querySelectorAll("#nav a").forEach((a) => {
    if (a.getAttribute("href") === location.pathname) a.classList.add("active");
  });
}

function appendMessage({ user, text, ts, mine, color }) {
  const log = $("#log");
  const node = document.createElement("div");
  node.className = `msg${mine ? " mine" : ""}`;
  node.innerHTML =
    `<div class="who" style="${mine ? "" : `color:${color || "#2b7de9"}`}">` +
    `${escapeHtml(mine ? "我" : user)}<span class="when">${fmtTime(ts * 1000)}</span></div>` +
    `<div class="text">${escapeHtml(text)}</div>`;
  log.appendChild(node);
  log.scrollTop = log.scrollHeight;
  transcript.push({ type: "message", user, text, ts: Number(ts) || Date.now() / 1000 });
}

function appendSystem(text) {
  const log = $("#log");
  const node = document.createElement("div");
  node.className = "msg sys";
  node.textContent = text;
  log.appendChild(node);
  log.scrollTop = log.scrollHeight;
  transcript.push({ type: "system", text, ts: Date.now() / 1000 });
}

function updateCharCount() {
  $("#char-count").textContent = `${$("#text").value.length} / 4000`;
}

async function shareRoom() {
  const room = $("#room").value.trim() || "lobby";
  const url = new URL("/chat.html", location.origin);
  url.searchParams.set("room", room);
  const copied = await copyText(url.href);
  toast(copied ? "房间链接已复制" : "复制失败，请手动复制地址", copied ? "ok" : "warn");
}

function exportChat() {
  if (!transcript.length) { toast("当前还没有可导出的消息", "warn"); return; }
  const room = $("#room").value.trim() || "lobby";
  const lines = transcript.map((item) => {
    const when = fmtTime(item.ts * 1000);
    return item.type === "system" ? `[${when}] ${item.text}` : `[${when}] ${item.user}: ${item.text}`;
  });
  const blob = new Blob([`房间：${room}\n导出时间：${fmtTime(Date.now())}\n\n${lines.join("\n")}`], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  const safeRoom = room.replace(/[^\p{L}\p{N}_-]+/gu, "-");
  link.download = `chat-${safeRoom}-${new Date().toISOString().slice(0, 10)}.txt`;
  link.click();
  URL.revokeObjectURL(link.href);
  toast("聊天记录已导出", "ok");
}

function renderUsers(list) {
  const host = $("#users");
  const users = list || [];
  $("#online-count").textContent = users.length ? `${users.length} 人` : "";
  host.innerHTML = users.length
    ? users.map((u) => {
        const mine = u.user === me;
        return `<li><span class="swatch" style="background:${u.color}"></span>` +
               `${escapeHtml(u.user)}${mine ? ' <span class="tag">我</span>' : ""}</li>`;
      }).join("")
    : '<li class="empty">房间里暂时只有你</li>';
}

async function connect() {
  const room = $("#room").value.trim() || "lobby";
  $("#room").value = room;
  setParams({ room });

  if (socket) socket.close();
  socket = new LiveSocket({ room });
  $("#log").innerHTML = "";
  transcript.length = 0;
  $("#room-label").textContent = `房间：${room}`;
  $("#connect").disabled = true;
  $("#disconnect").disabled = false;
  $("#text").disabled = false;
  $("#send").disabled = false;

  socket.addEventListener("status", (event) => {
    const { state, retry, delay } = event.detail;
    if (state === "open") setNetStatus("on", `已连接 ${room}`);
    else if (state === "connecting") setNetStatus("wait", "连接中…");
    else if (state === "retrying") {
      setNetStatus("off", `断开，${Math.round(delay / 1000)} 秒后第 ${retry} 次重连`);
    } else if (state === "closed") setNetStatus("off", "已断开");
  });

  socket.addEventListener("open", () => {
    appendSystem(`已进入房间「${room}」`);
    $("#text").focus();
  });

  socket.addEventListener("message", (event) => {
    const msg = event.detail;
    switch (msg.type) {
      case "welcome":
        me = msg.you.user;
        myId = msg.you.id;
        (msg.chat_history || []).forEach((m) => appendMessage({ ...m, mine: m.client_id === myId }));
        if (msg.chat_history && msg.chat_history.length) appendSystem("—— 以上为历史消息 ——");
        renderUsers(msg.users);
        break;
      case "chat":
        appendMessage({ ...msg, mine: msg.client_id === myId });
        break;
      case "join":
        renderUsers(msg.users);
        if (msg.user !== me) appendSystem(`${msg.user} 加入了房间`);
        break;
      case "leave":
        renderUsers(msg.users);
        appendSystem(`${msg.user} 离开了房间`);
        break;
      case "error":
        toast(msg.detail, "warn");
        break;
      default:
        break;
    }
  });

  socket.connect();
}

$("#connect").addEventListener("click", connect);

$("#disconnect").addEventListener("click", () => {
  if (socket) socket.close();
  socket = null;
  $("#connect").disabled = false;
  $("#disconnect").disabled = true;
  $("#text").disabled = true;
  $("#send").disabled = true;
  $("#users").innerHTML = '<li class="empty">未连接</li>';
  appendSystem("已离开房间");
  setNetStatus("off", "未连接");
});

$("#say").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("#text").value.trim();
  if (!text) return;
  if (!socket || !socket.send({ type: "chat", text, room: socket.room })) {
    toast("连接不可用，消息未发送", "warn");
    return;
  }
  $("#text").value = "";
  updateCharCount();
});

$("#text").addEventListener("input", updateCharCount);
$("#share-room").addEventListener("click", shareRoom);
$("#export-chat").addEventListener("click", exportChat);

/* 回车发送、页面关闭时优雅断开 */
$("#text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("#say").requestSubmit();
  }
});
window.addEventListener("beforeunload", () => socket && socket.close());

markActiveNav();
$("#room").value = param("room", "lobby");
updateCharCount();

// 身份来自登记页写入的 Cookie，这里只负责显示，不再提供输入框
api.get("/api/session")
  .then((info) => {
    if (info.user) {
      me = info.user.name;
      $("#whoami").textContent = info.user.name;
    }
  })
  .catch(() => { $("#whoami").textContent = "未登记"; });
