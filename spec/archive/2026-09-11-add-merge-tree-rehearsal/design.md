# Design — add-merge-tree-rehearsal

## Context

merge-back 现状（2026-09-05 核实）：

- git 层：`worktree_manager.merge_back_from_branch`（`core/worktree_manager.py:1563-1726`）在 `_main_tree_lock` guard 段内 stash → merge → 冲突则 abort（主树保持干净）→ 返回 `MergeConflictInfo`（冲突路径 + 分类）。主树在冲突场景经历「stash 收拢 → 半合并态 → abort 回滚」全舞蹈，只是最终干净。
- 调度层：implementer（`core/pm_engine/dispatch.py:700-766`）与 fast-track（`:1176-1224`）失败分支均先做 fp 指纹记账（`_merge_fp`/`_merge_streak`），再按 `_should_enter_repair`（语义冲突 + 熔断未触发 + 轮次未超）路由 repair 通道；repair 完成后 re-merge-back 再失败仍走熔断累计（`:1554`）。
- repair 通道本体（载体现状三态、方向反转、轮次上限 `MAX_REPAIR_ROUNDS_PER_FAILURE = 2`、主树干净态保证）已由 add-merge-back-repair-lane 落地，本 SPEC 不改其语义。

事故账本：2026-09-04 task-track merge-back 冲突（fp=3cf770823ad5）→ 二轮 re-dispatch 约 32 分钟、全程 16.1M input tokens / $4.60。

## Goals / Non-Goals

- **Goals**：语义冲突在主树零污染点被拦截；repair 直通不经 fp 记账与状态降级；零冲突与产物冲突路径行为逐字节不变。
- **Non-Goals**：不改 repair 通道内部语义；不解决 push 阶段远端前移冲突（既有自愈覆盖）；不做跨 spec 合并排序。

## Decisions

### D1 预演实现：`git merge-tree --write-tree <main> <branch>`

只读、不触索引与工作区；输出 tree oid + 冲突段（`CONFLICT` 行，含路径与冲突类型）。解析冲突路径清单后复用既有产物前缀分类（`has_semantic_conflict` 判定同源，与 abort 后分类口径一致）。预演在 guard 锁内、stash 之前执行——用户未提交改动（autostash 候选）不参与预演，冲突面以已提交内容为准；真合并时 autostash pop 冲突仍按现行 guard 语义处理。

### D2 直通 repair 的状态语义

预演语义冲突 → 直接构造 `MergeConflictInfo(has_semantic_conflict=True, rehearsed=True)` 返回，git 层不执行 stash/merge/abort。调度层在两个失败分支（implementer/fast-track）检测 `rehearsed` 标记：命中则跳过 fp 记账与 ready 降级，直接 `_dispatch_repair_lane`。理由：
- 主树未被扰动，「merge 失败」在熔断语义上并未发生——fp 熔断的职责（阻断「根因不消除→整轮重跑→再败」循环）由 repair 轮次上限承接；
- spec 保持 in-flight 避免 ready 降级造成的重派排队与并发窗口。

re-merge-back 失败链（repair 后重推）保持现行 fp 熔断不动——那是真合并失败，语义成立。

### D3 单点收口

预演闸在 `merge_back_from_branch` 内实现（implementer/fast-track/repair remerge 三条调用路径自然全覆盖），调度层只加 `rehearsed` 分支。不新增配置键；git 探测结果进程内缓存（一次性 WARNING）。

### D4 git 版本探测

`git merge-tree --write-tree` 需 git ≥ 2.38。进程首用一次性探测（执行 `git merge-tree --write-tree` 空参试探或版本号解析），失败 → `_rehearsal_supported = False`，预演闸永久跳过，行为回退现行。探测失败记 WARNING 一次，不刷屏。

## Risks / Trade-offs

- **merge-tree 与真合并结果差异**：两者同用 merge-ort 引擎，冲突判定一致性高；残余差异（如 rename 检测边界）的兜底是——预演放行后真合并仍可能失败，届时走现行 abort + fp + repair 路径，不丢安全性。
- **预演冲突但真合并本可成功**：merge-ort 的冲突集是确定性的，该场景仅存在于探测误判，风险可忽略。
- **直通 repair 绕过熔断记账**：由 repair 轮次上限（2）+ remerge 失败链熔断兜底；若 repair 无法消化的冲突反复出现，最终落入 fallback 重派 → remerge 失败 → 熔断，闭环仍成立。
- **预演增加每轮合并开销**：merge-tree 为 O(仓库) 只读操作，dashboard 尺寸仓库毫秒级，可忽略。

## Migration Plan

1. git 探测 + 预演闸落 worktree_manager（零冲突/产物冲突路径行为等价，回归保护）。
2. `rehearsed` 标记 + 调度层直通分支（语义冲突行为变化点）。
3. 回归：merge guard / repair lane / 熔断套件全绿。

## Open Questions

- 无。
