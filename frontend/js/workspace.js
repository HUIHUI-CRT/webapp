import { $, api, toast, escapeHtml } from "/js/common.js";


const STATUS = { todo: "待办", doing: "进行中", done: "已完成" };
let me = "";
let taskCache = [];

/** 身份来自登记页写入的 Cookie；这里只负责显示，不再要求手动输入。 */
async function loadIdentity() {
  try {
    const info = await api.get("/api/session");
    if (info.user) {
      me = info.user.name;
      $("#whoami").textContent = me;
    }
  } catch {
    $("#whoami").textContent = "未登记";
  }
}

function markActiveNav() {
  document.querySelectorAll("#nav a").forEach((a) => {
    if (a.getAttribute("href") === location.pathname) a.classList.add("active");
  });
}

async function loadTasks() {
  try {
    const tasks = await api.get("/api/tasks");
    taskCache = tasks;
    const groups = { todo: [], doing: [], done: [] };
    tasks.forEach((task) => groups[task.status].push(task));
    Object.entries(groups).forEach(([status, items]) => {
      $(`#${status}-count`).textContent = items.length;
      $(`#tasks-${status}`).innerHTML = items.length ? items.map(renderTask).join("")
        : '<p class="empty">目前没有任务</p>';
    });
  } catch (err) { toast(`任务加载失败：${err.message}`, "err"); }
}

function renderTask(task) {
  const overdue = task.due_date && task.status !== "done" && task.due_date < new Date().toISOString().slice(0, 10);
  const priority = { high: "高优先级", medium: "普通", low: "低优先级" }[task.priority] || task.priority;
  return `<article class="task-card ${overdue ? "overdue" : ""}">
    <div class="task-card-head"><strong>${escapeHtml(task.title)}</strong><span class="tag ${task.priority === "high" ? "err" : ""}">${priority}</span></div>
    ${task.description ? `<p>${escapeHtml(task.description)}</p>` : ""}
    <div class="task-meta">${task.assignee ? `负责人：${escapeHtml(task.assignee)}` : "未分配"}
      ${task.due_date ? ` · ${overdue ? "已逾期：" : "截止："}${escapeHtml(task.due_date)}` : ""}</div>
    <div class="row task-actions">
      <label class="sr-only" for="task-status-${task.id}">任务状态</label>
      <select id="task-status-${task.id}" data-task-status="${task.id}" aria-label="${escapeHtml(task.title)} 状态">
        ${Object.entries(STATUS).map(([value, label]) => `<option value="${value}" ${task.status === value ? "selected" : ""}>${label}</option>`).join("")}
      </select>
      <button class="ghost small" type="button" data-task-edit="${task.id}">编辑</button>
      <button class="ghost small danger-text" type="button" data-task-delete="${task.id}">删除</button>
    </div>
  </article>`;
}

async function createTask(event) {
  event.preventDefault();
  const button = $("#task-submit");
  button.disabled = true;
  try {
    await api.post("/api/tasks", {
      title: $("#task-title").value.trim(),
      description: $("#task-description").value.trim(),
      assignee: $("#task-assignee").value.trim(),
      due_date: $("#task-due").value || null,
      priority: $("#task-priority").value,
    });
    $("#task-form").reset();
    toast("任务已添加", "ok");
    loadTasks();
  } catch (err) { toast(`添加失败：${err.message}`, "err"); }
  finally { button.disabled = false; }
}

async function changeTaskStatus(select) {
  try {
    await api.patch(`/api/tasks/${select.dataset.taskStatus}`, { status: select.value });
    toast("任务状态已更新", "ok");
    loadTasks();
  } catch (err) { toast(`状态更新失败：${err.message}`, "err"); loadTasks(); }
}

async function deleteTask(button) {
  if (!confirm("确定删除这个任务吗？")) return;
  try {
    await api.del(`/api/tasks/${button.dataset.taskDelete}`);
    toast("任务已删除", "ok");
    loadTasks();
  } catch (err) { toast(`删除失败：${err.message}`, "err"); }
}

function openTaskEditor(id) {
  const task = taskCache.find((item) => item.id === Number(id));
  if (!task) return;
  $("#edit-task-id").value = task.id;
  $("#edit-task-title").value = task.title;
  $("#edit-task-description").value = task.description;
  $("#edit-task-assignee").value = task.assignee;
  $("#edit-task-due").value = task.due_date || "";
  $("#edit-task-priority").value = task.priority;
  $("#task-editor").showModal();
}

