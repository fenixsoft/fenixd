# pushed 终态自动重启 dashboard

<!-- knowledge: capability=dashboard-push-restart rev=1
     sources=spec/archive/2026-10-07-add-push-restart-dashboard-hook -->

任一 SPEC 合入（pushed 终态）后自动重启 dashboard 进程，主树最新代码无需人工重启即对用户生效；由 HookEngine 的内置默认 hook 条目驱动，零配置生效。

## 规则

- 内置默认条目：`hook_config()` 在返回副本的 global 段头部注入 `builtin-push-restart-dashboard`（`events: [pushed]`、`action: restart-dashboard`），对全部 SPEC 生效；与用户级 hooks 配置叠加，各自独立执行互不吞并。
- 读侧注入纪律：注入只作用于 `hook_config()` 的返回副本，MUST NOT 原地修改入参 config、MUST NOT 把内置条目持久化进 `.fenix/config.yaml`——`match_hooks`/`_find_live_hook` 每次事件都重复调用 `hook_config()`，原地注入会逐次堆叠重复条目；条目一旦落盘，逃生键置 `false` 也无法阻止重启。用户 global 列表已有同 id 条目时用户条目优先，不重复注入。内置条目走与用户条目同一执行链（`validate_hook_entry` 校验、按 id 找回执行），无旁路。
- 逃生键：配置键 `hooks.push_restart_dashboard`（bool，缺省 `true`，仅显式 `false` 关闭，非法值按缺省开启）为 `false` 时 `hook_config()` 不注入内置条目，pushed 不再触发重启，用户自定义 hooks 不受影响。设置页 HooksPanel 提供开关控件，修改经既有 `/api/config` 读写链路持久化。
- 重启动作：`restart-dashboard` 以 `tmux respawn-window -k` 重启 `fenix-dashboard` 会话（固化命令带 `env -u CLAUDE_PID`，保持端口与原工作目录），以端口重新可服务为成功判据。
- 去抖窗口：60 秒，锚定进程内最近一次成功重启的 monotonic 时间戳。窗口内的后续触发幂等跳过，记 skipped 审计；重启失败不写时间戳，窗口内再次触发可重试。不做跨进程持久化——daemon 重启后时间戳清零，重启后的首个 pushed 会多重启一次，设计内无害。
- 并发防重：去抖检查与「标记重启中」在同一锁临界区一次完成——多条不同 id 的 restart-dashboard hook（内置条目与用户自挂条目）并发命中时仅首个认领者执行动作，其余按 skipped 跳过，dashboard 不会被连续弹两次。
- 无会话静默跳过：tmux 会话不存在（或 tmux 不可执行）是环境态而非操作失败，动作返回 skipped 并记 debug 日志，不产 failure 审计、不升级人工告警；会话存在但 respawn 或端口探测失败仍记 failure（真故障）。
- 边界：本链路只重启 dashboard，不自动重启 daemon——pushed 时可能存在其它 SPEC 的在飞 run，daemon 重启会打断在飞批，daemon 重启维持 supervisor/人工链路。

## 关键行为

- push 批次：同日多个 SPEC 相继 pushed（如 10s 内 3 个）只发生一次真实重启，其余触发跳过并留 skipped 审计，dashboard 无多次闪断。
- 重启瞬间浏览器 SSE 断连由 EventSource 自动重连兜底，用户感知为一次 ≤5s 闪断；60s 去抖窗口内第二次 push 的代码延迟到下一次 pushed 才生效。

## 溯源

- 2026-10-07 add-push-restart-dashboard-hook（spec/archive/2026-10-07-add-push-restart-dashboard-hook） — 新增能力：内置条目读侧注入与逃生键、restart-dashboard 60s 去抖与并发认领、无会话静默跳过、HooksPanel 开关
