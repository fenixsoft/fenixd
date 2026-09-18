## Context

Fenix Web Dashboard（`core/dashboard/`）当前是一个**只读观测面板**：Python
标准库 `ThreadingHTTPServer` + 表驱动路由（`routes/base.py` 的
`_API_GET_ROUTES` / `_API_POST_ROUTES` / `_API_DELETE_ROUTES`），前端是
Ant Design Pro（`static/src/`），实时性由 `FileWatcher`（`watcher.py`，1s 轮询）
+ `SSEHub`（`sse.py`）推送。

本 SPEC 要加入**第一个面向人的交互式会话能力**。相关既有构造：

- **展示控件已就绪**：`static/src/components/claude-msg/`（16 文件）是
  claudecodeui 的展示层移植；`runEvents.ts:runEventsToChatMessages()` 已按
  `claude -p --output-format stream-json` 的原始块结构解析 assistant / user /
  tool_use / tool_result / thinking。`ClaudeOutputPane.tsx` 是既有的
  「拉尾部 + SSE 增量 + 渲染」范例（数据源是 run 产物文件）。
- **SSE 订阅机制通用**：`SSEHub.watch(cid, key)` 的 `key` 只是不透明字符串
  （现用于 `run_id`）；`broadcast(event, run_id=key)` 定向投递。
- **子进程范例已存在**：`core/agent_runner/runner.py:3249` 用 `subprocess.Popen`
  + 逐行 stdout 读线程跑 claude CLI 并解析事件；env 由 `os.environ.copy()` 继承
  （实测 dashboard 进程环境中 `ANTHROPIC_BASE_URL=http://127.0.0.1:15721` 就绪）。
- **服务器生命周期钩子**：`server.py:serve()` —— `watcher.start()` 之后是
  `httpd.serve_forever()`，`finally` 里 `watcher.stop(); httpd.server_close()`。
  会话管理器的 start/stop 挂同一处。

约束：

- dashboard 进程零新增 Python 依赖（D2：仅标准库，`server.py:4` 明示）。
- 路由表是**可扫描的字面量列表**（`bin/gen-route-map.py` 扫源生成路由图），
  新端点须以既有条目结构登记，不得写自由分支。
- 主树对实现 Agent 只读：前端构建产物 `static/dist/` 属 `reference`，由框架
  在 merge 后自动重建，不进交付物声明。
- `claude` CLI 是 fenixd 的既有硬依赖（`install.sh` 已校验）。

## Goals / Non-Goals

**Goals**

- 在项目页点一下即可与该项目根目录的自由 Claude 会话对话；多轮、带工具调用、
  带 thinking，渲染形态与既有 run 输出面板一致。
- 会话进程与事件缓冲**只活在 dashboard 进程内**，随进程退出而消失；无落盘、
  无历史、无 `--resume`。
- 复用既有 `claude-msg` 展示控件与 `SSEHub`，**不引入 CloudCLI 服务或源码**，
  不引入任何 AGPL 代码，不新增 Python 依赖。

**Non-Goals**

- 不做历史会话、`--resume`、会话导出、附件、语音、slash 命令、模型选择器。
- 不绑定 SPEC、不读写 `.fenix/` 下任何产物（会话不产生 run 文件）。
- 不优雅中断当前轮（`stop` 直接终止进程）。
- 不改 `agent_runner`，不与其共享会话池。

## Decisions

### D1：会话进程的启动命令与 I/O 模型

会话进程 = 一条长期存活的 `claude` 子进程，用**流式输入**模式：

```
claude -p
       --input-format stream-json
       --output-format stream-json
       --verbose
       --permission-mode bypassPermissions
```

- `-p` + `--input-format stream-json` 使进程从 stdin 读 JSON 行、每读一行触发
  一轮，**进程不退出**（实测：连写两行，两轮先后完成，中间记住上下文）。
  `--verbose` 是 `--print` + `stream-json` 的硬性要求（与 runner.py 同款）。
- `cwd` = 项目根（`registry` 里的 `project["path"]`），使会话天然在该项目里
  进行，`CLAUDE.md` / 仓库上下文自动生效。
