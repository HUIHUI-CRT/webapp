# 多功能网站 —— 本地可部署的博客 / 文件 / 聊天 / 画布

一个用 **Python + 原生前端 + 可选 C++ 扩展** 实现的多功能网站，一条命令启动，
博客、文件、聊天、画布、任务、投票与搜索共享同一套基础设施，在 `http://127.0.0.1:8000` 即可完整验证。

| 模块 | 能力 | 实现要点 |
|---|---|---|
| 📝 简易博客 | 发布、倒序列表、详情、删除 | SQLite + REST，列表只返回摘要 |
| 📦 文件共享 | 拖拽上传、列表、下载、删除 | 流式分块落盘，UUID 存储名，SHA-256 秒传 |
| 💬 在线聊天 | 多房间实时广播、在线名单、历史补齐 | WebSocket，断线自动重连 + 心跳 |
| 🎨 共享画布 | 多人协作绘制、房间隔离、清空 | 归一化坐标（0~1），线段级广播 |
| ✅ 任务看板 | 待办 / 进行中 / 已完成，负责人、优先级、截止日期 | SQLite 持久化，逾期提醒与状态统计 |
| 🗳️ 小组投票 | 创建选项、截止时间、实时结果、成员改票 | SQLite 记录，每个昵称每项投票一票 |
| 🔎 全站搜索 | 搜索文章、文件名、任务与近期聊天 | SQLite 查询 + 当前进程聊天缓存 |
| 📈 动态与统计 | 文章、文件、任务、投票、在线人数及近期操作 | 复用各模块数据，活动日志持久保存 |
| ⚙️ C++ 扩展 | SHA-256、分块合并 | pybind11 + CMake，缺失时纯 Python 回退 |

### 文档导航

| 文档 | 用途 |
|---|---|
| `README.md`（本文） | 部署、启动、外网发布、测试验收、故障排查 |
| [`docs/代码导读.md`](docs/代码导读.md) | **推荐阅览顺序** + HTTP 全链路说明（含每个环节的文件位置） |
| [`docs/接口清单.md`](docs/接口清单.md) | 全部接口的 `文件:行号`、处理函数、前端调用方（自动生成） |
| `http://127.0.0.1:8000/docs` | 交互式接口文档，可直接发请求调试 |

---

## 1. 快速开始

### Windows（推荐）

```powershell
# 方式一：双击 start.cmd

# 方式二：命令行
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1
```

脚本会自动：检查/创建 `.venv` → 补齐依赖 → 读取 `.env` → 打印本机与局域网地址 → 启动服务 → 打开浏览器。
停止服务按 `Ctrl+C`。

### 进入网站的方式

**不需要密码，输入一个昵称就能进。** 第一次打开任何页面都会跳到 `/login.html`，
填个名字后 30 天内不用再填；这个名字会跟着你走遍全站——聊天、画布、任务、投票、
发文、传文件，都不再要求单独输入。

