## Why

2026-09-29 验收 `add-dashboard-paging-and-etag` 时实测发现：SPEC 合入 push 后**运行中的 dashboard 进程仍是旧代码**（16:38 启动的进程跑着 21:04 合入后的主树），性能修复对用户不生效，直到人工重启。机制盘点：HookEngine 已有 `restart-dashboard` 动作（`tmux respawn-window` + 固化命令 + 端口可服务判据，`hook_engine.py:979`），`hooks.global` 作用域可匹配任意 SPEC 的任意状态事件（`match_hooks`，`hook_engine.py:299`）——但没有任何配置把 `pushed` 终态接到该动作上，dashboard 重启始终依赖人工。

## What Changes

- **pushed 终态自动重启 dashboard**：`hook_config()` 注入内置默认 global hook 条目（`builtin-push-restart-dashboard`，`events: [pushed]`，`action: restart-dashboard`）——零配置生效，走既有 HookEngine 动作，不新增机制。
- **动作层去抖**：`restart-dashboard` 动作加 60s 去抖窗口（进程内最近成功重启时间戳）：窗口内重复 `pushed` 事件（push 批次常见，如同日多个 verification-report 入库）幂等跳过，记 skipped 审计；重启后 dashboard 已加载最新主树代码，无需尾沿补发。
- **无会话静默跳过**：`tmux` 会话不存在时（dashboard 未运行的环境，如 CI/容器）从 failure 审计改为静默跳过——不产失败告警噪音（对齐人工告警降噪口径）。
- **逃生键**：新增配置键 `hooks.push_restart_dashboard`（bool，缺省 `true`），设为 `false` 时 `hook_config()` 不注入内置条目；设置页 HooksPanel 增加开关控件（新增配置项必须带 Dashboard 界面）。

## Capabilities

### New Capabilities

- `dashboard-push-restart`: SPEC pushed 终态自动重启 dashboard——内置 hook 注入、60s 去抖、无会话静默、逃生键。

### Modified Capabilities

（无——HookEngine 动作与 hooks 配置体系均为既有能力，本变更只补触发链与健壮性）

## Impact

- 后端：`core/hook_engine.py`（`hook_config` 注入 + `_action_restart_dashboard` 去抖与静默跳过及返回通道三态化；`validate_hook_entry` 无需改动——逃生键是 hooks 段 bool 键不经条目校验，注入条目本身合法可通过执行链校验）。
- 前端：`core/dashboard/static/src/pages/settings/components/HooksPanel.tsx`（逃生键开关）。
- 运行时数据：`/api/config` 读写链路自然携带新键（无 schema 迁移；gitignored 的 `.fenix/config.yaml` 由运行时写入，非交付物）。
- 兼容性：无 BREAKING——缺省行为新增（pushed 后重启 dashboard），既有 hook 配置与动作语义不变。
- 既有回归面：`add-spec-hooks` 的 hook 匹配/执行/审计链、`fenixd-dashboard-ops-family` 的 tmux 重启协议（`env -u CLAUDE_PID` 固化命令保持不动）。
