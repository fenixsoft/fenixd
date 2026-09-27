# SPEC 事件钩子（状态变化触发自定义动作）
<!-- knowledge: capability=spec-event-hooks rev=1
     sources=spec/archive/2026-09-12-add-spec-hooks -->

SPEC 状态变化发布事件，按全局/spec 级两级订阅触发七种动作（重启、git、webhook、shell），后台异步执行、审计留痕、失败告警不重试。

## 规则

- 事件发布：SPEC 进入任何状态（十状态枚举）后 ≤5 秒内发布一次事件，携带 spec 名、from_status、to_status、error（若有）、frozen 标志、时间戳；由 daemon 进程内唯一的全局状态观察者驱动，覆盖 dashboard 进程写入（admin 处置、人工恢复）与人工冻结直写等所有跨进程状态变化路径。
- 两级订阅：全局 hooks（对所有 SPEC 生效）与 spec 级 hooks（仅对该 SPEC 生效）；事件 `(spec, event_type)` 命中「events 含该类型的全部全局 hooks」+「该 SPEC 的 spec 级命中条目」，每个命中的 hook 为独立消费者各自执行；一个事件可触发多个消费者，互不阻塞。
- 每条 hook 配置：`events`（非空，十状态枚举内）、`action`（七种动作枚举）、`enabled` 布尔开关——`enabled=false` 时被有意跳过，不执行动作、不告警，审计状态记 `skipped`。
- 七种动作：
  - `restart-daemon`：创建 `.fenix/restart_request` 请求文件复用 supervisor 优雅重启协议；创建成功即动作成功，不得由 hook 执行器直接杀 daemon 进程。
  - `restart-dashboard`：以 `tmux respawn-window -k` 重启目标会话（可选参数 `target`，缺省 `fenix-dashboard`），命令满足 `env -u CLAUDE_PID` 且保持 8787 端口与原工作目录；重启后探测端口恢复可服务定成败，超时记失败。
  - `commit`：`git add -A` 后按提交信息模板执行 `git commit`（变量 `{spec}`、`{event}`，缺省 `[fenix] hook: {spec} {event}`）；工作区无变更视为 no-op 成功（审计记 `noop`，不告警）。
  - `push`：执行 `git push`（跟随当前分支 upstream）。
  - `commit-push`：先 commit 后 push；commit 为 no-op 时仍执行 push；push 失败不回滚已产生的本地提交。
  - `webhook`：向配置 `url` 发一次 HTTP POST（application/json），body 含 event/spec/from_status/to_status/ts/error/frozen/hook_id/action/project；2xx 成功，连接失败、非 2xx、超时（`timeout_seconds` 缺省 10）为失败；不提供消息模板引擎（钉钉/飞书等经 shell 动作适配）。
  - `shell`：`bash -c <command>` 在项目根执行，注入 `FENIX_HOOK_EVENT` / `FENIX_HOOK_SPEC` / `FENIX_HOOK_FROM_STATUS` / `FENIX_HOOK_TO_STATUS` / `FENIX_HOOK_ERROR` / `FENIX_HOOK_PROJECT_ROOT` 环境变量；退出码 0 成功，非 0 或超时（缺省 60，超时强制终止）为失败；stdout+stderr 尾部 ≤2KB 记入审计。
- 异步执行：分发与动作执行在 daemon 后台线程，不阻塞状态机写路径与 PM Engine 调度；单个慢动作（如不可达 webhook）不延迟其他 hook、不阻塞后续状态转换事件。
- 失败处理：写 status=failure 审计记录 + 经 admin_store 发一条 `hook_failure` 站内告警（含 spec、事件、动作、错误摘要）；不自动重试；告警不做去重降噪（hook 失败是真实信号，每次可见）。
- 审计：每次触发向 `.fenix/hook_audit.jsonl` 追加一条 JSON（ts、spec、event、from_status、to_status、hook_id、action、scope、status（success/failure/noop/skipped）、detail ≤2KB、duration_ms），文件 append-only；`GET /api/hooks/audit` 按 spec 过滤、limit（缺省 20）返回尾部倒序记录。
- 配置持久化于 `.fenix/config.yaml` 的 `hooks` 段（`hooks.global` + `hooks.specs.<spec名>`），经配置热更新（30s mtime）生效；`POST /api/config` 保存时校验（events 枚举、动作枚举、webhook 必填 url、shell 必填 command），违规返回 400；无 `hooks` 段 = 空订阅、零行为。
- Dashboard：SPEC 详情页「失败截图」页签之后提供「Hook」页签——生效中的 hooks（合并全局与 spec 级，来源列标「全局/本 spec」）、本 spec hooks 的增删改与启停（表单按动作类型显隐参数字段）、最近执行审计列表；设置页「Hook」面板提供全局 hooks 管理与跨 SPEC 审计尾部。

## 溯源

- 2026-09-12 2026-09-12-add-spec-hooks — 新增事件钩子：全局状态观察者与事件发布、两级订阅与七种动作、异步执行与失败告警不重试、hook_audit 审计与查询 API、配置契约与 Dashboard 两个管理面
