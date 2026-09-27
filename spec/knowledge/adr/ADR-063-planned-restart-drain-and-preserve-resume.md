# ADR-063：停机分规划性/非计划两档，恢复按 git 事实保全续做

date: 2026-09-11
status: accepted

## Context

重启一律秒级排水的代价：规划性重启把在飞 run 已提交的成果整轮蒸发、烧掉重派预算；但一律长排水又让非计划停机（外部 kill/崩溃）无谓拖长、且无法优雅保全。恢复侧若无差别清空 implementing 状态，已提交分支与 implementer 记录全部丢失。本裁定推翻 ADR-015 的「恒快速排水、不扩展 supervisor 窗口」——快速排水保留，但不再是唯一停机形态。

## Decision

- **停机分两档**：`.fenix/restart_request` 在册 = 规划性重启 → 排水模式，等在跑 run 自然终态，上限 `admin.shutdown_drain_seconds`（0 = 立即快速停机）；不在册 = 非计划停机 → 保持既有快速 terminate。
- **daemon 与 supervisor 成对联动**：supervisor SIGKILL 等待 = 排水窗口 + 120s 余量；禁止只改一侧，否则排水期必被强杀截断。开箱缺省排水窗口为 0（快速停机 + 恢复续做承接）。
- **保全走 sidecar**：排水超时仍需 terminate 的 run 落 `.fenix/interrupted_runs.json`（spec/branch/worktree/ahead_commits），调度类元数据不进 STATE.md。
- **恢复按 git 事实保全**：`git rev-parse main..branch` 有提交 → 保留分支与 implementer_run，标记恢复续做——重新派发新 run 在既有分支上续做并 prompt 注入继承说明（分支级续做，非会话级 resume）；worktree 三态（在场/重建/不可用）由单一可用性查询判定，以 git 注册信息为真相、不信任内存表；零提交走既有清空重建。
- **清理与保全协调**：boot recovery 先完成保留判定再执行孤儿清扫，清扫带保护集参数（保全在册项 ∪ 保留分支的 worktree），永不互删。
- 每 agent 级 terminate 链（SIGTERM → interrupted 标记 → 短宽限 → SIGKILL）与 interrupted 终态证据语义保留，在排水超时与非计划路径生效。

## Consequences

- 规划性重启不再丢失已提交成果；卡死 run 会耗满排水窗口（run 自身超时兜底，窗口 0 可一键回退快速停机）。
- 非计划停机仍走快速路径，sidecar 缺失时降级为清空重建——已提交分支的保全以 sidecar/git 事实为限。
- supervisor 等待窗口随排水配置拉长，是有意的成对语义。
