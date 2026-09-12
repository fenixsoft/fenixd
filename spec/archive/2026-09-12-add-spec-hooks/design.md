# Design: add-spec-hooks

## Context

fenixd 是单项目自动化研发守护进程：daemon（supervisor 直启）驱动 SPEC 生命周期状态机，dashboard（tmux 会话 `fenix-dashboard`，Python 标准库 http.server，端口 8787）提供 Web 界面，两进程通过 `.fenix/` 下的状态文件交互。

现状要点：

- 状态机共 10 状态（drafted/ready/implementing/implemented/testing/verified/bug-found/blocked/done/pushed），`core/state_machine.py` 的 `transition()` 与 `update_spec()` 是仅有的两个写入口；人工冻结（`freeze_spec`）走 `update_spec` 直写 `status=blocked`，**不经过 `transition()`**。
- `core/event_bus.py` 已有 daemon 进程内唯一的全局状态观察者：`_watch_loop` 每 2s 对 STATE.md 做 checksum 轮询，`_dispatch_changes` diff 出状态变化（`_known_specs` 保存上次快照）后调 `pm_engine.handle_event`；`full_scan` 周期兜底。启动时 `_update_known_state()` 先记录初始快照，因此 daemon 重启不会把存量 spec 当作新事件重发。
- dashboard 进程也会写 STATE.md（admin 处置、人工恢复等），写路径与 daemon 跨进程。
- daemon 优雅重启已有文件协议：touch `.fenix/restart_request` → supervisor SIGTERM daemon → 等退出 → 重启清请求。
- dashboard 运行在 tmux 会话 `fenix-dashboard`；重启协议要求 `env -u CLAUDE_PID`（防 claude-watchdog 绑会话自杀）且保持 8787 端口。
- 配置：`.fenix/config.yaml`，`core/config.py` 30s mtime 轮询热更新；dashboard 设置页通过 `POST /api/config`（原子写、校验）保存。
- 站内告警：`core/admin_store.py` `append()` 写 `.fenix/admin_alerts.jsonl`，dashboard 概览/运维记录可见。
- push 目前归人工门禁（fenix-approve）与 push 流程负责；`core/archive_commit.py` 仅做 pathspec 限定的归档提交、只 commit 不 push。

用户已确认的四项决策：通知走 webhook 且必须写审计日志；动作集合为内置 + 自定义 shell；失败处理为记日志 + 站内告警（不重试）；执行模式 full。

## Goals / Non-Goals

**Goals**

1. SPEC 任意状态变化（含跨进程写入与人工冻结）最终都能触发用户订阅的 hook，一个事件可触发多个消费者。
2. 提供七种动作：`restart-daemon` / `restart-dashboard` / `commit` / `push` / `commit-push` / `webhook` / `shell`，其中前五种覆盖用户点名的管理动作。
3. 全部 hook 触发与执行结果可审计（`.fenix/hook_audit.jsonl`），失败产生站内告警。
4. 两级配置（全局 / spec 级）+ Dashboard 配置界面（spec 详情页 Hook 页签、设置页 Hook 面板）。

**Non-Goals**

- 不做 hook 失败自动重试（commit/push 类动作重试有幂等风险）。
- 不做 webhook 消息模板引擎（钉钉/飞书等特殊格式用 `shell` 动作 + curl 兜底适配）。
- 不做用户级/跨项目 hook 配置（仅当前项目 `.fenix/config.yaml`）。
- 不做审计日志轮转（append-only，容量治理留待后续 spec）。
- 不做 UI 上的「手动测试触发」按钮。
- 不做 hook 触发风暴/循环的自动熔断（用户配置 shell 改状态导致循环属配置错误，靠审计与告警暴露）。

## Decisions

### D1: 事件发布点 = EventBus 状态 diff，而非 state_machine 进程内回调

hook 分发挂在 `event_bus._dispatch_changes` 的状态 diff 处（diff 出 `old_status != new_status` 即产生一条事件，同时分发给 PM Engine 与 hook 引擎），而非在 `state_machine.update_spec()` 内部回调。

- 理由：STATE.md 存在**跨进程写入**（dashboard 进程的 admin 处置/人工恢复），进程内回调只能覆盖 daemon 自己的写入；EventBus 是 daemon 进程内唯一的全局观察者，天然覆盖所有进程的写入路径（含 `freeze_spec` 直写 blocked 的路径）。
- 代价：事件延迟 ≤ 2s（轮询周期）。hook 全部是管理类动作（重启/提交/通知），2s 延迟无感。
- 备选（否决）：`update_spec` 收口回调——即时但漏跨进程写入；需要回调注入改动 82 个调用点所在路径的装配，侵入更大。
- daemon 停机窗口内的状态变化漏发为已知边界（`full_scan` recovery 仅对可恢复态补派发 PM Engine 事件，不补发 hook）：done 等终态转换由 daemon 进程自身完成，停机漏发窗口极小，接受。

### D2: hook 配置存 `.fenix/config.yaml` 的 `hooks` 段，而非 `.spec.yaml`