- `env` = `os.environ.copy()`，与 `runner.py:3211` 同款：dashboard 父进程已带
  网关 env，会话进程继承之，无需读 `.fenix/config.yaml` 的 provider 段。
- stdin 写入格式（每轮一行，`\n` 结尾，`ensure_ascii=False`）：
  ```json
  {"type":"user","message":{"role":"user","content":[{"type":"text","text":"<用户输入>"}]}}
  ```
- stdout 由**每条会话一条守护线程**逐行 `json.loads`。非 JSON 行（CLI 的
  进度/告警文本）单独成 `{"type":"stderr","line":…}` 事件，保证前端永不因
  脏行中断解析（与 `runner.py` 同款兜底）。
- stderr 同样一条守护线程逐行读，只落该会话的**日志环形缓冲**（供错误诊断），
  不推给前端、不影响对话。

**Alternatives considered**

- **`--include-partial-messages` 做逐 token** —— 被否：事件量与前端合并复杂度
  激增，且 Modal 关掉重开时半截消息的状态机难对齐。按完整块到达已足够。
- **用 `--continue` 而非长期进程** —— 被否：每轮都要重启进程、重新加载上下文，
  延迟与 token 成本都高，且丢失「进程还活着」这一最简状态定义。

#### D1.1：事件过滤（hook 噪音）

实测本机 `claude -p --input-format stream-json` 的输出里，`system/hook_started`
与 `system/hook_response` 会携带 **SessionStart hook 的完整附加上下文**
（superpowers skill 全文等，实测单条 hook_response 可达数千字符）。这类事件对
会话本身毫无信息量，若原样进缓冲与推送，用户一开会话就看到满屏噪音。

过滤规则（在 stdout 读线程内、进缓冲**之前**执行）：

- **丢弃**：`type == "system"` 且 `subtype` 以 `hook_` 开头的事件。
- **保留**：其余全部（含 `system/init`、`assistant`、`user`、`result`、以及
  解析失败的 `stderr` 兜底行）。

过滤**只作用于自由会话**（`session_manager.py` 内），MUST NOT 改动
`agent_runner` 的落盘行为——run 产物是审计凭据，须保全量。

实测确认：全部事件（含 hook 类）均携带 `uuid` 字段，故 D6 的 uuid 去重成立。

### D2：会话管理器落位与状态模型

新增 `core/dashboard/session_manager.py`，导出单一类 `SessionManager`：

```python
class Session:
    project: str          # 项目别名（registry 的 name）
    project_path: Path
    proc: subprocess.Popen
    session_id: str       # 本地生成，仅作 SSE 订阅键与前端句柄（不解析 CLI 的 session_id）
    events: deque[dict]   # 事件环形缓冲（maxlen 有界，见 D5）
    lock: threading.Lock  # 保护 stdin 写入与 events 追加
    last_activity: float
    stderr_tail: deque[str]
```

- **每项目至多一个会话**（`dict[str, Session]`，键为项目名）。重复打开 Modal
  即接回同一会话；用户显式 `stop` 后才能重开新的。
- `session_id` 由 dashboard 侧 `uuid4().hex` 生成——**不**依赖 CLI 的
  `session_id`（后者出现在事件流里，但解析它会把会话状态机与 CLI 内部耦合）。
  该 id 仅用于：SSE 订阅键、`/api/session?…` 回读缓冲、前端记录当前句柄。
- 线程模型：manager 的 `dict` 操作与 `spawn/kill` 在**请求线程**里加锁进行；
  每会话的 stdout/stderr 读线程只 append 到该会话的 `events`/`stderr_tail`
  并调 `hub.broadcast`。读线程不触碰 manager 的 `dict`。
- `SessionManager` 实例挂在 `DashboardHTTPServer` 上（`httpd.session_manager`），
  与 `httpd.sse_hub` / `httpd.watcher` 同级；由 `serve()` 创建与收尾。

**Alternatives considered**

- **挂在 watcher 里做节拍轮询** —— 被否：会话是**事件驱动**的（stdout 一到就
  推），塞进 1s 轮询的 watcher 会平白引入 ≤1s 延迟，且职责混淆。

### D3：SSE 复用与订阅键

- 广播：`hub.broadcast({"type":"session_events","session_id":sid,"events":[...]}, run_id=sid)`
  —— 复用 `run_id` 形参作**不透明订阅键**，不改 `SSEHub` 一行。
