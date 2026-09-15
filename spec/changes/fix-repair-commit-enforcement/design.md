## Context

repair 车道（`add-merge-back-repair-lane` + `add-merge-tree-rehearsal`）的既定闭环是：merge-back 预演检出语义冲突 → 直通 repair → repair agent 在实现分支一侧把 main 合入、解决冲突、commit → 框架 re-merge-back。

现状缺口在「repair agent 声明 success」与「框架据以 re-merge-back」之间**没有任何 git 事实校验**。`_run_repair_worker`（`core/pm_engine/dispatch.py:2774-2790`）只读 worktree 的 `.fenix-run-result.json`，信任其 `status` 字段与 `r.success`。当 repair agent 把冲突解决并 `git add` 到 index、却因去跑全量套件而**从未 `git commit`**、在超时窗口内以 success 结束时，框架判定成功 → `merge_back_from_branch` 对该未前进的分支重新预演 → 检出**同一冲突** → 熔断 → `_fallback_after_repair` 全新重派。

实证（`evo-infra-failure-budget-exempt`，2026-09-15）：
- 两次 repair run 的结论文本均为「冲突已解决并暂存…等测试结果确认后即完成合并提交」，分支 tip 停在 `c1660085`，`git merge-base --is-ancestor 73508d00 <branch>` = NO；
- 预演每轮对同一 `core/pm_engine/budget.py` import 行冲突（主树 `73508d00` 删 FROZEN_FIELD vs 分支新增 infra 字段）复现；
- 第 3 次 → fallback；重派分支带 `535f6918 Merge branch 'main'` 才真正解掉；
- 代价：尝试预算 2/6、累计 $20.78。冲突规模是「单行 import」，本可原地 1 分钟解决。

同因还有两处放大：repair prompt 要求「解决冲突 → 运行项目测试 → commit」，把测试放在提交之前，诱导 agent 用全量套件当提交前置（该 spec 全量套件在本机约 40min+ 且有存量挂起，repair 窗口内几乎必然跑不完）；且 repair 开场不清洗上一轮残留的未完成 merge 现场，第二轮 repair 被迫先把上一轮遗留的半成品当作起点梳理。

## Goals / Non-Goals

**Goals:**
- repair 的「成功」以**分支 git 事实**为准，任何未提交/未解决/未完成 merge 一律判未完成，不再误触发 re-merge-back 与熔断重派。
- 回退时把**具体**未完成事实注入下一轮重派上下文，替代笼统的「merge-back failed」。
- prompt 侧把「提交」确立为测试之前的强制终点，测试收敛为触及文件的定向回归 + 有界超时。
- repair 开场清理残留未完成 merge 现场。

**Non-Goals:**
- 不改动 `merge_back_from_branch` / 预演闸的既有语义与判定。
- 不引入新的配置键（判定为硬事实，无需阈值）。
- 不试图让 repair agent「自动 rebase/merge main 到分支以外的新机制」——那是本变更为之服务的目标（修复能原地生效），但本次只保证**repair 的成果被真正落地**。
- 不改变 repair 的预算/轮次约束与熔断阈值。

## Decisions

**D1：git 事实复核放在 dispatch worker 侧，不进 repair agent 信任半径。**
复核点位于 `_run_repair_worker` 判定 `repair_ok` 之后、`_reconcile_impl_budget` 与 re-merge-back 之前。理由：agent 报的 success 是「声明」，worker 需以 git 事实独立验证；把校验放在框架侧而非 prompt 侧，agent 无论如何措辞都无法绕过。

**D2：三项事实判定全部走只读 git 查询，不新增 worktree 写操作。**
- 分支 tip 前进：以 repair 派发前记录的分支 tip（派发点或 repair run 启动前）与 repair 后 `git rev-parse <branch>` 比较。
- 冲突残留：`git -C <wt> ls-files -u` 为空。
- 未完成 merge：worktree 内 `git rev-parse -q --verify MERGE_HEAD` 失败（无 MERGE_HEAD）。

