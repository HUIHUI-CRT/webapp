/**
 * 共享画布：本地绘制 + WebSocket 广播。
 *
 * 坐标以 0~1 的相对值传输，这样不同窗口尺寸、不同分辨率（含高 DPI）的
 * 客户端都能画在相同位置；每段线独立由 from/to 描述，无需维护画笔状态。
 *
 * 本页不使用 REST 接口，实时通道为：
 *   WS /ws?room=<房间>   定义在 backend/app/routers/ws.py
 * 昵称来自登记页写入的身份 Cookie，不在本页输入，也无法被 URL 参数覆盖。
 * 发送 {"type":"draw"/"clear", ...}，接收同房间其他人的同名消息。
 */
import {
  $, LiveSocket, toast, param, setParams, setNetStatus, escapeHtml, api,
} from "/js/common.js";

const canvas = $("#board");
const ctx = canvas.getContext("2d");

let socket = null;
let me = "";
let myId = null;
let strokes = [];      // 本地保存的全部线段，用于重绘与尺寸变化
let drawing = false;
let last = null;

/* ------------------------------------------------------------------ 画布 */
function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); // 之后统一按 CSS 像素作图
  redraw();
}

function drawSegment(seg) {
  const rect = canvas.getBoundingClientRect();
  ctx.save();
  ctx.strokeStyle = seg.color || "#2b7de9";
  ctx.lineWidth = seg.width || 3;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.moveTo(seg.from.x * rect.width, seg.from.y * rect.height);
  ctx.lineTo(seg.to.x * rect.width, seg.to.y * rect.height);
  ctx.stroke();
  ctx.restore();
}

function redraw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  strokes.forEach(drawSegment);
  $("#stroke-count").textContent = `${strokes.length} 笔`;
}

function normalized(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
    y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
  };
}

/** 记录并绘制一段线；broadcast 为真时同时发给同房间其他客户端。 */
function addSegment(seg, broadcast) {
  strokes.push(seg);
  drawSegment(seg);
  $("#stroke-count").textContent = `${strokes.length} 笔`;
  if (broadcast && socket) {
    socket.send({
      type: "draw",
      from: seg.from,
      to: seg.to,
      color: seg.color,
      width: seg.width,
      room: socket.room,
    });
  }
}

/* --------------------------------------------------------------- 绘制事件 */
canvas.addEventListener("pointerdown", (event) => {
  if (!socket) { toast("请先点击「进入画布」", "warn"); return; }
  canvas.setPointerCapture(event.pointerId);
  drawing = true;
  last = normalized(event);
});

canvas.addEventListener("pointermove", (event) => {
  const point = normalized(event);
  $("#cursor").textContent = `${point.x.toFixed(3)}, ${point.y.toFixed(3)}`;
  if (!drawing || !socket) return;
  addSegment({
    from: last,
    to: point,
    color: $("#color").value,
    width: Number($("#width").value),
  }, true);
  last = point;
});

["pointerup", "pointercancel", "pointerleave"].forEach((ev) =>
  canvas.addEventListener(ev, () => { drawing = false; last = null; }));

$("#width").addEventListener("input", (e) => { $("#width-label").textContent = `${e.target.value} px`; });

/* ------------------------------------------------------------------ 连接 */
function renderUsers(list) {
  const users = list || [];
  $("#online-count").textContent = users.length ? `${users.length} 人` : "";
  $("#users").innerHTML = users.length
    ? users.map((u) =>
        `<li><span class="swatch" style="background:${u.color}"></span>${escapeHtml(u.user)}` +
        `${u.user === me ? ' <span class="tag">我</span>' : ""}</li>`).join("")
    : '<li class="empty">房间里暂时只有你</li>';
}

function connect() {
  const room = $("#room").value.trim() || "lobby";
  $("#room").value = room;
  setParams({ room });

  if (socket) socket.close();
  socket = new LiveSocket({ room });
  strokes = [];
  redraw();
  $("#connect").disabled = true;
  $("#disconnect").disabled = false;
  $("#canvas-status").textContent = `正在进入房间「${room}」…`;

  socket.addEventListener("status", (event) => {
    const { state, retry, delay } = event.detail;
    if (state === "open") setNetStatus("on", `已连接 ${room}`);
    else if (state === "connecting") setNetStatus("wait", "连接中…");
    else if (state === "retrying") setNetStatus("off", `断开，${Math.round(delay / 1000)} 秒后重连（第 ${retry} 次）`);
    else if (state === "closed") setNetStatus("off", "已断开");
  });

  socket.addEventListener("open", () => {
    $("#canvas-status").textContent = `已进入房间「${room}」，可以开始绘制。`;
  });

  socket.addEventListener("message", (event) => {
    const msg = event.detail;
    switch (msg.type) {
      case "welcome": {
        myId = msg.you.id;
        me = msg.you.user;
        strokes = (msg.canvas_history || []).slice();
        redraw();
        renderUsers(msg.users);
        $("#canvas-status").textContent =
          `已进入房间「${msg.you.room}」，当前 ${(msg.users || []).length} 人，历史 ${strokes.length} 笔。`;
        break;
      }
      case "draw":
        strokes.push(msg);
        drawSegment(msg);
        $("#stroke-count").textContent = `${strokes.length} 笔`;
        break;
      case "clear":
        strokes = [];
        redraw();
        toast(msg.client_id === myId ? "你清空了画布" : `${msg.user} 清空了画布`, "warn");
        break;
      case "join":
        renderUsers(msg.users);
        if (msg.user !== me) toast(`${msg.user} 进入画布`, "ok");
        break;
      case "leave":
        renderUsers(msg.users);
        if (msg.user !== me) toast(`${msg.user} 离开画布`);
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
  $("#users").innerHTML = '<li class="empty">未连接</li>';
  $("#canvas-status").textContent = "已离开画布。";
  setNetStatus("off", "未连接");
});

$("#clear").addEventListener("click", () => {
  if (!socket) { toast("请先进入画布", "warn"); return; }
  if (!strokes.length) { toast("画布已经是空的", "warn"); return; }
  if (!confirm("确定清空当前房间的共享画布吗？")) return;
  strokes = [];
  redraw();
  socket.send({ type: "clear", room: socket.room });
});

$("#download-board").addEventListener("click", () => {
  const link = document.createElement("a");
  const room = $("#room").value.trim() || "lobby";
  const safeRoom = room.replace(/[^\p{L}\p{N}_-]+/gu, "-");
  link.download = `canvas-${safeRoom}-${new Date().toISOString().slice(0, 10)}.png`;
  link.href = canvas.toDataURL("image/png");
  link.click();
  toast("画布 PNG 已下载", "ok");
});

window.addEventListener("resize", resizeCanvas);
window.addEventListener("beforeunload", () => socket && socket.close());

/* ------------------------------------------------------------------ 初始化 */
document.querySelectorAll("#nav a").forEach((a) => {
  if (a.getAttribute("href") === location.pathname) a.classList.add("active");
});
$("#room").value = param("room", "lobby");
resizeCanvas();

// 身份来自登记页写入的 Cookie，这里只负责显示
api.get("/api/session")
  .then((info) => {
    if (info.user) {
      me = info.user.name;
      $("#whoami").textContent = info.user.name;
    }
  })
  .catch(() => { $("#whoami").textContent = "未登记"; });