```yaml
hooks:
  global:                      # 设置页配置，对所有 spec 生效
    - id: h-3f9a2b             # 短随机 id（前端生成），UI 增删改的稳定 key
      enabled: true
      events: [done, blocked]  # 订阅的事件类型（状态枚举，非空）
      action: restart-daemon   # restart-daemon|restart-dashboard|commit|push|commit-push|webhook|shell
      url: ""                  # webhook 必填：POST 目标 URL
      command: ""              # shell 必填：命令行（bash -c 执行）
      message: ""              # commit/commit-push 可选：提交信息模板，缺省 "[fenix] hook: {spec} {event}"
      timeout_seconds: 60      # shell/webhook 可选：超时，缺省 60（webhook 缺省 10）
      target: ""               # restart-dashboard 可选：目标 tmux 会话名，缺省 "fenix-dashboard"（测试/多实例时指向沙箱会话）
  specs:                       # spec 详情页配置，仅对该 spec 生效
    add-xxx:
      - { id: h-7c1d9e, enabled: true, events: [done], action: commit-push }
```

- 理由：配置不入库（`.fenix/` 已 gitignore）——UI 保存不会弄脏工作区、不会触发 merge-back 冲突（对比 `.spec.yaml` 方案：spec 目录是入库的，dashboard 写它会要求配套自动提交链路）；单文件读写对 UI 与 daemon 都最简单；热更新机制（30s mtime）免费获得配置生效。
- spec 归档后 `hooks.specs` 下的条目残留为已知噪音，可接受（不执行、不影响匹配）。
- 备选（否决）：`.spec.yaml` 内嵌——配置与 spec 同生命周期更「优雅」，但引入 dashboard 写入库文件的提交/冲突连锁问题，复杂度不成比例。

### D3: 执行模型 = daemon 进程内异步线程池，每事件并发分发，不排队不持久化

- 匹配：事件 `(spec, event_type)` 命中「全局 hooks 中 events 含该类型」+「`hooks.specs[spec]` 中 events 含该类型」的全部条目，每条为一个独立消费者。
- 执行：每个命中的 hook 在独立 daemon 线程中执行（并发），互不阻塞；执行前实时从 config 对象读 `hooks` 段（享受热更新，无独立缓存失效问题）。
- 不阻塞状态机：EventBus 分发线程只投递任务，动作在线程池跑。
- 进程重启丢失在途执行：接受（管理动作下一次事件自然会再触发；webhook 丢失属通知级损失）。
- 备选（否决）：进程外队列/子进程执行器——为低频管理事件引入持久化队列过度设计。

### D4: 动作实现协议

- `restart-daemon`：`touch .fenix/restart_request`，复用 supervisor 既有优雅重启协议。动作本身瞬时完成，touch 后即视为成功（daemon 退出/拉起由 supervisor 负责）。
- `restart-dashboard`：daemon 内子进程执行 tmux 会话重启。实现时从当前存活会话提取实际启动命令固化（`tmux respawn-window -k -t <target> "<原启动命令>"` 形态），目标会话名取条目可选参数 `target`（缺省 `fenix-dashboard`），命令必须满足：`env -u CLAUDE_PID`（防 claude-watchdog 绑会话自杀）、保持 8787 端口与原工作目录。重启后以「8787 端口重新可服务」为成功判据（探测超时则失败告警）。
- `commit`：`git add -A` + `git commit -m <message 模板渲染>`（模板变量 `{spec}`/`{event}`）。**无变更（nothing to commit）视为 no-op 成功**，审计记 `noop`；git 失败视为失败。
- `push`：`git push`（跟随当前分支 upstream）。无新提交时 push 为远端 no-op 成功。
- `commit-push`：先 commit 后 push；commit 为 no-op 时仍执行 push；push 失败不回滚 commit（本地提交保留，失败告警）。
- `webhook`：POST JSON，`Content-Type: application/json`，body：
  ```json
  {"event": "done", "spec": "add-xxx", "from_status": "verified", "to_status": "done",
   "ts": "2026-09-06T12:00:00+00:00", "error": null, "frozen": false,
   "hook_id": "h-3f9a2b", "action": "webhook", "project": "<项目名>"}
  ```
  2xx = 成功；连接失败/非 2xx/超时 = 失败。响应体不转发（截断 2KB 记审计）。
- `shell`：`bash -c <command>`，cwd = 项目根；注入环境变量 `FENIX_HOOK_EVENT` / `FENIX_HOOK_SPEC` / `FENIX_HOOK_FROM_STATUS` / `FENIX_HOOK_TO_STATUS` / `FENIX_HOOK_ERROR` / `FENIX_HOOK_PROJECT_ROOT`；超时强制 kill（`timeout_seconds`，缺省 60）；退出码 0 = 成功；stdout+stderr 尾部 2KB 记审计。
- 模板渲染失败（如 message 含未知变量）不致命：未知变量原样保留。

### D5: 失败处理与告警

动作失败（含 webhook 非 2xx、shell 非零退出/超时、git 失败、dashboard 重启探测失败）时：

