## Why

Fenixd 的项目里，用户偶尔需要一个**不受 SPEC 约束的自由 Claude 会话**：临时问一个
代码库问题、让 Claude 改一处小东西、试探某个想法，而不必为此立项一个 SPEC。今天
唯一可得的形态是另起一个终端跑 `claude`，或者用一个与 fenixd 完全无关的外部 Web UI
（CloudCLI / claudecodeui），两者的上下文（在哪个目录、用哪个模型网关）都要人工重设。

本 SPEC 在 Fenix Web Dashboard 内提供这个能力：项目页「接入会话」按钮 → 全屏 Modal
→ 与该项目根目录下的 Claude 进行多轮自由对话。

**为什么不引入 CloudCLI 服务**（用户最初设想的方案，经调查否决）：

1. **渲染层已迁移完毕**。`core/dashboard/static/src/components/claude-msg/` 已是
   claudecodeui 的展示控件移植（Markdown / 代码高亮 / thinking 折叠 / 工具卡片），
   且 `runEvents.ts` 的 `runEventsToChatMessages()` **已经在解析**
   `{type:"assistant", message:{content:[{type:"text"|"thinking"|"tool_use"}]}}` 与
   `{type:"user", message:{content:[{type:"tool_result"}]}}` —— 这正是
   `claude -p --output-format stream-json` 的原始事件格式。展示侧零新增。
2. **交互层无法移植**。CloudCLI 的会话前端（`src/components/chat/`）约 14,700 行，
   深度耦合其 i18n / WebSocketContext / provider store / 附件 / 语音 / taskmaster；
   后端由 `@anthropic-ai/claude-agent-sdk` 的 `query()` 驱动（`claude-runtime.provider.js`
   1068 行 + `claude-sessions.provider.js` 684 行）。移植等价于把半个 CloudCLI 搬进来。
3. **执行层 fenixd 已有等价物**。`core/agent_runner/runner.py:3249` 早就在跑
   `claude -p <prompt> --output-format stream-json --verbose --permission-mode
   bypassPermissions` 并逐行解析事件；dashboard 已有 SSE Hub（`core/dashboard/sse.py`）
   与 run 增量订阅。缺的只是「**持续输入**」。
4. **许可证冲突**。CloudCLI 为 **AGPL-3.0-or-later**（`package.json` `license` 字段与
   LICENSE 头），fenixd 为 **MIT**。把 CloudCLI 源码或其编译产物纳入 fenixd 仓库并随
   MIT 包分发，将触发 AGPL 的传染与源码提供义务。本方案只通过 CLI 进程边界与之交互，
   不引入任何 AGPL 代码。
5. **独立的 3001 服务与「跳过登录/直达会话」需求相抵**。CloudCLI 现为带密码形态
   （`~/.cloudcli/auth.db` 内有用户 `icyfenix`），其免登录的「平台模式」需
   `VITE_IS_PLATFORM=true` 且该常量在**构建期**内联进前端 —— 已安装的全局包
   （`/usr/lib/node_modules/@cloudcli-ai/cloudcli`，v1.37.2，前端已编译）不含该分支，
   纯运行时配置无法开启，必须重建前端。本方案天然没有登录概念。

**实测确认的关键机制**（本机 Claude Code CLI）：

```
claude -p --input-format stream-json --output-format stream-json --verbose \
       --permission-mode bypassPermissions
```

- 向 stdin 写一行 `{"type":"user","message":{"role":"user","content":[{"type":"text","text":"…"}]}}`
  即触发一轮；**进程不退出，可无限多轮**（实测两轮记住同一数字）。
- 工具调用与结果正常回传（实测 `Bash` 的 `tool_use` → `tool_result` → 后续 `text`）。
- `--resume <session-id>` 可续接既有会话（本 SPEC **不使用**，见 Non-Goals）。
- 会话落在 `~/.claude/projects/<cwd 编码>/<session-id>.jsonl`（**不落项目目录**）。
- fenixd 现有 agent 即由 dashboard/daemon 父进程以 `os.environ.copy()` 继承的
  `ANTHROPIC_BASE_URL` 等 env 驱动（实测 dashboard 进程 `pid 124307` 的环境里
  `ANTHROPIC_BASE_URL=http://127.0.0.1:15721` 就绪），故会话进程继承同一网关，无需
  另行配置 provider。

## What Changes

在 Dashboard 新增「项目级自由会话」能力，全部落在 fenixd 自己的代码内：

- **新增会话进程管理器** `core/dashboard/session_manager.py`：按项目维护
  `claude` 子进程池（每项目至多一个会话）、stdin 写入管道、stdout 逐行解析线程、
  会话内事件缓冲、空闲回收。纯标准库，与 dashboard 进程同生命周期。
