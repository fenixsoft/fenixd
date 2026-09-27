<!-- knowledge: capability=recovery-branch-anchor rev=1 sources=spec/archive/2026-09-19-fix-recovery-branch-anchor-without-worktree -->

# 恢复分支锚点

实现成功即落 STATE 分支锚点、新轮次派发前失效旧锚点，恢复链按三层回落解析锚点，使「已实现、未合并」的在飞成果在重启后可被找回续做。

## 现行规则

- 成功即落锚点：implement / repair run 到达终态成功时，在 merge-back（含 repair 的 re-merge-back）之前把该 run 的 `branch` 与 `implementer_run` 写入 STATE；`branch` 语义为「本轮实现分支」（取值集合与 merge-back 成功后写入一致，无取值漂移）。run 未达终态成功（失败、中断、被杀）不写入。
- 写入点定序在全部 merge 前置闸门之后：零变更哨（`core/pm_engine/dispatch.py:770`）、交付物守卫与缺件异议（`:844-900`）、tasks.md 收口复检（`:904`）等以 `status: ready/blocked` 早退的路径不残留本轮锚点——本轮已放弃、下一轮另建分支；零变更哨内的「确认型 no-op 放行」（直转 `implemented`）属终态成功。实现口径：锚点写入紧邻 merge 预演之前，或在上述早退分支内一并清锚点。
- 锚点随实现轮次失效：spec 进入全新实现轮次（非 `_recovery_resume` 续做的普通派发）时，先失效上一轮的 `branch`/`implementer_run`（清空或改写为本轮值）。实现位置落在全新实现派发的唯一入口（`core/pm_engine/dispatch.py:672` `_run_agent_worker` → implementer 分支内、`_recovery_resume` 续做判定之后、`run_implementer` 之前；fast-track 独立入口同样落点），使全部重派出口机械覆盖；不得按 `status: ready` 写点逐点枚举（出口清单以 `grep -n '"status": "ready"' core/pm_engine/dispatch.py` 为审计口径，枚举必然遗漏）。覆盖至少含 merge-back 失败降级 ready 重试、repair 熔断后的 fallback 重派、不经派发直接改状态的出口（含人工复位 blocked→ready 后重派）。
- 失效理由（约束性）：锚点解析链第一层是 STATE.`branch`，优先于第二层（在册 worktree）；上一轮锚点残留而新一轮在飞时重启恢复，会按第一层选中已放弃的上一轮分支并重建载体整轮续做，把新一轮在飞成果整轮晾掉。
- 三层回落解析（任一环节命中即停止）：① STATE 的 `branch` 字段；② worktree_manager 的 spec → 在册 worktree 事实查询（`git worktree list --porcelain` + worktree 命名约定）；③ git 分支命名空间枚举 `refs/heads/<prefix>/<spec>-*`。
- 枚举前缀与分支创建端同源：创建端硬编码 `fenix/`（`core/worktree_manager.py:223/226`），故 `<prefix>` 取 `fenix/` 或「配置 `worktree.implement_branch_prefix` ∪ `fenix/`」并集，不得仅凭配置值取前缀——非 `fenix` 配置下创建端仍产出 `fenix/<spec>-<ts>`，仅按配置枚举会扫空命名空间、该层静默失效。枚举不依赖内存表（`_active_worktrees`/`_wt_branches`），worktree 已被清理不放弃该回落——实现 run 成功收口会清理其 worktree，此时分支仅以 refs 形式存在。
- 候选排序：先取 `main` 为其祖先者（`git merge-base --is-ancestor main <branch>` 成立，即已含 main 的合并）中 committerdate 最新者；无「已含合并」候选时取 `git rev-list --count main..<branch>` 最大者。命中多个候选且无法唯一确定时，取排序最优者并打 WARNING 列出全部候选，不静默取首个。
- 候选清单按「完整 spec 名 + 分隔符边界」全等比较生成：分支名去掉 `<prefix>/` 后按最后一个 `-` 分段，末段须为纯数字时间戳、其前段须与 spec 名全等（口径与 `worktree_manager._wt_name_matches_spec` 一致）；不满足者不入候选。不得把 `<prefix>/<spec>-*` 的前缀 glob 命中集合直接当候选——spec 名可互为前缀（如 `fix-x` 与 `fix-x-y`），glob 会把 `fix-x-y` 的实现分支算作 `fix-x` 的候选、跨 spec 误配；`<prefix>/verify-<spec>-*` 形态的验证分支不是实现分支，不入候选。
- 零提交闸门先于排序：第三层候选与第一/二层同口径过「`main..branch` 非空」闸门；零提交候选（含分支 tip 与 main 同点——`main` 恰为其祖先不构成「已含未合并成果」，repair 已把 main 合入分支的形态必然 `main..branch` 非空）自候选清单剔除、不参与排序，避免其在排序中胜出又过不了闸门，把本可保留的其它候选误判为锚点不可得。全部候选零提交或无候选时，锚点判定不可得，走零提交清空重建路径。
- 强制留痕：恢复链在无任何锚点而走清空重建路径时打 WARNING，内容含 spec 名与命名空间枚举结果（候选分支名清单，无命中则显式标注为空），不得以无日志的早退结束判定；锚点已解析出分支但 `is_available` 三态判定载体不可用时，在既有降级 WARNING 中一并打出该分支名与降级原因，不额外引入无锚点结论。

## 溯源

- 2026-09-19 fix-recovery-branch-anchor-without-worktree — 新增成功即落锚点与新轮次失效旧锚点、三层回落解析（含命名空间枚举、创建端同源前缀与全等边界）、零提交闸门先于排序与锚点不可得强制留痕
