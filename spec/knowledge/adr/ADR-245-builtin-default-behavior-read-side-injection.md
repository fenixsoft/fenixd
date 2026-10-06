# ADR-245：零配置默认行为进代码——内置 hook 读侧注入，禁落地运行时配置文件

date: 2026-10-07
status: accepted

## Context

「SPEC pushed 后自动重启 dashboard」要求零配置生效，而项目运行时配置 `.fenix/config.yaml` 是 gitignored 文件：worktree 内的实现 agent 不可达（主树对实现 agent 只读、worktree 不含 gitignored 文件），把默认行为当作配置交付物的纯配置方案不可交付。HookEngine 已具备动作实现（restart-dashboard）与 global 作用域对任意 SPEC 的事件匹配，缺的只是把 pushed 终态接到动作上的触发链。

## Decision

默认行为进代码：`hook_config()` 读侧向返回副本的 global 段头部注入内置条目（`builtin-push-restart-dashboard`，pushed → restart-dashboard），注入条目走与用户条目完全相同的执行链（`validate_hook_entry` 校验、按 id 找回执行），不设旁路。两条硬纪律：MUST NOT 原地 mutate 入参 config——`match_hooks`/`_find_live_hook` 每次事件都重复调用 `hook_config()`，原地注入会逐次堆叠重复条目；MUST NOT 把内置条目持久化进配置文件——文件里已有实体条目后逃生键置 false 也无法阻止行为，直接违背「读侧注入，不改 config 文件」。逃生键（`hooks.push_restart_dashboard`，缺省 true）只控制注入与否；用户 global 列表手写同 id 条目时用户条目优先、不重复注入。后续一切「零配置默认行为」沿用同一形态：默认值进代码读侧，用户配置只承载覆盖与开关。

## Consequences

- 新项目零配置即生效；配置文件保持用户手写内容纯净（不出现机器注入实体），逃生键始终可信。
- 内置行为与代码严格同版，随代码发布与回滚；为覆盖内置行为保留的唯一口子是手写同 id 条目与逃生键。
- 代价：注入逻辑位于每次事件的读路径（常数开销）；默认行为没有配置可查，可发现性依赖设置页控件与知识真相源。
- 去抖等进程内状态不随注入持久化：daemon 重启后去抖时间戳清零，重启后的首个 pushed 会多重启一次 dashboard，设计内无害，不做跨进程去抖持久化。