async function saveTaskEdit(event) {
  event.preventDefault();
  const id = $("#edit-task-id").value;
  const button = $("#save-task-edit");
  button.disabled = true;
  try {
    await api.patch(`/api/tasks/${id}`, {
      title: $("#edit-task-title").value.trim(),
      description: $("#edit-task-description").value.trim(),
      assignee: $("#edit-task-assignee").value.trim(),
      due_date: $("#edit-task-due").value || null,
      priority: $("#edit-task-priority").value,
    });
    $("#task-editor").close();
    toast("任务已更新", "ok");
    loadTasks();
  } catch (err) { toast(`保存失败：${err.message}`, "err"); }
  finally { button.disabled = false; }
}

function pollEnded(endsAt) {
  return Boolean(endsAt && new Date(endsAt.replace(" ", "T")).getTime() < Date.now());
}

function renderPoll(poll) {
  const ended = pollEnded(poll.ends_at);
  return `<article class="poll-card">
    <div class="task-card-head"><strong>${escapeHtml(poll.title)}</strong><span class="tag ${ended ? "" : "ok"}">${ended ? "已截止" : "进行中"}</span></div>
    <p class="task-meta">发起人：${escapeHtml(poll.created_by)} · ${poll.total_votes} 票${poll.ends_at ? ` · 截止 ${escapeHtml(poll.ends_at)}` : ""}</p>
    ${poll.options.map((option) => {
      const percent = poll.total_votes ? Math.round(option.votes * 100 / poll.total_votes) : 0;
      const mine = Number(poll.my_option_id) === option.id;
      return `<div class="poll-option ${mine ? "selected" : ""}">
        <div class="poll-option-line"><span>${escapeHtml(option.label)}${mine ? " · 我的选择" : ""}</span><span>${option.votes} 票 · ${percent}%</span></div>
        <div class="poll-progress"><i style="width:${percent}%"></i></div>
        ${ended ? "" : `<button class="ghost small" type="button" data-vote="${poll.id}" data-option="${option.id}">${mine ? "已选择" : "投这一项"}</button>`}
      </div>`;
    }).join("")}
  </article>`;
}

async function loadPolls() {
  try {
    const polls = await api.get("/api/polls");
    $("#polls").innerHTML = polls.length ? polls.map(renderPoll).join("")
      : '<p class="empty">还没有投票，发起一个小组决策吧。</p>';
  } catch (err) { $("#polls").innerHTML = `<p class="empty">投票加载失败：${escapeHtml(err.message)}</p>`; }
}

async function createPoll(event) {
  event.preventDefault();
  const options = $("#poll-options").value.split("\n").map((line) => line.trim()).filter(Boolean);
  const button = $("#poll-submit");
  button.disabled = true;
  try {
    await api.post("/api/polls", {
      title: $("#poll-title").value.trim(),
      options,
      ends_at: $("#poll-ends").value || null,
    });
    $("#poll-form").reset();
    toast("投票已发布", "ok");
    loadPolls();
  } catch (err) { toast(`发布失败：${err.message}`, "err"); }
  finally { button.disabled = false; }
}

async function vote(button) {
  try {
    await api.post(`/api/polls/${button.dataset.vote}/vote`, {
      option_id: Number(button.dataset.option),
    });
    toast("投票已记录，可以再次选择修改", "ok");
    loadPolls();
  } catch (err) { toast(`投票失败：${err.message}`, "err"); }
}

$("#task-form").addEventListener("submit", createTask);
$("#poll-form").addEventListener("submit", createPoll);
document.querySelector(".kanban").addEventListener("change", (event) => {
  if (event.target.matches("[data-task-status]")) changeTaskStatus(event.target);
});
document.querySelector(".kanban").addEventListener("click", (event) => {
  const edit = event.target.closest("[data-task-edit]");
  if (edit) openTaskEditor(edit.dataset.taskEdit);
  const button = event.target.closest("[data-task-delete]");
  if (button) deleteTask(button);
});
$("#task-edit-form").addEventListener("submit", saveTaskEdit);
$("#cancel-task-edit").addEventListener("click", () => $("#task-editor").close());
$("#polls").addEventListener("click", (event) => {
  const button = event.target.closest("[data-vote]");
  if (button) vote(button);
});

markActiveNav();
loadIdentity();
loadTasks();
loadPolls();
setInterval(() => { loadTasks(); loadPolls(); }, 30000);