- 注册：`POST /api/session/watch?project=<name>&cid=<cid>` → `hub.watch(cid, sid)`；
  `DELETE` 同路径 → `hub.unwatch(cid, sid)`。
- 因 `cid` 由服务端在 SSE `hello` 中分配（`ClaudeOutputPane.tsx:95` 已示范正确
  用法），前端 MUST 用 hello 里的 cid，自造 cid 会静默失效。
- **断线重连**（`EventSource` 自动重连 → 新 cid）由前端在每次 hello 时重新
  `POST /api/session`（先取全量缓冲）+ `POST …/watch` 完成重建，与
  `ClaudeOutputPane.tsx` 的「hello 分支里注册 + 重拉尾部」同构。

### D4：事件缓冲与「重开接回」

- 每会话 `events: deque(maxlen=SESSION_EVENT_BUFFER)`（模块常量，缺省 4000）。
  Modal 重开 / 刷新页面 `GET /api/session?project=…` 回读**当前缓冲全量**。
- 缓冲**有界**：超限丢弃最旧事件。为此响应携带 `"truncated": true` 标记，
  前端据此在消息流顶部显示一条「更早的消息已省略」系统行——避免静默丢历史
  造成误解。
- 不在服务端做「事件游标/断点续传」：Modal 重开即全量重拉 + 按事件内在键
  （`uuid`，见 D6）去重，简单且有界。

### D5：生命周期与空闲回收

- **随 dashboard 进程**：`serve()` 中 `httpd.session_manager = SessionManager(...)`；
  `finally` 里 `httpd.session_manager.shutdown()`（对每个会话：关 stdin → 等
  `SESSION_TERMINATE_GRACE_SECONDS`（缺省 5s）→ `proc.kill()`），再 `watcher.stop()`。
- **空闲回收**：会话的 `last_activity` 在每次 send / 每次收到 stdout 事件时刷新；
  一条 manager 级的轻量守护线程按 `SESSION_IDLE_TIMEOUT_SECONDS`（模块常量，
  缺省 1800s）扫描，超时会话走与 `stop` 相同的终止路径并广播
  `{"type":"session_ended","session_id":sid,"reason":"idle"}`。
- **不新增受管配置键**：空闲阈值/缓冲上限/宽限期均为模块常量（与
  `fix-verify-serving-disk-reclaim` 的 `RECLAIM_GRACE_SECONDS` 同款处置）——
  避免触发「新增配置项必须带 Dashboard 界面」的一整套受管键接线
  （`_MANAGED_KEYS` / `_AGENTS_MANAGED_SUBKEYS` / `_SOURCE_KEYS` /
  `_SYNC_PAGE_KEYS` 四处 + 前端面板）。
- **进程被杀兜底**：stdout 读线程读到 EOF 即判定进程退出，追加
  `{"type":"session_ended","reason":"process_exit"}` 并从 manager 移除该会话；
  这样即使用户在别处 `kill` 了 claude 进程，前端也能收到明确终态。

### D6：前端 Modal 与去重

新增 `pages/projects/components/SessionModal.tsx`：

- 全屏 `Modal`（`width="96vw"`，`styles={{body:{height:'82vh'}}}`），内含：
  - 消息区：`ClaudeMessageList`（`messages={runEventsToChatMessages(events)}`）
    —— 与 run 输出面板**同一控件**；
  - 输入区：`Input.TextArea`（Enter 发送 / Shift+Enter 换行）+ 发送按钮 +
    「停止会话」按钮；发送中禁用输入并显示 `Spin`。
- 事件去重：服务端下发的原始事件多数带 `uuid`（CLI 事件信封字段）。前端维护
  `Set<uuid>`；`GET` 全量重拉时清空重建，SSE 增量按 uuid 跳过已见项。无 `uuid`
  的事件（本地合成的 `stderr` / `session_ended`）不进集合、按顺序 append。
- `runEventsToChatMessages` 对 `session_ended` 事件无专门分支，会落到 fallback
  输出 `[session_ended]` 之类的系统行——**须在实现期确认**：要么给它加一条
  明确的系统行文案（推荐），要么在 Modal 层把该类事件单独渲染成状态条而不
  交给 `runEventsToChatMessages`。tasks 中为独立任务。
