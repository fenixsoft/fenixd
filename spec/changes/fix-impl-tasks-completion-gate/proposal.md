# Proposal: fix-impl-tasks-completion-gate

## Why

2026-09-13，SPEC `add-spec-review-gate` 的第 1 轮实现 run（`impl-add-spec-review-gate-1789292970-a1`，207 轮 / 3h08m）在 `tasks.md` 尚余 **17 项未勾选** 时主动收工，却在 `.fenix-run-result.json` 写下 `{"status": "success"}`——收工总结里还自行列出了「剩余任务（未勾选）」。daemon 采信该 success，`implementing → implemented → testing → verified` 全链放行；验证 23/23 全绿（场景不覆盖文档 / Dashboard / 补充测试这些任务面），直到 `verified → done` 的任务完成度门禁才拦下。

而拦下之后**没有出路**：`VALID_TRANSITIONS[VERIFIED] = [DONE]`、`GATE_TRANSITIONS[VERIFIED] = [TESTING]`，不存在 `VERIFIED → IMPLEMENTING`。SPEC 死在 verified 死角，最终只能**人工直接改写 `.fenix/STATE.md`** 复位——Dashboard 的 13 条 `spec-*` 路由与 CLI 都没有任何回炉入口。

三个结构性缺口：

1. **实现者的结果文件根本没有产物硬门**。`core/agent_runner/runner.py` 的 `_check_agent_result_artifact()` 开头即 `if agent_type not in ("planner-judge", "planner-plan"): return None`——planner 侧已有 `add-planready-artifact-gate` 立的存在性 / 非空 / 合法 JSON / status 白名单硬门，**implementer 与 fast-track 连"结果文件在不在、status 合不合法、任务书做没做完"都不校验**。而 `agents/fast-track.md` 与 `agents/implementer.md` 同样要求读并勾 `tasks.md`，fast-track 一样能带着缺口走到 verified。
2. **唯一的探测器在最末端**。`_task_completion_blocker` 全局只有一个调用点（`core/pm_engine/engine.py:547`，`_on_spec_verified` 内）——实现、验证、合并全部走完之后才发现任务书没做完。
3. **诚实上报没有出口**。Agent 若做不完，契约里只有 `success` 与 `error` 两个取值，且 `success` 的前置条件（"全部任务完成后"）不可自检；做不完又想收工时，唯一出路就是谎报 success。

同时本次勘察发现一条**从未生效的强制契约**：实现者提示词里的 `task-progress-contract` 要求每条 `tasks.md` 任务对应一次 `TaskCreate` 并在完成瞬间 `TaskUpdate`，但扫描 `.fenix/runs/` 全部 **141** 个 run，**含真实 `TaskCreate`/`TaskUpdate` 调用的为 0 个**（唯一 `init.tools` 含 `TaskCreate` 的是一个非 runner 派发的 review run）。这意味着 `parse_run_task_done` 的 `done_ids` 在本部署恒为空，``_task_completion_blocker`` 里"做了但忘勾"的豁免通道是死代码，而提示词强制的契约在每一个 run 上都被静默违反。

## What Changes

**P0 — 实现者/快速通道产物硬门（源头拦截，主体）**

`_check_agent_result_artifact()` 新增 `implementer` 与 `fast-track` 分支，`exit 0` 时校验 worktree 内 `.fenix-run-result.json`：

- 存在、非空、合法 JSON、顶层为对象、`status ∈ {success, error, partial}`；
- `status == "success"` 时 → `tasks.md` MUST 无未勾数字任务（`^- \[(x| )\] (\d+\.\d+)` 口径，与 `_task_completion_blocker` 同源，禁止双实现漂移）；
- `status == "success"` 时 → MUST 附 `completed_tasks: [...]`，且与 `tasks.md` 勾选项**集合相等**；
- **能力探测（条件化）**：读 run 的 `system/init.tools`，含 `TaskCreate` 时**额外**强制 `done_ids ⊇ checked_ids`（复用 `parse_run_task_done`）；不含时跳过并写审计事件 `impl-task-crosscheck-skipped`。**不得**把交叉核对写成无条件硬要求——在 Task 家族不可用的路由上它不可满足，会形成"拒绝 → resume → 再拒绝"的烧预算死循环。

失败处理：不判失败、不废弃整轮，复用既有 `AgentArtifactGateError` 通道（与 `add-impl-terminal-nocommit-gate` 同构）= 原地退避 + 同 worktree `--resume` 续做，并把剩余任务清单注入续做 prompt。fast-track 在其既有 `_hard_check_fast_track` 之上叠加同款判据，不另起一套。

**P2 — 诚实上报出口 + 收工契约可执行化**