- **新增会话 REST 端点**（沿用既有 mixin + 表驱动路由模式）：
  - `POST /api/session/start?project=<name>` → 显式创建（或复用）该项目的会话并返回句柄
  - `GET  /api/session?project=<name>` → 会话状态 + 全量事件缓冲（**只读**：无会话时
    返回 `session: null`，MUST NOT 借回读端点启动进程；重开 Modal 接回）
  - `POST /api/session/send?project=<name>` → body `{"text": "..."}` 送入一轮
  - `POST /api/session/stop?project=<name>` → 终止会话进程
  - `POST /api/session/watch?project=<name>&cid=<cid>` → 订阅该会话的 SSE 增量
  - `DELETE /api/session/watch?project=<name>&cid=<cid>` → 取消订阅
- **SSE 增量广播**：复用既有 `SSEHub.watch/broadcast`（`run_id` 位传会话 id 作不透明键），
  事件类型 `{"type":"session_events","session_id":…,"events":[…]}`。
- **新增前端会话 Modal** `SessionModal.tsx`：全屏 Modal，上半部消息流（复用
  `ClaudeMessageList` + `runEventsToChatMessages`）、下半部输入框与发送按钮；打开时
  `GET` 拉全量 + 注册 watch，SSE 增量 append。
- **入口按钮**：SPEC 列表页（`pages/projects/list.tsx`）标题栏
  `共 N 个 SPEC` **之后**、**靠右对齐**新增「接入会话」按钮，打开上述 Modal。
  按钮属**项目级**语义（会话绑定项目根目录，与任何具体 SPEC 无关），故**不**放进
  每行 SPEC 的「更多」菜单。
- **生命周期**：会话随 dashboard 进程存活；dashboard 重启即全部消失（不持久化、
  不提供历史会话列表、不做 `--resume` 接回）。空闲回收阈值用**模块常量**
  （`SESSION_IDLE_TIMEOUT_SECONDS`），**不新增受管配置键** —— 与既有先例一致
  （`fix-verify-serving-disk-reclaim` 的 `RECLAIM_GRACE_SECONDS = 600` 同款处置），
  从而不触发「新增配置项必须带 Dashboard 界面」约定下的一整套受管键接线。

## Capabilities

### New Capabilities

- `dashboard-live-session`: Fenix Web Dashboard 内的项目级自由 Claude 会话 ——
  会话进程的创建 / 输入 / 终止与空闲回收、事件流的增量订阅与全量接回、前端会话
  Modal 的消息渲染与输入。

## Impact

- **Affected specs**: 无既有 capability 被修改（新增独立 capability）。
- **Affected code**:
  - 新增：`core/dashboard/session_manager.py`、`core/dashboard/routes/session_routes.py`、
    `core/dashboard/static/src/pages/projects/components/SessionModal.tsx`、
    `tests/test_dashboard_session.py`
  - 修改：`core/dashboard/server.py`（生命周期接线）、`core/dashboard/routes/base.py`
    （路由表条目）、`core/dashboard/routes/__init__.py`（mixin 门面）、
    `core/dashboard/static/src/pages/projects/list.tsx`（入口按钮）、
    `core/dashboard/static/src/services/dashboard.ts`（API 客户端）、
    `core/dashboard/static/src/components/claude-msg/runEvents.ts`（终态事件分支）
- **运行时依赖**：`claude` CLI 必须在 dashboard 进程的 PATH 上（fenixd 既有硬依赖，
  `install.sh` 已校验）。
- **安全影响**：会话以 `--permission-mode bypassPermissions` 运行，即在该项目根目录下
  Claude 可不受询问地执行任意 Bash/Write/Edit。这与 fenixd 现有 implementer/verifier
  agent 的既有做法一致，但**面向人的入口**扩大了可达面：任何能访问 dashboard 的人
  （dashboard 仅绑定 127.0.0.1）都能获得任意代码执行。见 Risks。
- **不影响**：现有 run 流（`/api/runs/*`）、SPEC 生命周期、`agent_runner` 的任何行为。

## Non-Goals

- **不引入 CloudCLI / claudecodeui 服务或其源码**（含 `dist`/`dist-server` 产物）。
- **不做 `--resume` 接回 / 历史会话列表**（用户已决策：跟 dashboard 生命周期）。
- **不绑定 SPEC**：会话是项目级的，不在 SPEC 列表行的操作菜单中出现，也不读写
  `.fenix/STATE.md`、`spec/`、`.fenix/runs/` 任何产物。
- **不做**：逐 token 流式（不加 `--include-partial-messages`）、权限询问 UI、附件上传、
  语音输入、slash 命令菜单、模型选择器、会话导出。CloudCLI 的交互子系统整体不移植。
- **不改** `agent_runner` 去共享会话机制（agent 的 run 产物契约与自由会话语义不同）。
- **不做优雅中断当前轮**：`stop` 仅终止会话进程（本轮一并丢弃）。