> ⚠️ 昵称**不做任何核验**：任何人拿到网址都能以任意昵称进入。它解决的是
> 「到处重复填名字」的体验问题，不是安全边界。详见 [第 8 节](#8-身份与安全说明)。

### Linux / macOS / Git Bash

```bash
bash start.sh
```

### 手动启动

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt      # Windows
# .venv/bin/python -m pip install -r requirements.txt            # Linux/macOS
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

### 访问入口

| 页面 | 地址 |
|---|---|
| 首页 | http://127.0.0.1:8000/index.html |
| 博客 | http://127.0.0.1:8000/blog.html |
| 文件共享 | http://127.0.0.1:8000/files.html |
| 在线聊天 | http://127.0.0.1:8000/chat.html |
| 共享画布 | http://127.0.0.1:8000/canvas.html |
| 小组协作台 | http://127.0.0.1:8000/workspace.html |
| 全站搜索 | http://127.0.0.1:8000/search.html |
| 接口文档 | http://127.0.0.1:8000/docs |

---

## 2. 让别人访问（外网）

服务默认监听 `0.0.0.0`，本机、局域网、外网共用同一个进程。

**第一步：放行入站端口**（管理员权限的 PowerShell）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\open_firewall.ps1 -Port 8000
# 撤销：加 -Remove
```

**方式一：局域网访问**
启动脚本会打印形如 `http://192.168.x.x:8000/index.html` 的地址，同一网络内的设备直接访问。
若访问不通，确认上面这一步已执行。

**方式二：路由器端口映射（长期可用）**
在路由器后台把公网端口的 TCP 流量映射到本机内网 IP 的 `8000` 端口，
别人用 `http://<你的公网IP>:8000/index.html` 访问。适用于有公网 IP 的宽带。

**方式三：内网穿透（临时、免公网 IP，推荐演示用）**

```powershell
# 另开一个窗口，先保证 start.ps1 已在运行
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\public_tunnel.ps1
```

脚本调用 Cloudflare 免费快速隧道，会输出一个 `https://xxxx.trycloudflare.com` 地址，
把它发给任何人都能访问（WebSocket 自动走 wss）。首次运行会把 `cloudflared.exe`
自动下载到 `.tools\`（约 55 MB，只下一次）。

手机扫码版本：拿到地址后生成二维码

```powershell
.\.venv\Scripts\python.exe scripts\make_qr.py https://xxxx.trycloudflare.com
# 输出 docs\公网访问二维码.png，用手机相机扫一扫即可打开
```

注意：**快速隧道的地址不是永久的**——关掉窗口或重启 `cloudflared` 就会换一个新域名。
需要固定地址请改用 Cloudflare 命名隧道（需要账号），或直接用方式一/方式二。

> ⚠️ 公网地址是公开的：拿到链接的人都能上传/下载文件、在聊天里发言。
> 演示完请立刻关闭隧道。生产场景请自行加认证（见「后续扩展」）。

---

## 3. 目录结构

```
webapp/
├── backend/
│   ├── app/
│   │   ├── main.py          FastAPI 入口：组装路由 + 挂载静态前端
│   │   ├── config.py        路径与运行参数（全部可用环境变量覆盖）
│   │   ├── auth.py          昵称身份门禁（签名 Cookie + 纯 ASGI 中间件）
│   │   ├── db.py            SQLite 连接与建表（WAL + busy_timeout）
│   │   ├── schemas.py       请求/响应模型
│   │   ├── routers/
│   │   │   ├── blog.py      /api/posts*
│   │   │   ├── files.py     /api/files*、/api/upload、/api/download/*
│   │   │   └── ws.py        /ws（聊天与画布共用）
│   │   ├── services/hub.py  房间广播中心：连接管理、历史缓存、广播
│   │   └── ext/             C++ 扩展加载器 + 纯 Python 回退
│   ├── cpp/
│   │   ├── fastcore.cpp     SHA-256 与分块合并实现（pybind11）
│   │   └── CMakeLists.txt   扩展构建脚本
│   ├── build/               编译产物 fastcore*.pyd 落在这里（被自动搜索）
│   ├── data/app.db          SQLite 数据库（重启不丢）
│   └── uploads/             上传的文件（重启不丢）
├── frontend/                原生 HTML/CSS/JS，无需构建工具
│   ├── index.html blog.html files.html chat.html canvas.html workspace.html search.html login.html
│   ├── css/style.css
│   └── js/common.js + 各页面脚本（含 login.js）
├── scripts/
│   ├── start.ps1            一键启动（会加载根目录 .env）
│   ├── build_ext.ps1        编译 C++ 扩展
│   ├── open_firewall.ps1    放行入站端口（需管理员）
│   ├── public_tunnel.ps1    内网穿透，生成临时公网地址
│   ├── make_qr.py           把公网地址生成手机可扫的二维码
│   ├── gen_api_doc.py       扫描路由生成 docs/接口清单.md
│   └── smoke_test.py        对运行中的服务做真实 HTTP/WebSocket 验证
├── .env.example             配置模板（复制为 .env 后按需修改）
├── docs/
│   ├── 代码导读.md          推荐阅览顺序 + HTTP 全链路说明（含文件位置）
│   └── 接口清单.md          全部接口的 文件:行号（自动生成，勿手改）
├── .tools/                  构建期辅助（不参与网站运行）
│   ├── sitecustomize.py     Python 3.14 在受限环境下 mkdtemp 权限过窄的补丁
│   └── patch_ps1.py         改写 .ps1 时保留 UTF-8 BOM 的小工具
├── tests/                   pytest 测试（45 项）
├── requirements.txt
├── start.cmd / start.sh
└── pytest.ini
```

---

## 4. 接口与协议

### 4.1 REST

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/posts` | 文章列表（标题 + 摘要，支持 `limit` / `offset`） |
| GET | `/api/posts/{id}` | 文章详情（含完整正文） |
| POST | `/api/posts` | 创建文章 `{title, content}` |
| DELETE | `/api/posts/{id}` | 删除文章 |
| GET | `/api/files` | 文件列表（含大小、时间、sha256、下载地址） |
| POST | `/api/upload` | 上传文件（multipart 字段名 `file`） |
| GET | `/api/download/{filename}` | 按存储名下载，响应头还原原始文件名 |
| DELETE | `/api/files/{id}` | 删除文件记录与磁盘文件 |
| GET / POST | `/api/tasks` | 查看 / 创建任务（标题、负责人、优先级、截止日期） |
| PATCH / DELETE | `/api/tasks/{id}` | 更新状态或内容 / 删除任务 |
| GET / POST | `/api/polls` | 查看投票结果 / 创建投票 |
| POST | `/api/polls/{id}/vote` | 投票或更改自己的选择 |
| GET | `/api/activity?limit=30` | 最近小组活动记录 |
| GET | `/api/stats` | 首页汇总：任务、投票、文件、在线人数等 |
| GET | `/api/search?q=关键词` | 搜索文章、文件、任务和当前运行期聊天记录 |
| GET | `/api/health` | 健康检查（含 C++ 扩展状态） |
| GET | `/api/ext` `POST /api/ext/reload` | 查看 / 热加载 C++ 扩展 |
| GET | `/api/rooms` | 实时房间与连接数 |

### 4.2 WebSocket `/ws?user=<昵称>&room=<房间>`

聊天与画布共用一条连接，靠 `type` 区分。

客户端 → 服务端：

```jsonc
{"type": "chat",  "text": "你好", "user": "甲", "room": "lobby"}
{"type": "draw",  "from": {"x":0.1,"y":0.2}, "to": {"x":0.3,"y":0.4},
                  "color": "#2b7de9", "width": 3, "room": "lobby"}
{"type": "clear", "room": "lobby"}
{"type": "ping"}
```

服务端 → 客户端：

| type | 说明 |
|---|---|
| `welcome` | 连接建立，携带 `you`、在线 `users`、`chat_history`、`canvas_history` |
| `chat` | 广播的聊天消息（含服务端 `ts`，发送者也会收到） |
| `draw` | 广播的绘制动作（**不回发给发起者**，避免重复绘制） |
| `clear` | 画布被清空 |
| `join` / `leave` | 成员变动，附带最新 `users` |
| `pong` / `error` | 心跳应答 / 载荷不合法 |

画布坐标使用 **0~1 归一化值**，因此不同窗口尺寸、不同 DPI 的客户端能画在同一位置。

---

## 5. C++ 扩展

负责两件计算密集的事：**SHA-256 计算**（用于秒传与完整性校验）和**分块文件合并**。

### 编译

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_ext.ps1
```

流程：CMake 配置 → `pybind11_add_module` 编译 → 产物写入 `backend/build/` → 脚本自动导入自检。
若 CMake 不可用会自动退化为直接调用 `g++` 编译。

产物落盘后无需重启：首页的「重新加载 C++ 扩展」按钮（或 `POST /api/ext/reload`）即可热加载。
当前构建结果：

```
backend/build/fastcore.cp314-win_amd64.pyd
依赖：python314.dll + 系统 UCRT，无第三方运行库（已静态链接 libgcc/libstdc++/winpthread）
```

### 回退保证

`backend/app/ext/__init__.py` 按 `fastcore` → `backend/build` → `backend/app/ext` 的顺序查找扩展，
全部失败就用 `ext/fallback.py` 的纯 Python 实现，**接口完全一致**。因此没装编译器的环境
照样能跑，接口里的 `engine` 字段会显示当前用的是 `cpp` 还是 `python`。

---

## 6. 测试与验收

### 单元 / 接口测试（43 项）

```powershell
.\.venv\Scripts\python.exe -m pytest
```

覆盖：博客增删查与参数校验、文件上传/下载/秒传/删除/路径穿越防护、
任务创建与状态变更、投票计数与改票、跨模块搜索、活动记录与统计、
C++ 与 Python 两种哈希实现结果一致、WebSocket 同房间广播、房间隔离、
绘制动作同步与发起者排除、历史补齐、断线清理。

### 端到端冒烟测试（对运行中的真实服务，23 项）

```powershell
# 另开窗口先启动服务
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

覆盖真实 HTTP（含手写 multipart 上传与下载字节比对）与真实 WebSocket 收发。

### 手工验收（对应计划书各阶段）

| 模块 | 操作 | 预期 |
|---|---|---|
| 博客 | 发布文章 → 刷新 → 点标题 | 列表出现、详情正文完整 |
| 文件 | 拖入文件 → 下载 | 列表出现、下载内容一致；同一文件再传提示秒传 |
| 聊天 | 两个窗口同房间（`chat.html?room=test`） | 消息实时同步；关掉一个窗口另一个继续正常 |
| 画布 | 两个窗口同房间（`canvas.html?room=test`） | 线条实时同步；换房间互不干扰 |
| 持久化 | `Ctrl+C` 后重新启动 | 文章与文件仍在 |

---

## 7. 数据与配置

数据都在 `backend/` 下，重启不丢：

- `backend/data/app.db` —— 文章与文件元数据（WAL 模式）
- `backend/uploads/` —— 上传的文件，磁盘名为 UUID，原始名记录在数据库

全部配置可用环境变量覆盖：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_HOST` | `0.0.0.0` | 监听地址，仅本机可设 `127.0.0.1` |
| `APP_PORT` | `8000` | 端口 |
| `APP_DB_PATH` | `backend/data/app.db` | 数据库位置 |
| `APP_UPLOAD_DIR` | `backend/uploads` | 上传目录 |
| `APP_MAX_UPLOAD_BYTES` | `536870912`（512 MiB） | 单文件上限 |
| `APP_CHAT_HISTORY_LIMIT` | `200` | 每个房间保留的聊天条数 |
| `APP_CANVAS_HISTORY_LIMIT` | `5000` | 每个房间保留的线段数 |
| `APP_SECRET` | 自动生成 | 身份 Cookie 签名密钥，换值即让所有已登记设备失效 |

以上变量都可以写在项目根目录的 `.env` 里（`scripts/start.ps1` 会自动加载），
也可以用系统环境变量覆盖（同名时系统环境变量优先）。

---

## 8. 身份与安全说明

### 8.1 昵称门禁是怎么工作的

```
访问任意页面
   │
   ├─ 有有效身份 Cookie ──▶ 正常进入（服务端顺带知道"你是谁"）
   │
   └─ 没有 ──▶ 页面：302 跳到 /login.html?next=…
                接口：401 {"detail": "尚未登记昵称…"}
                WebSocket：握手直接关闭
                        │
                输入昵称 ──▶ POST /api/login ──▶ 记录昵称
                        │                       └─ 下发 HttpOnly 签名 Cookie（30 天）
                        └─ 跳回原来要访问的页面
```

实现位置：`backend/app/auth.py`（纯 ASGI 中间件，同时覆盖 HTTP 与 WebSocket）、
`frontend/login.html` + `frontend/js/login.js`、`backend/app/main.py` 里的
`/api/login`、`/api/logout`、`/api/session` 三个接口。

**为什么用 Cookie 而不是 localStorage**：`new WebSocket()` 无法附加自定义请求头，
但同源握手一定会带 Cookie。这样 `/ws` 也能拿到身份，聊天里显示的就是登记过的名字，
而不是前端随手填的「访客123」；同时前端也改不动自己的名字（服务端只认 Cookie）。

**身份是怎么变成「作者/上传者/发起人」的**：路由通过 `Depends(current_user)` 取当前昵称，
写入 `posts.author`、`files.uploader`、`tasks.created_by`、`polls.created_by`、
`poll_votes.voter`、`activity.actor`。前端不再需要提交这些字段。

### 8.2 换名字与失效

- **换名字**：右上角「换个名字」→ 重新填一次，旧身份立即作废。
- **让所有人重新登记**：改 `.env` 里的 `APP_SECRET`（或删除 `backend/data/.identity_secret`）后重启。
- **有效期**：30 天，过期后自动回到登记页。

### 8.3 其余已做的防护

上传文件名清洗（去目录成分与危险字符）、磁盘名 UUID 化（杜绝重名覆盖）、
下载仅接受数据库中登记过的存储名并二次校验路径位于上传目录内、上传大小上限、
流式写盘避免内存爆掉、身份 Cookie 为 HttpOnly + SameSite=Lax 且带 HMAC 签名。

### 8.4 这套方案的边界

| 能做 | 不能做 |
|---|---|
| 一次登记，全站通用身份 | 阻止陌生人进入（没有密码） |
| 记录「谁发的文章、谁传的文件、谁建的任务」 | 防止有人冒充别人的昵称 |
| 区分「我」和「别人」（消息归属、我的投票） | 权限控制（人人能干任何事） |

需要真正的门禁与权限时，要升级为账号体系（`users` 表 + 密码哈希 + 角色），
那属于另一项工作。

---

## 9. 故障排查

| 现象 | 原因与处理 |
|---|---|
| 执行 `.ps1` 报「未对文件进行数字签名」 | 用 `powershell -NoProfile -ExecutionPolicy Bypass -File ...`，或直接双击 `start.cmd` |
| 局域网/外网访问不通 | 先执行 `scripts\open_firewall.ps1`；路由器需做端口映射；确认没被其它安全软件拦截 |
| 首页显示「C++ 扩展未编译」 | 属正常回退。执行 `scripts\build_ext.ps1` 编译后点「重新加载 C++ 扩展」 |
| `build_ext.ps1` 提示找不到编译器 | 装 MSYS2（含 `ucrt64` 工具链）或 Visual Studio Build Tools，再用 `-Compiler` 指定 `g++.exe` 全路径 |
| MSYS2 编译时 cc1plus 静默失败 | 编译器所在 `bin` 目录必须在 `PATH` 中（脚本已自动处理） |
| 一直停在登记页 | 浏览器禁用了 Cookie，或身份已过期；允许本站 Cookie 后重新填一次昵称 |
| 顶栏名字不对 | 点右上角「换个名字」重新登记；想让所有人都重来就换 `APP_SECRET` 后重启 |
| 手机能打开页面但聊天连不上 | 检查是不是用 `http://` 打开的（隧道是 https，必须让页面走 https/wss） |

---

## 10. 后续扩展方向

- **多用户账号**：注册登录、按用户隔离博客与文件、区分管理员与访客。
- **画布持久化**：把线段历史写进 SQLite，支持回放与断点接续。
- **分块上传 / 秒传**：已具备 SHA-256 能力，可在此基础上做断点续传。
- **统一通知**：通过 `/ws` 推送「新文章」「新文件」事件，首页做成实时时间线。
- **房间工作区**：把博客、文件、聊天、画布按房间组织成独立工作区。
