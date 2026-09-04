# Proposal: 修复 implementer 未在 worktree 隔离工作（Popen 未传 cwd）

## Why

Fenix 框架的核心设计原则之一是「Implementer Agent 在独立 git worktree 中隔离工作」（`fenixd.py` 注释明确：*Implementer Agent (automatic, Ralph-mode, worktree-isolated)*；`worktree_manager.py` 为每次运行创建 `impl-<spec>-<ts>` worktree）。然而经排查发现该隔离机制**实际从未生效**：

1. **根因（代码级确认）**：`core/agent_runner.py::_run_claude` 接收 `cwd=worktree 路径`，但 `subprocess.Popen(cmd, ..., env=env)` **从未传 `cwd=` 参数** —— worktree 路径仅通过 `--add-dir <worktree>` 作为「附加目录」加入会话。因此 claude 子进程实际工作目录是 daemon 的 cwd（项目主树），prompt 中的相对路径（`spec/changes/<spec>/...`）全部解析到主树。
   - 已核验：本机旧 run `impl-add-dashboard-spec-table-1787577911` 与 `impl-add-flowtoken-run-view-1787617630` 的 init 事件 `cwd` 均为主树 `/root/fenixd`；worktree `impl-add-flowtoken-run-view-1787617630` 的 `git status` 干净（实现者从未在其中编辑）。
   - `fenixd.py` 中不存在任何「把 worktree 分支合并回主树」的逻辑 —— 主树中的实现提交全部来自 implementer 直接在主树工作这一「意外」行为。

2. **次级影响（Dashboard 读取路径错位）**：`core/dashboard/data.py::parse_tasks` 对 `implementing` 状态的 SPEC 经 `find_implementer_worktree` 读取 **worktree** 的 `tasks.md`，而实现者实际编辑的是主树的 tasks.md —— 即使实现者按规范勾选了 tasks.md，Dashboard 也读到 stale 的 worktree 副本。

3. **修复不完整**：若只修复 cwd 传入（让 implementer 真正在 worktree 工作）而不补「合并回主树」步骤，实现将只存在于 worktree 分支上，verifier（在主树运行的验证管线）会验证旧代码，流水线断裂。

## What Changes

- **让 implementer 真正在 worktree 中工作**：`agent_runner._run_claude` 的 `subprocess.Popen` 传入 `cwd=worktree 路径`，使 claude 子进程、所有相对路径编辑与 git commit 都落在 worktree 内。
- **新增 worktree 分支合并回主树**：implementer 成功运行后，将 worktree 分支（`fenix/<spec>-<ts>`）以 `git merge --no-ff` 合并回主树（或等价地 cherry-pick），确保主树包含实现、供 verifier 验证与后续 push。
- **对齐读取路径**：`data.parse_tasks` / `worktree_manager.find_implementer_worktree` 读取位置与 tasks.md 实际所在一致；核对 `.fenix-run-result.json` 读回（`pm_engine._read_implementer_result` 已 worktree 优先）与 verifier 的 `verify-progress` / `spec_dir` 路径假设。
- **回归保障**：全量单元测试通过；一次完整 implement→verify 周期正常，Dashboard 实时任务进度（叠加 run 记录）在修复后与 tasks.md 勾选状态双源一致。

## Capabilities

### New Capabilities

- `worktree-isolation`: implementer 在独立 worktree 中隔离实现（cwd 正确传入），成功后 worktree 分支合并回主树；`data.parse_tasks` / `find_implementer_worktree` 读取路径与实际工作目录一致；verifier 验证的是合并后的主树代码。

### Modified Capabilities

<!-- 无既有能力被修改；本次为对现有「worktree 隔离」设计意图的落实修复。 -->

## Impact

- **核心代码**：
  - `core/agent_runner.py`：`_run_claude` 的 `Popen` 传入 `cwd`；实现成功后新增 merge-back 步骤（在 `_execute_agent` 或 pm_engine 侧）。
  - `core/worktree_manager.py`：`cleanup` 语义与 merge-back 配合（保留分支供合并、成功后移除 worktree）。
  - `core/dashboard/data.py`：`parse_tasks` / `find_implementer_worktree` 的读取路径与 tasks.md 实际所在一致（避免读到 stale worktree 副本）。
  - `core/pm_engine.py`：`_run_agent_worker` 在 implementer 成功后触发 merge-back 后再推进状态与排队 verifier。
- **测试**：`tests/test_core.py` / `tests/test_dashboard.py` 增加 merge-back、cwd 传入、读取路径对齐的单元测试。
- **行为影响**：实现者的编辑不再直接落主树（主树在运行期间保持干净），成功后经 merge 呈现；`git log` 历史出现 merge commit。
- **风险**：merge-back 若实现不当（如漏 merge、冲突未解）会导致 verifier 验证旧代码或实现丢失 —— 必须配合回归测试与失败回退（merge 失败则标记 error，不推进状态）。

## 相关背景（供实现者阅读）

- 根因排查记录：`add-flowtoken-run-view` 实现运行中，worktree `impl-add-flowtoken-run-view-1787617630` 的 `git status` 干净、主树文件被直接编辑（`core/dashboard/static/app.js` 等未提交改动在 main）。
- 实时任务进度叠加（`data.parse_tasks` 的 run 记录 overlay）与本 SPEC 正交：overlay 读主树 `.fenix/runs/` 产物，不关心 implementer 在哪个目录工作；修复 worktree 隔离后，实现者勾选的 worktree tasks.md 与 overlay 并集仍正确。
