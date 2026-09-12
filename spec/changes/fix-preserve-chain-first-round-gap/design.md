## Context

`add-interrupt-recovery-preserve`（`daf4df7d`，2026-09-05）与 `add-impl-wip-checkpoint`（`ad2fb912`，2026-09-10）共同建成了一条中断保全链：排水期 sidecar 保全 → orphan 清理保护集 → boot recovery 保留分支续做 → resume 原地续做。2026-09-11 07:51Z 的规划性重启中，`impl-add-blocked-reverify-lane-1789107185-a1` 在排水超时后被 SIGTERM 强杀，128 分钟工作全丢，保全链无一条生效。事故当日 HEAD（`d0fce202`）已包含上述两个机制，故这不是「机制缺失」而是「机制在特定窗口全盲」。

源码级定位（两条独立缺陷叠成一条因果链）：

| | 缺陷 | 位置 | 表现 |
|---|---|---|---|
| A | `branch` 登记滞后于 run 生命周期 | `dispatch.py:995`、`:2172`（仅完成态写入）；读取方 `fenixd.py:1114`、`state_machine.py:868` | 首轮在飞 run 的 STATE `branch=None` → sidecar 写 `branch:''/worktree:''`、保护集为空、`_recovery_preserve_spec` 直接 `return False` |
| B | 删除路径无前置留档 | `worktree_manager.py:638`（唯一调用点，位于失败兜底分支）；`cleanup_orphans:725`、`cleanup:554` | orphan 清理无快照；`--force` 成功路径亦无快照 |

事故日志 `Preserving interrupted run … branch 'none', worktree 'none', ahead=0` 正是缺陷 A 的直接产物：保全条目写出来了，但三个字段全空，保护集 `protected=∅`，随后的 orphan 清理无差别执行。

## Goals

- 首轮在飞 run 遭遇排水强杀时，其 worktree 与分支 MUST 被保全链正确识别，工作区不因清理而丢失。
- 任何 worktree 目录被物理删除前 MUST 留有 dirty 快照引用，事后可取证。
- 既有语义零回归：非计划 SIGTERM 快速停机、零提交分支清空重建、零提交走现行路径三条行为逐字节不变。

## Non-Goals

- 不延长排水窗口（`admin.shutdown_drain_seconds` 缺省仍 1800，0=快速停机）。长活 run 自适应延长只是推迟问题，不解决保全链失明。
- 不改变 `git stash create` 留档机制本身（沿用 `_snapshot_dirty_worktree`）。
- 不改动 verify/merge-back 链路。

## Decisions

### D1：新增 spec → branch/worktree 的 git 事实查询，作为 STATE 缺失时的回落源

保全与恢复保留判定的分支取值一律经该查询回落，不新增任何 STATE 中间态写入。

**为什么不用 `_active_worktrees` / `_wt_branches` 内存表**：这两张表在 `worktree_manager` 构造时建立（`worktree_manager.py:138-139`），键为**路径**而非 spec 名，且是**纯内存态**（代码自陈「daemon 重启即失」，见 `:2954` 注释）——排水强杀场景下它恰好还在（同一进程），但 boot recovery 路径读不到任何东西。同一文件里已有 `find_worktree_path` / `is_available` 两条「以 git 为真相、不信任内存表」的先例（`:2956`、`:3073`），新查询 MUST 沿用同一口径：`git worktree list --porcelain` 取在册 worktree 全集，按 worktree 目录命名约定（`impl-<spec>-<timestamp>`，见 `worktree_manager.py` 创建路径）匹配 spec，再经 `is_available` 三态校验。

**否掉的方案一**：派发时就把 `branch` 写进 STATE。STATE 是状态机权威，`branch` 语义为「该 spec 已完成任务的产出分支」，被 `prompt_builder.py:760/794`、recovery、merge-back 等多处读取；在 run 未到终态时写入会造成「branch 有值但 run 在飞」的中间态，污染其他判定路径（例如确认型 no-op 与 merge-back 的完成态假设）。回落读取没有这个问题——它只改变读取方的容错，不改变写入语义。

**否掉的方案二**：只把 `_active_worktrees` 加个 spec 索引。它解决不了 boot 路径（重启后表空），会让同一缺口在「不排水直接崩溃」场景下换个形态复发。

### D2：留档从「失败兜底」改为「删除前置动作」

`_snapshot_dirty_worktree` 目前唯一调用点在 `cleanup()` 的 `if result.returncode != 0:` 分支内（`:622` → `:638`）。而该处 `git worktree remove` 在 `success=False` 时带 `--force`，**通常成功**，于是快照在最需要它的路径上根本不触发；`cleanup_orphans` 更是完全没有留档。

方案：把快照调用提到删除动作之前，覆盖 `cleanup_orphans` 与 `cleanup` 两条路径的所有删除分支。快照失败降级 WARNING 不阻塞删除（沿用 D4 既有降级语义）。

**代价**：删除路径多一次 `git stash create`（对 dirty worktree 才实际产生对象）。以既有实现为据该调用已有 `timeout` 保护，量级为毫秒至百毫秒，相对关机路径（排水 1800s 量级）可忽略。

### D3：保护集与保留判定同步回落注册表

sidecar 条目 worktree 为空串时，以该 spec 在册 worktree 补入保护集。保守方向选择「多保不删」：宁可留下一个本该清理的 worktree（下轮 orphan 清理仍可回收），也不能删掉一个本该保全的。

### D4：非计划 SIGTERM 路径不进入本次改动范围

非计划停机（restart_request 不在册）不走排水、不写 sidecar，其快速停机语义 MUST 保持不变。改动点需以「仅在保全/清理路径生效」为界，新增分支不得影响该路径。

## Risks

- **停机关键路径回归**：保全、清理、recovery 均运行在 shutdown/boot 关键路径，异常会阻塞停机。缓解：所有新增查询与快照调用 MUST 有超时与异常降级（WARNING 不阻塞）；以既有 Scenario「非计划 SIGTERM 行为零变化」「零提交分支走现行清空」作为回归红线。
- **保护集过度保守**：回落查询可能把已产出但未清理的 worktree 纳入保护，导致目录堆积。缓解：保护集仅在 dev-server 停机与 orphan 清理窗口生效；下轮清理会重新评估。堆积上限由 `cleanup_stale_worktrees`（`:1811`）兜底。
- **命名约定匹配歧义**：`impl-<spec>-<ts>` 约定下，spec 名互为前缀（如 `fix-x` 与 `fix-x-y`）时可能误匹配。缓解：匹配 MUST 以完整 spec 名为准（分隔符边界锚定，非子串包含），且与 `is_available` 的分支校验联合判定；歧义命中时 MUST NOT 静默取第一个，按不可用处理并 WARNING。
- **首轮分支可能尚未有提交**：首轮在飞 run 若尚未 commit，分支相对 main 零提交，按既有语义仍走清空路径——这是**正确的**（无提交则无工作可丢）。本改动只保证「有提交时能被保住」，不承诺保住未提交的脏工作区——后者由 D2 的快照留档兜底取证（而非自动恢复）。