- 会话未启动 / 未选择项目时不渲染内容；项目切换时关闭 Modal 并清理本地状态。

### D7：入口按钮位置

`pages/projects/list.tsx` 的 `PageContainer.header.title`（当前是
`<Space>{name} 共 N 个 SPEC</Space>`）。

- 按钮放在这个 `Space` **之后**、**靠右**：把 header 的 title 内容改为
  一行 flex 容器，左半是原有 `Space`，右半是「接入会话」按钮
  （`marginLeft:'auto'`）。
- **不放进**每行 SPEC 的 `specMenuItems`：会话是项目级的，与具体 SPEC 无关
  （用户明确要求）。这也是本 SPEC 与 CloudCLI 集成方案在 UX 上的关键分歧点。
- 点击 → `setSessionOpen(true)` → 渲染 `SessionModal`（传 `project={name}`）。

### D8：安全边界

- dashboard 仅绑定 `127.0.0.1`（`server.py:serve()`），故会话的可达面 = 本机
  能访问该端口的人。
- 会话以 `bypassPermissions` 运行 = 在项目根目录下无询问地执行任意命令。
  **用户已显式确认**接受此模式（与 fenixd 现有 agent 一致）。本 SPEC 的实施
  约束：`SessionManager.spawn` MUST 只在 `cwd` 为**该项目的注册根路径**时启动
  （复用 `registry` 的 `project["path"]`，MUST NOT 接受来自请求的任意 cwd），
  从而不可能借会话越权写到其它目录。
- **不做**额外的请求鉴权：dashboard 现状对所有 `/api/*` 无鉴权，本 SPEC 不
  单独为此端点加一套（引入鉴权属独立课题）。

## Risks / Trade-offs

- **[会话进程泄漏]** dashboard 崩溃时子进程可能成为孤儿 → `serve()` 的
  `finally` + 空闲回收 + 读线程 EOF 兜底三重；此外 dashboard 自身挂了则由
  用户在重启后重新打开（会话进程失去 stdin 写入者，读线程后续 EOF 退出）。
  *可接受*：会话进程不持有独占资源，孤儿最多空转至 idle 超时。
- **[`bypassPermissions` 扩大可达面]** → 见 D8：cwd 锁死为注册根；用户已确认。
- **[事件缓冲截断丢历史]** → 携带 `truncated: true` 并显式渲染提示行，
  不静默。
- **[前端去重依赖 `uuid`]** 若某类 CLI 事件无 `uuid` 且服务端重复投递，
  可能重复渲染 → 缓冲全量重拉是唯一会重复的路径，且重拉会清空重建，实际
  只影响「重连瞬间的窗口」；实现期用一次手动重连验证。
- **[CLI 流式输入行为随版本变化]** 该模式依赖 `--input-format stream-json`
  的长期存活语义 → 本机 CLI 已实测；实现期须加一条**集成测试**（真实起一个
  进程、写两轮、断言两轮都有 assistant 输出），一旦 CLI 行为变化即报警。
- **[浏览器 service worker / 静态资源干扰]** 不涉及（不引入 CloudCLI）。

## Migration Plan

无数据迁移。合入后：

1. 重建前端产物（框架在 merge 后自动执行，`static/dist/` 不入库）。
2. 重启 dashboard（`/fenix-dashboard` 或 supervisor 路径）以加载新后端。
3. 回滚：删除 `session_manager.py` 的接线 + 前端按钮即可；无残留状态。

## Open Questions（均已在文档内定案）

- **`session_ended` 渲染落点**（D6）：**定案**——改 `runEvents.ts` 加分支（一处
  收口，run 面板复用同逻辑）。对应 tasks 4.4 + 测试 5.5。
- **`stderr` 事件是否呈现给用户**：**定案**——不呈现，只进服务端
  `stderr_tail` 环形缓冲（tasks 1.4）。理由：CLI 的进度/告警噪音会污染对话，
  而真正的模型错误已走 stdout 的结构化事件（`type: "error"`）。若日后发现关键
  故障只走 stderr，再加「可展开的诊断条」。