1. 审计记录 `status=failure`（含错误摘要）——用户明确要求的审计底线。
2. `admin_store.append()` 写一条 hook 失败告警（`signal_type: hook_failure`，severity `major`，description/evidence 含 spec、事件、动作、错误摘要），复用现有告警展示与处置链路。
3. 不重试、不阻塞其他 hook 与状态机。告警不做去重/降噪——真实失败应每次可见（与「合成兜底静默化」的既有降噪决策不冲突：hook 失败是真实信号）。

### D6: 审计日志 = `.fenix/hook_audit.jsonl` append-only

每条记录：`{"ts", "spec", "event", "from_status", "to_status", "hook_id", "action", "scope": "global|spec", "status": "success|failure|noop|skipped", "detail": "<错误/输出摘要 ≤2KB>", "duration_ms"}`。skipped 用于 `enabled=false` 等有意跳过（不告警）。由 hook 引擎统一写入（带锁追加，风格对齐 `admin_store`）。dashboard 经 API 读尾部 N 条。

### D7: Dashboard API 与前端

- API（并入 `core/dashboard/server.py`，零新增依赖）：
  - hooks 配置读写并入现有 `GET/POST /api/config` 通道（`hooks` 段作为受管配置的一部分，享受原子写与校验）；POST 校验规则：`events` 非空且取值合法、`action` 合法、webhook 必有非空 `url`、shell 必有非空 `command`，违规 400。
  - 新增 `GET /api/hooks/audit?spec=<name>&limit=20`：读 `.fenix/hook_audit.jsonl` 尾部（可按 spec 过滤），返回倒序列表。
- spec 详情页 Hook 页签（`projects/detail.tsx`，「失败截图」页签之后）：
  - 「生效中的 Hooks」区：全局 + spec 级合并列表，来源列标注「全局/本 spec」，含启停状态。
  - 「本 spec 的 Hooks」区：spec 级 hooks 的增删改/启停（事件多选 + 动作下拉 + 参数表单按动作类型显隐）。
  - 「最近执行」区：该 spec 的审计记录（时间/动作/结果/耗时/摘要）。
- 设置页 Hook 面板（`settings/index.tsx` 菜单新增 `hook` 项，面板组件 `HooksPanel.tsx`）：全局 hooks 增删改/启停 + 最近执行记录，结构复用同一套 Hook 编辑组件。
- 前端产物 `dist` 不入库：交付物声明以 `core/dashboard/static/dist/index.html` 为锚点，merge 后框架自动重建，agent 不提交 dist。

### D8: 代码落点与装配

- 新增 `core/hook_engine.py`（单文件，风格对齐 `event_bus.py`/`admin_store.py`）：`HookEngine` 类（配置读取校验、事件匹配、线程执行、七种动作实现、审计写入、失败告警）。daemon 启动装配时实例化，注入 `event_bus`（构造参数可选 `hook_dispatcher`，EventBus diff 处调用，未注入则维持现状——状态机与 EventBus 不产生对 hook 的硬依赖）。
- `commit`/`push` 复用 subprocess + 项目根执行；不修改 `archive_commit.py`（其 pathspec 限定语义与 hook 的全工作区提交是两回事）。
- 审计读取放 `core/hook_engine.py` 导出的纯函数（dashboard server 直接 import），不在 `data.py` 堆叠。

## Risks / Trade-offs

- [daemon 停机窗口内的状态变化漏发 hook] → 终态转换由 daemon 自身完成、窗口极小；`full_scan` recovery 间接缓解；已知边界，接受（D1）。
- [`push` 动作绕过人工门禁 fenix-approve] → hook 配置即用户显式授权自动化推送，属 proposal 明示的语义扩展；审计 + 失败告警保证可观测。
- [`shell` 动作执行任意命令] → hook 配置仅可经 dashboard/本机配置文件写入，风险面与现有设置页一致；超时强制终止 + 输出截断限制爆炸半径。
- [用户配置 shell 改状态导致 hook 自激循环] → Non-Goal 不做熔断；审计日志与失败告警使循环可见；文档（帮助文案）提示不要在 hook 中修改 spec 状态。
- [`restart-dashboard` 由 daemon 执行会短暂断开用户浏览器连接] → dashboard 前端已有 SSE/轮询重连逻辑；重启探测成功才记 success，失败告警。
- [EventBus 2s 轮询期间同 spec 连续多次状态跳变被合并] → diff 只看到 latest from/to；管理动作不依赖中间态逐拍触发，接受；审计如实记录观察到的 from/to。
- [`hooks` 段配置被 `POST /api/config` 并发写竞争] → 复用现有原子写与校验路径（该路径已处理受管配置的读写一致性）。

## Migration Plan

无数据迁移。`.fenix/config.yaml` 无 `hooks` 段 = 空订阅、零行为，完全向后兼容；部署后用户按需在 UI 配置。回滚 = 移除代码 + 配置段残留无害。

## Open Questions

无——四项关键分叉（通知渠道、动作集合、失败策略、执行模式）已由用户确认。
