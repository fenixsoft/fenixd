# 实时会话视图

<!-- knowledge: capability=dashboard-live-session rev=3
     sources=spec/archive/2026-09-23-add-dashboard-live-session,spec/archive/2026-09-23-add-project-detail-tabs,spec/archive/2026-10-03-add-session-composer -->

dashboard 内的项目级自由 Claude 会话：会话进程管理、事件流增量订阅与项目页「会话」分面界面。

## 规则

- 每个受管项目维护至多一个自由 Claude 会话：会话进程 cwd 恒为 registry 中该项目的注册根路径，MUST NOT 由请求参数决定；项目未注册或路径不存在时拒绝并返回错误，不启动任何进程。
- 启动命令行等价于 `claude -p --input-format stream-json --output-format stream-json --verbose --permission-mode bypassPermissions --replay-user-messages`：`-p` + stream-json 组合使进程读入一行 stdin JSON 执行一轮但不退出（多轮对话）；`--verbose` 为硬性要求；`--replay-user-messages` 使每轮输入以 `{"type":"user","isReplay":true,…}` 事件（携带 uuid，前端去重依赖）出现在事件流中——缺失时 CLI 不回显用户输入，服务端缓冲会丢失全部用户轮次。进程环境由 dashboard 进程环境复制后覆盖，MUST NOT 从 `.fenix/config.yaml` 读取 provider 配置。
- 会话复用与只读回读：同项目再次请求复用既有存活会话，不新建第二个；回读端点只读——无会话时返回「无会话」，MUST NOT 借回读隐式启动进程；会话进程退出（读线程观测 EOF 并移除登记）后再次请求才清理登记并重建。
- 一轮输入：以单行 JSON `{"type":"user","message":{...}}` 写入 stdin；写入在会话级锁保护下进行，不与并发发送交错；空文本拒绝且不写 stdin；向不存在/已终止会话发送返回错误，不致服务端异常；`tool_use`/`tool_result` 原样出现在事件流中，不被过滤改写；权限由 `bypassPermissions` 保证无交互式询问；发送时刷新 `last_activity`。
- 事件流：每会话一条守护线程逐行读 stdout；解析失败的行以 `{"type":"stderr","line":<原文>}` 兜底，不中断解析；`type=="system"` 且 subtype 以 `hook_` 开头的 CLI 噪音事件丢弃；`type=="system"` 且 subtype 为 `init` 的事件捕获进补全元数据缓存后丢弃，MUST NOT 进入事件缓冲或 SSE 广播（数据口径见 ADR-208）；其余事件保留（过滤只作用于会话路径，不改变 fenixd run 产物落盘）；事件经 SSE 定向订阅推送 `{"type":"session_events","session_id":…,"events":[…]}`，只投递给订阅了该会话的连接；事件缓冲有界，超限丢弃最旧且全量回读携带 `truncated:true`；重开界面接回既有缓冲全量，不重启进程。
- 补全元数据端点：`GET /api/session/files?project=<name>` 返回项目工作区文件相对路径数组——以 registry 注册路径为 cwd 跑 `git ls-files --cached --others --exclude-standard` 子进程（timeout 10s，超时或无法执行返回空数组不 500），条数上限 5000 静默截断、响应体为普通数组不附截断标记，合法注册但非 git 仓库返回 200 空数组；`GET /api/session/commands?project=<name>` 返回 init 缓存的 `slash_commands` 与 `skills`，MUST NOT 自行扫描 skills/命令目录推导；两端点均只读，project 校验复用既有 `_project_from_query`（缺参/未注册 404）；无在飞会话或 init 未到达时 commands 返回两个空数组。
- init 缓存：Session 对象持 `slash_commands`/`skills` 缓存字段（commands 端点唯一数据源），随 Session 生命周期存亡——进程终止、会话被移除后缓存一并不可达，MUST NOT 返回陈旧缓存；会话重启后以新 init 事件内容覆盖。
- 终止与回收：显式终止先关 stdin，宽限 `SESSION_TERMINATE_GRACE_SECONDS` 后仍存活则 kill；EOF 观测即判定进程退出，缓冲 `session_ended`（reason `process_exit`）并移除登记；空闲回收线程按 `SESSION_IDLE_TIMEOUT_SECONDS`（模块常量，非受管配置键）扫描，超时会话走与显式终止相同路径（reason `idle`）；dashboard 进程退出时终止全部会话进程，不留孤儿。
- 前端承载：会话界面为项目页「会话」分面的内联面板（消息流区 + 输入控件），MUST NOT 以 Modal 弹窗呈现，页面标题栏不设独立「接入会话」按钮；会话是项目级语义，MUST NOT 出现在单行 SPEC 的「更多」菜单；消息流复用 `claude-msg` 展示控件与 `runEventsToChatMessages()` 转换，不另写一套渲染；输入区由 [会话输入控件](session-composer.md) 承载（补全/草稿/键盘适配归该能力），发送经既有 REST `sendSessionMessage`、停止经 `stopSession`，语义不变；会话终止事件以明确终态提示呈现并禁用输入区，不静默无响应。
- 按需激活：仅「会话」分面被选中时拉取会话状态并订阅事件流；未被选中时不产生会话相关请求或订阅；切离分面释放订阅但不终止会话进程本身。
- 与 fenixd 产物完全隔离：不读写 `.fenix/STATE.md`、不在 `.fenix/runs/` 产生文件、不改变任何 SPEC 状态或任务进度。
- 会话不持久化：无历史会话列表、不做 `--resume` 接回，随 dashboard 进程生命周期（重启即全部消失）。

## 溯源

- 2026-09-23 2026-09-23-add-dashboard-live-session（spec/archive/2026-09-23-add-dashboard-live-session） — 建立会话进程管理（创建/复用/输入/订阅/终止/空闲回收）、SSE 定向订阅、与 fenixd 产物隔离契约及前端会话界面
- 2026-09-23 2026-09-23-add-project-detail-tabs（spec/archive/2026-09-23-add-project-detail-tabs） — 会话界面承载形态由标题栏按钮 + 全屏 Modal 改为项目页「会话」分面内联面板，并加按需激活门控（会话进程与 REST/SSE 契约不变）
- 2026-10-03 add-session-composer（spec/archive/2026-10-03-add-session-composer） — 输入区改由 session-composer 控件承载；新增 files/commands 两个只读元数据端点与 SessionManager init 事件缓存；init 事件改为捕获后丢弃、不再进事件缓冲与 SSE（原「其余事件含 system/init 保留」口径废除）