> 分支 tip 基准：优先取 repair run **派发前**分支 tip。若派发点未记录，退化为「分支 tip ≠ 派发时框架所见」不可判定——因此 MUST 在 `_dispatch_repair_lane` 或 `_run_repair_worker` 入口记录基准 tip（新增 `_repair_base_tip` STATE 侧车字段，`_` 前缀自动透传，与 `_repair_merge_fp` 同族）。基线在 repair 成功后由 re-merge 成功路径清零。

**D3：判定失败复用既有 `_fallback_after_repair` 路径，仅增强错误文本。**
不新造回退分支——`repair_ok = False` 分支已存在且已注入 merge 失败上下文；本次把 `repair_error` 从「结果文件 status=error」类升级为携带具体事实的文本（如「repair git 事实复核未通过：分支 tip 未前进（base=c1660085, now=c1660085）」）。`_fallback_after_repair` 的 `merge_error` 参数由调用侧一并传入该事实。

**D4：prompt 契约改为「提交先于测试且为强制终点」。**
`_build_repair_prompt` 的「修复方向」步骤重排为：① 开场清理残留 merge（若 MERGE_HEAD 存在先 abort）→ ② `git merge main` → ③ 解决冲突 → ④ **commit**（强制终点）→ ⑤ 定向回归测试（触及文件子集 + 有界超时，例 `timeout 600 python3 -m pytest <touched_test_files> -q`）。显式写入「提交不可因测试未完而推迟；测试跑不完时提交已解决合并并标注边界」。

**D5：判定逻辑抽为可测试的纯函数/独立方法，便于单测。**
在 worktree_manager（或 dispatch 的辅助）新增只读查询方法，dispatch 侧组合判定；单测直接对「tip 未前进 / 有未合并条目 / 有 MERGE_HEAD / 全 ok」四态注入构造仓库验证。沿用 `tests/test_mergeback_repair_lane.py` 的临时仓库夹具风格。

## Risks / Trade-offs

- **误判「无新提交」**：若 repair 通过 `--amend` 或等价手段在不改 tip 的情况下完成解决 → 会被判未完成。缓解：repair 语义本就要求「合入 main」必然产生新提交（merge commit 或冲突提交），tip 不变与「真正合入 main」互斥；如遇边界，复核仅需 tip 前进这一必要条件即够，不追求充分。
- **换壳 worktree 下 MERGE_HEAD 判定**：三态解析的换壳分支是干净新 worktree，`MERGE_HEAD` 必不存在，判定自然通过；原地分支才可能残留。缓解：判定以 repair 后**实际 worktree 路径**为准（`wt_path`），不臆测。
- **基准 tip 缺失导致假阴性放行**：若 `_repair_base_tip` 未写入（老状态迁移），复核退化为「仅查冲突残留 + MERGE_HEAD」。缓解：这是保守侧（放行），与现状一致，不引入新风险；写入点覆盖派发与 worker 入口两处。
- **测试范围收窄可能漏回归**：定向回归不覆盖全量。缓解：这是 repair 场景的既定取舍——repair 只解决 merge 冲突、不改功能语义，定向到触及文件足够；全量回归仍由后续 verifier 环节承担。

## Migration Plan

- 无配置迁移、无数据迁移：新 STATE 侧车字段 `_repair_base_tip` 缺省缺失时判定降级为保守放行，存量 in-flight spec 零影响。
- 回滚：三项事实复核是纯增量校验，回滚即移除复核分支；不改变既有 happy path（真提交的 repair 逐字节不变）。

## Open Questions

- 基准 tip 的写入点取「`_dispatch_repair_lane` 派发前」还是「`_run_repair_worker` 入口」更稳？（倾向 `_dispatch_repair_lane`：与 `_repair_round`/`_repair_merge_fp` 同处一次 `update_spec` 落盘，语义一致。）—— 实现阶段定。
