# Design — add-interrupt-recovery-preserve

## Context

重启链路现状（2026-09-05 核实）：

- supervisor（`bin/fenixd_supervisor.py:74-83`）：检测 `.fenix/restart_request` → SIGTERM daemon → 60s 未退出 → SIGKILL → 重启并清除请求。等待时长硬编码。
- daemon 停机（`fenixd.py shutdown()`）：禁新派发 → admin 池关闭 → `agent_runner.wait_for_running_agents()`（SIGTERM→interrupted 标记→≤10s grace→SIGKILL，总关停刻意 ≪ supervisor 60s，archived spec fix-graceful-shutdown-agents 的取舍）→ `_v2_stop_all` → `worktree_manager.cleanup_orphans()`。
- boot recovery（`fenixd.py:198` → `state_machine.recover_interrupted`，`core/state_machine.py:628-642`）：对 interrupted implementing spec 整段清空 implementer_run/branch/tester_run；`cleanup_orphans`（`core/worktree_manager.py:644-651`）按内存活动集合清孤儿 worktree。
- STATE 在跑期间本就持有 branch/implementer_run——问题不在信息缺失，而在 recovery 无差别清空。
- attempt 层盲复用已删 worktree 的秒挂缺口已由 3a 修复（fix-resume-stale-worktree，2026-09-05，`runner._worktree_path_valid` + repair 显式失败语义）。

事故账本：2026-09-04 add-run-cancel 首轮 run 19 分钟 + 3.5MB 转录整轮蒸发；restart_request 三连杀曾烧 4/6 重派预算（.fenix/restart-kills-inflight-fasttrack 记忆）。

## Goals / Non-Goals

- **Goals**：规划性重启不丢失已提交成果；恢复后按 resume 续做而非从零重派；清理与保全永不互删。
- **Non-Goals**：不做在跑 run 的增量落盘/检查点（claude 会话级续跑已由 --resume 覆盖）；不改非计划停机的快速语义；不做多 daemon 协同。

## Decisions

### D1 排水判定：restart_request 在册 = 规划性重启

daemon 信号处理收到 SIGTERM 后读 `.fenix/restart_request`：在册 → 排水模式（等在跑 run 终态，上限 `admin.shutdown_drain_seconds`，缺省 1800）；不在册 → 现行快速停机。理由：restart_request 是 supervisor 重启协议的唯一信号源（memory: supervisor-restart-protocol），语义上必为规划性；外部 kill/崩溃走非计划路径，保持既有快速语义（兼容 archived agent-shutdown-interrupt）。

### D2 supervisor 等待时长联动

supervisor SIGKILL 等待从硬编码 60s 改为读取 `admin.shutdown_drain_seconds + 120s` 余量（解析 .fenix/config.yaml；解析失败回退 60s 保持向后兼容）。禁止只改 daemon 不改 supervisor——否则排水期必被 SIGKILL 截断，排水形同虚设。

### D3 保全 sidecar：`.fenix/interrupted_runs.json`

仅排水超时仍需 terminate 时写入（正常终态无需保全）。字段：`[{spec, run_id, branch, worktree, ahead_commits, reason, timestamp}]`。boot recovery 消费后即清除对应条目。不塞进 STATE.md（避免混入 spec 状态表语义，与 self-review 的 STATE 隔离原则一致）。

### D4 recovery 保留判定：`git rev-parse main..branch`

有提交 → 保留 branch/implementer_run + 标记恢复续做；worktree 三态经单源查询：在场 → 原地，缺失 → 在既有分支上重建 worktree（worktree_manager 已支持 checkout 既有分支，add-merge-back-repair-lane 1.2 落地），不可用 → 降级清空重建并 WARNING。零提交 → 现行清空路径逐字节兼容。resume 派发复用 fast-track 继承语义（prompt 注入继承说明、attempt 校验已收敛）。

### D5 worktree 可用性单源：`worktree_manager.is_available`

返回三态（available / rebuildable / unavailable）：目录存在 + `git worktree list` 注册有效 + 分支 `rev-parse --verify` 可解析。`_take_reusable_worktree`、`_worktree_path_valid`（3a）、recovery、resume 认领全部收敛到该查询；`_worktree_path_valid` 保留为薄封装避免大范围签名变更。以 git 为真相（不信任内存表），与 repair lane 1.2 的判定口径一致。

### D6 cleanup 协调

`cleanup_orphans` 增加保护集参数（shutdown 路径传保全在册项 ∪ STATE 中保留分支的 worktree）；boot recovery 在 cleanup 之前完成保留判定，天然避免互删。

## Risks / Trade-offs

- **排水拖长重启窗口**：卡死 run 会耗满 drain 窗口。→ 上限封顶 + run 自身 timeout 兜底；`shutdown_drain_seconds: 0` 一键回退现行行为。
- **排水期 run 仍可能失败**：失败 run 走正常终态，daemon 退出，不影响保全机制。
- **非计划停机仍丢成果**：本 SPEC 不解决（SIGKILL 场景无法优雅保全）；3a 已封住其 resume 秒挂放大器，残余风险由「中断恢复保留分支」在非计划场景的 sidecar 缺失时降级为现状。
- **autostash 交互**：排水期 worker 结束会触发既有 stash/pop 流程，与现行无差异。

## Migration Plan

1. 落 is_available 单源与 cleanup 保护集（纯重构，行为等价）。
2. 落 recovery 保留判定 + sidecar（默认行为已变化：有提交分支不再清空）。
3. 落 daemon 排水 + supervisor 联动（缺省启用 drain=1800s；`shutdown_drain_seconds: 0` 可回退）。

## Open Questions

- 无（模式/窗口缺省值已由用户确认方向：排水缺省开启，窗口取 1800s 量级）。
