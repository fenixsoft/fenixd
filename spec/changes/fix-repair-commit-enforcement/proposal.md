## Why

repair 车道的可数命门是「repair agent 声明成功但没真正提交合并」。框架在 `_run_repair_worker` 读 repair 结果文件只信 `status` 字段与 `r.success`，从不校验分支 git 事实。当 repair agent 把冲突解决后只在 index 暂存、却去跑全量套件、最终在跑测试的超时窗口里以「success」收尾（未 `git commit`）时，框架判定 repair 成功 → 立即对该分支重跑 `merge_back_from_branch` → 预演闸再次检出**同一冲突** → 熔断 → 回退「全新重派」。

结果是一次本可原地解决的 import 行冲突，被升级为一次完整的实现重做。实证（`evo-infra-failure-budget-exempt`，2026-09-15）：两轮 repair 均在「已解决、已暂存、正在跑测试」处报告 success 结束，分支 tip 从未前进（`git merge-base --is-ancestor 73508d00 <branch>` = NO），第 3 次预演复现同一 `core/pm_engine/budget.py` 冲突 → fallback；重派后 `535f6918 Merge branch 'main'` 才真正解掉，代价 2 次尝试预算 + ~$20.78。

## What Changes

- **repair worker 增加 git 事实硬门（A）**：`_run_repair_worker` 在消费 repair 结果、决定走 re-merge 之前，校验分支 git 事实——① 分支 tip 相对派发前是否前进（至少一个新提交）；② worktree 内是否残留未解决冲突（`git ls-files -u` 非空 / 冲突标记）；③ 是否仍处于未完成 merge（worktree 存在 `MERGE_HEAD`）。任一不满足即视为 repair 未完成，快速走 `_fallback_after_repair`，并把「未提交」「冲突残留」等具体事实注入 merge 失败上下文，**不再以「merge-back failed」笼统原因重派**。
- **repair prompt 提交契约强化（B）**：把「先 commit、再测试」写成强制顺序终点，禁止「跑全量套件后再决定是否提交」；测试从「运行项目测试」收敛为「本次合并触及文件的定向回归 + 有界超时」，明确「无法在窗口内跑完全量套件时应提交已解决合并并如实说明验证边界，**不得因测试未跑完而不提交**」。
- **repair 开场清理残留 merge（C）**：repair agent 开工第一步检测 worktree 是否残留上一轮未完成 merge（`MERGE_HEAD` 存在），若有则 `git merge --abort` 复位到干净 tip 再重新 `git merge main`，禁止把上一轮半成品现场当作本轮起点。

## Capabilities

### New Capabilities

- `repair-commit-enforcement`: repair 车道的「成功」以分支 git 事实为准——repair agent 声明 success 后，框架必须验证分支确实前进了提交且无冲突残留/未完成 merge，才算 repair 成功；prompt 侧确立「提交先于测试且为强制终点」的契约；开场清理残留 merge 现场。

### Modified Capabilities

（无——现有 `merge-back-repair-lane` / `merge-tree-rehearsal` 的 spec 级行为不变，本变更是新增校验层，对既有 Requirement 为增强而非改写。）

## Impact

- `core/pm_engine/dispatch.py`：`_run_repair_worker`（repair 成功后、re-merge-back 前的校验点）
- `core/agent_runner/prompt_builder.py`：`_build_repair_prompt`（提交契约与限测措辞）
- `core/worktree_manager.py`：可能新增只读的「分支 tip / 冲突残留 / MERGE_HEAD」查询辅助（若 dispatch 侧不直接跑 git 子进程）
- `tests/`：新增 repair git 事实硬门的单元测试（沿用 `tests/test_mergeback_repair_lane.py` / `test_repair_redispatch.py` 既有夹具风格）
- 不改动 `merge_back_from_branch` / 预演闸本身语义；不新增配置键（阈值走既有常量，必要时以 `_repair_*` STATE 字段记录判定事实）
