## Why

fenixd 的 SPEC 生命周期（drafted→…→done/pushed）目前只在 dashboard 上被动展示：spec 完成、陷入困境（blocked）等关键节点发生时，用户必须自己盯着页面或翻日志才能发现，后续的管理动作（重启服务让新代码生效、提交/推送产物）也全部靠人工执行。需要一个 hook 机制把「SPEC 状态变化」变成可订阅的事件，让用户把重复性的管理动作自动化。

## What Changes

- 新增 SPEC 状态变化事件流：spec 进入任何状态（drafted/ready/implementing/implemented/testing/verified/bug-found/blocked/done/pushed）时自动发布事件，事件含 spec 名、from/to 状态、错误信息、时间戳。
- 新增 hook 订阅与执行引擎（daemon 侧）：
  - 两级配置：全局 hook（对所有 spec 生效，设置页配置）+ spec 级 hook（仅对该 spec 生效，spec 详情页配置）；一个事件可同时匹配多个 hook（多消费者）。
  - 内置动作：`restart-daemon`（优雅重启 daemon）、`restart-dashboard`（优雅重启 dashboard）、`commit`（提交变更）、`push`（推送变更）、`commit-push`（提交并推送）、`webhook`（POST JSON 通知，含审计）。
  - 自定义 `shell` 动作：执行用户配置的命令行，注入事件上下文环境变量，带超时。
  - 异步执行：hook 分发不阻塞状态机写入路径；动作失败不重试。
- 新增 hook 审计日志：每次 hook 触发与执行结果（成功/失败/跳过、耗时、输出摘要）追加写入 `.fenix/hook_audit.jsonl`。
- 失败处理：动作执行失败时写审计日志 + 发站内告警（复用 admin_alerts 通道），不静默。
- hook 配置持久化到 `.fenix/config.yaml` 的 `hooks` 段，随现有配置热更新机制生效（≤30s）。
- Dashboard 前端：
  - spec 详情页在「失败截图」页签后新增「Hook」页签：展示该 spec 生效的全部 hooks（含全局来源标注）、管理 spec 级 hooks（增删改/启停）、查看该 spec 最近 hook 执行记录。
  - 设置页新增「Hook」面板：管理全局 hooks（同款增删改/启停）、查看最近执行记录。
- 新增 Dashboard API：hooks 配置读写（并入现有 `/api/config` 通道）、hook 审计记录查询。

## Capabilities

### New Capabilities

- `spec-event-hooks`: SPEC 状态变化事件的发布、hook 订阅匹配、七种消费动作（restart-daemon / restart-dashboard / commit / push / commit-push / webhook / shell）执行、失败告警与审计日志、两级 hook 配置及 Dashboard 配置界面（spec 详情页 Hook 页签 + 设置页 Hook 面板）。

### Modified Capabilities

<!-- 无：spec/specs/ 下当前无活跃 capability specs，本变更为纯新增。 -->

## Impact

- **后端（daemon 进程）**：新增 `core/hook_engine.py`（事件分发、匹配、动作执行、审计写入）；`core/event_bus.py` 在状态 diff 处挂接 hook 分发回调；`core/dashboard/server.py` 新增 hooks 配置与审计查询 API。
- **配置**：`.fenix/config.yaml` 新增 `hooks` 段（global + specs 两级）；依赖现有配置热更新（30s mtime 轮询）。
- **前端**：`core/dashboard/static/src/pages/projects/detail.tsx`（新增页签）、`core/dashboard/static/src/pages/settings/index.tsx`（新增菜单项）、新增 Hook 管理组件；前端产物 `dist` 不入库，merge 后由框架自动重建。
- **既有语义的明确化**：现有架构中 push 由人工门禁（fenix-approve）负责；本能力提供的 `push`/`commit-push` 动作是用户通过 hook 配置显式授权的自动推送，属有意为之，不改变 fenix-approve 门禁本身。
- **运维协议复用**：`restart-daemon` 复用 `.fenix/restart_request` 优雅重启协议（supervisor 已支持）；`restart-dashboard` 需新增 tmux 会话重启执行路径。