- `.fenix-run-result.json` 允许 `status: "partial"` + `unfinished: ["4.5", "5.1", ...]`，明确 MUST NOT 用 `success` 掩盖未完成项；`partial` 走 dispatch 既有的非 success 失败/重派通道（`core/pm_engine/dispatch.py:736` 已有一致处理），确认不被静默放行。
- `agents/implementer.md` 与 `agents/fast-track.md` 的收工契约结构化：收工 MUST 逐项核对 `tasks.md`，输出 `completed_tasks` 清单，未完成项 MUST 进 `unfinished`，禁止「先勾后做」。
- **修掉那条不可执行契约**：`task-progress-contract` 段要求每条任务一次 `TaskCreate`/`TaskUpdate`，而 runner 派发的 run 从不具备该工具链（141/141）。本 SPEC MUST 在两者中择一收口——给实现者路由开 Task 工具链（环境侧），或把契约改为以 `.fenix-run-result.json` 的 `completed_tasks` / `unfinished` 为进度载体。不允许继续保留一条必然被违反的强制契约。

**P1′ — 人工一键回炉入口（只做人工路径）**

不做自动 `VERIFIED → IMPLEMENTING` 回退（有 P0 后到达率极低，自动回炉烧钱且过度设计）。只补产品化的人工入口，消除"改 STATE.md 手工作业"：

- Dashboard 新增 `spec-*` 风格路由（对齐 `spec-error-clear` / `spec-freeze-config` / `spec-budget` 的错误语义），把因 `task-gap:` 前缀拦截而停在 `verified` 的 SPEC 复位为 `ready` 并清 error，供 daemon 重派实现者承接剩余任务；
- CLI 同步提供等价子命令（现状 `bin/fenix_cli.py` 只有 `promote` / `review`）；
- 开放条件收紧：仅 `status == verified` 且 `error` 以 `TASK_GAP_ERROR_PREFIX` 开头才允许；其余形态返回明确拒绝原因。

**明确不做**：验证场景断言与任务面的对齐（成本高，待本 SPEC 落地后按残留量另议）；provider 长尾治理（归 `fix-run-hang-amplification`）。

## Capabilities

### New Capabilities

- `impl-tasks-completion-gate`：实现者 / fast-track run 的结果产物硬门（存在性、JSON 合法性、status 白名单、`success` 的任务书完成度判据、能力探测下的 TaskUpdate 交叉核对、失败走 `AgentArtifactGateError` 原地续做、剩余任务清单注入）。
- `spec-task-reflow-action`：`task-gap` 拦截滞留 verified 的 SPEC 的人工回炉动作（后端路由 + CLI 子命令 + 开放条件与拒绝语义）。

### Modified Capabilities

- `implementer-task-protocol`（归档于 `2026-09-09-fix-implementer-task-progress`）：TaskCreate/TaskUpdate 强制契约改为本部署可执行的进度载体（`completed_tasks` / `unfinished` 清单），并新增 `status: partial` 的诚实上报语义。
- `spec-status-actions-modal`（`spec/changes/add-spec-status-modal-budget`）：「修改状态」弹窗新增**回炉区块**——状态为 `verified` 且 error 带 `task-gap:` 前缀时渲染，说明缺口任务与回炉后果，确认后调用回炉 API。

## Impact

**代码**

- `core/agent_runner/runner.py`：`_check_agent_result_artifact()` 新增 implementer/fast-track 分支与其调用点（约 2688 行）、能力探测、`AgentArtifactGateError` 续做提示注入。
- `core/agent_runner/prompt_builder.py`：剩余任务清单注入段、`task-progress-contract` 段改写、`partial`/`unfinished` 契约。
- `agents/implementer.md`、`agents/fast-track.md`：收工契约与结果文件 schema。
- `core/pm_engine/dispatch.py`：`partial` 状态在实现者结果消费处的语义对齐（是否重派 / 是否计入失败预算）。
- `core/pm_engine/verification.py`：fast-track 硬校验叠加同款完成度判据。
- `core/dashboard/data.py` + `core/dashboard/server.py`：回炉 API 与受管动作。
- `core/dashboard/static/src/`：状态弹窗回炉区块、API client、`statusMeta` 相关展示。
- `bin/fenix_cli.py`：回炉子命令。

**依赖与约束**

- 复用既有 `TASK_GAP_ERROR_PREFIX`（`core/pm_engine/__init__.py:27`）、`parse_run_task_done`（`core/dashboard/data.py:1245`）、`AgentArtifactGateError`（`core/agent_runner/runner.py:277`）、`planner_result_status_whitelist`（`core/agent_runner/prompt_builder.py:65`），不新造平行机制。
- `parse_run_task_done` 现定义在 `core/dashboard/data.py`，而硬门位于 `core/agent_runner/runner.py`；跨层 import 的落点须在 design 中定夺（下沉到中性模块并保留原处再导出）。
- 交付物守卫 `_deliverable_gate_missing`（`core/pm_engine/verification.py:2621`）只做分支 HEAD blob 存在性检查，`kind: modify` 类"声明了但一字未改"必然放行——**本 SPEC 不修它**，且不得误以为它能兜底。
- 已知残余风险（写入 design 风险段，不假装解决）：`completed_tasks` 与 `tasks.md` 的集合相等校验能抓"粗心漏勾 / 漏报"，**抓不住蓄意"先勾后做"**；在过程性工具不可用的路由上这是天花板，真正防线是验证场景与任务面的对齐（本 SPEC 明确不做）。
