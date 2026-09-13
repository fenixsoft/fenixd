## Deliverables

```yaml
# ── 解析与进度载体下沉 ────────────────────────────────────────
- path: core/run_task_track.py
  kind: new
- path: core/dashboard/data.py
  kind: modify

# ── 产物硬门 ────────────────────────────────────────────────
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify

# ── pm_engine 消费点与回炉动作 ────────────────────────────────
- path: core/pm_engine/engine.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/pm_engine/task_reflow.py
  kind: new

# ── 入口（API / CLI / 前端）────────────────────────────────────
- path: core/dashboard/server.py
  kind: modify
- path: bin/fenix_cli.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx
  kind: modify

# ── 提示词 ──────────────────────────────────────────────────
- path: agents/implementer.md
  kind: modify
- path: agents/fast-track.md
  kind: modify

# ── 文档 ────────────────────────────────────────────────────
- path: docs/help/03-lifecycle.md
  kind: modify
- path: docs/help/06-governance.md
  kind: modify

# ── 测试 ────────────────────────────────────────────────────
- path: tests/test_impl_tasks_completion_gate.py
  kind: new
- path: tests/test_spec_task_reflow.py
  kind: new
- path: tests/test_pm_verification.py
  kind: modify
- path: tests/test_dashboard_api.py
  kind: modify
- path: tests/test_agent_prompt_files.py
  kind: modify
```

## 1. 解析与进度载体下沉

- [ ] 1.1 新建 `core/run_task_track.py`：提供 tasks.md 数字任务解析纯函数（逐行匹配 `^- \[(x| )\] (\d+\.\d+)`，返回全部 id 与已勾选 id 集合；文件缺失/不含数字任务返回空集），供 `_task_completion_blocker`、新硬门、`parse_run_task_done` 调用方共用
- [ ] 1.2 新建 `core/run_task_track.py`：把 `core/dashboard/data.py` 的 `parse_run_task_done` 及其 memo 缓存（`_RUN_TASK_CACHE`）逐字下沉到本模块，语义与返回结构（`done_ids`/`created_count`/`flat_done`/`in_progress_ids`）保持不变
- [ ] 1.3 `core/dashboard/data.py`：改为从 `core.run_task_track` 再导出 `parse_run_task_done`，并保留既有兼容别名 `_parse_run_task_done`、`_find_impl_run_file`；确认既有全部调用点（`engine.py:961/1166`、`data.py:1406/1470`）零改动仍可用
- [ ] 1.4 `core/pm_engine/engine.py`：`_task_completion_blocker` 的内联 tasks.md 解析（约 1149-1160 行）改用 1.1 的共用函数，判定口径与行为保持逐字不变（含"文件缺失/无数字任务 → 放行"分支）

## 2. 实现者与快速通道结果产物硬门

- [ ] 2.1 `core/agent_runner/runner.py`：`_check_agent_result_artifact` 增加 `wt_path` 形参（调用点约 2688 行传入），并在 `agent_type in {"implementer", "fast-track"}` 分支读取 `wt_path / ".fenix-run-result.json"`（不读主树拷回副本）
- [ ] 2.2 `core/agent_runner/runner.py`：implementer/fast-track 分支的基础校验——文件存在、非空、合法 JSON、顶层为对象、顶层 `status ∈ {"success", "error", "partial"}`；任一不满足返回失败归因文案
- [ ] 2.3 `core/agent_runner/runner.py`：`status == "success"` 的完成度判据——以 worktree 内 `spec/changes/<spec>/tasks.md` 为对象，未勾数字任务必须为零（复用 1.1 解析），且结果文件 `completed_tasks` 集合必须与已勾选 id 集合完全相等（缺项/多项/非数字 id 均判失败）
- [ ] 2.4 `core/agent_runner/runner.py`：`status == "partial"` 的申报一致性判据——`completed_tasks` 等于已勾选集合、`unfinished` 等于未勾选集合、两集合互斥且并集等于全部数字任务 id
- [ ] 2.5 `core/agent_runner/runner.py`：能力探测——读本轮 run 产物中 `type=="system" && subtype=="init"` 的 `tools` 数组；含 `"TaskCreate"` 时额外强制 `parse_run_task_done(run_file)["done_ids"]` 覆盖全部已勾选 id；不含或 `init` 不可得时跳过并向 run 产物追加 `type=="impl-task-crosscheck-skipped"` 审计事件（含 spec/run_id/reason）
- [ ] 2.6 `core/agent_runner/runner.py`：`status == "error"` 时不施加任何完成度类判据
- [ ] 2.7 `core/agent_runner/runner.py`：硬门归因文案覆盖全部失败类别（缺失/为空/非法 JSON/顶层非对象/status 白名单外/未完成任务/完成清单不一致/申报不一致/TaskUpdate 不一致），含真实 status 取值与缺口任务 id 清单（超 20 项截断并标注总数），不得以 `None` 替代真实值

## 3. 硬门失败的原地续做

- [ ] 3.1 `core/agent_runner/runner.py`：确认硬门失败仍走既有 `AgentArtifactGateError` 通道（保 worktree、原地退避、同 worktree 同 session `--resume` 续做），不清理 worktree、不判整轮作废、不消耗实现尝试预算
- [ ] 3.2 `core/agent_runner/prompt_builder.py`：续做轮 prompt 注入硬门归因段（失败类别 + 缺口任务 id 清单），与 `add-impl-terminal-nocommit-gate` 的续做注入同构，使 agent 无需重新推导剩余范围

## 4. partial 状态的消费点一致性

- [ ] 4.1 `core/pm_engine/dispatch.py`：实现者结果消费主路径（约 729-741 行）显式处理 `partial`——`is_success` 为假、MUST NOT 进入 `implemented`，且失败归因 MUST 非空（由 `unfinished` 清单与缺口 id 构成，不得沿用为 `None` 的 `result.error`）
- [ ] 4.2 `core/pm_engine/dispatch.py`：逐点核对并处理 `partial`——约 1313 行、约 2225 行、约 3130 行（fast-track 路径），确认均不落入"未知状态按成功/放行"的默认分支
- [ ] 4.3 `core/pm_engine/verification.py`：约 3287 行的 fast-track 结果消费点显式处理 `partial`
- [ ] 4.4 `core/pm_engine/engine.py`:769 `_read_implementer_result` 读取器及其调用方核对 `partial` 语义；确认 `_task_completion_blocker` 在 partial 轮之后不会放行到 done
- [ ] 4.5 `core/pm_engine/dispatch.py`：确认 `partial` 走消耗实现尝试预算的失败/重派通道（不得走 `AgentArtifactGateError` 的不消耗预算续做通道），连续 partial 由既有预算上限收口转 blocked

## 5. fast-track 通道叠加

- [ ] 5.1 `core/pm_engine/dispatch.py`：在 `_hard_check_fast_track` 既有校验之上叠加与 implementer 同源的完成度判据（复用同一解析函数与同一归因构造），不另起一套判定
- [ ] 5.2 `core/pm_engine/verification.py`：确认 fast-track 结果文件顶层 `status == "success"`（verdict 承载在 `verification` 段）的既有契约与新硬门白名单兼容，不产生误拦

## 6. 提示词契约可执行化

- [ ] 6.1 `agents/implementer.md`：收工契约改写为可执行形态——`status: "success"` 必须附 `completed_tasks` 且与 tasks.md 勾选一一对应；做不完时 MUST 以 `status: "partial"` 收工并如实登记 `unfinished`，MUST NOT 用 success 掩盖未完成项；禁止「先勾后做」
- [ ] 6.2 `agents/fast-track.md`：同 6.1，且契约段与 implementer 分支由同一实现点产出（内容逐字一致）
- [ ] 6.3 `core/agent_runner/prompt_builder.py`：契约段改为条件生成——`init.tools` 含 `TaskCreate` 时保留 `Task <id>: ` 前缀与 `TaskUpdate status=completed` 立即汇报要求；不含时 MUST NOT 要求 TaskCreate/TaskUpdate，改以 `completed_tasks` 清单为进度载体

## 7. task-gap 滞留 SPEC 的人工回炉入口

- [ ] 7.1 新建 `core/pm_engine/task_reflow.py`：回炉动作的判定与执行单一实现点——开放条件（SPEC 存在 ∧ status == verified ∧ error 以 `TASK_GAP_ERROR_PREFIX` 开头 ∧ 未冻结）与四类拒绝原因；执行经 `StateMachine.update_spec` 原子写 `{"status": "ready", "error": None}`；MUST NOT 触碰 `_impl_run_budget_used`/`frozen`/`frozen_until`/`start_after`；成功后向 `.fenix/PROJECT_LOG.md` 追加可追溯记录（SPEC 名、原状态、缺口任务清单、动作来源）
- [ ] 7.2 `core/dashboard/server.py`：新增 `POST /api/spec-task-reflow?project=<name>&spec=<name>` 路由，错误语义对齐 `spec-error-clear`/`spec-freeze-config`/`spec-budget` 家族（404 / 非 200 明确拒绝原因 / `ok:true`）
- [ ] 7.3 `bin/fenix_cli.py`：新增 `reflow <spec> [--project <path>]` 子命令，判定与执行调用 7.1 的同一实现点；成功输出含新状态的提示并退出码 0，被拒绝时 stderr 输出原因并退出码非 0；`--project` 缺 `.fenix/STATE.md` 时报错退出
- [ ] 7.4 `core/dashboard/static/src/services/dashboard.ts`：新增回炉 API client（对齐既有 `freezeSpec`/`unfreezeSpec`/`promoteSpec` 模式）
- [ ] 7.5 `core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx`：新增回炉区块——status 为 `verified` 且 error 以 `task-gap:` 开头时渲染，含缺口任务清单与「将重新派发实现」说明；点击弹确认后调用回炉 API，成功提示已复位 ready 并刷新列表，被拒绝时以 message.error 展示后端原因；非 task-gap 形态不渲染该区块

## 8. 文档同步

- [ ] 8.1 `docs/help/06-governance.md`：新增「实现者任务书完成度硬门」章节——硬门判据（存在性/status 白名单/success 完成度/partial 申报一致性/能力探测下的 TaskUpdate 核对）、失败走原地续做而非废轮、`partial` 诚实上报语义与预算计入方式、残余风险（无法检出蓄意先勾后做）如实说明
- [ ] 8.2 `docs/help/03-lifecycle.md`：补充「verified 滞留与回炉路径」——`task-gap` 拦截的成因与 `error` 形态、Dashboard 修改状态弹窗与 CLI `reflow` 的人工回炉入口、回炉后由 daemon 重派实现者承接剩余任务

## 9. 测试与回归

- [ ] 9.1 新建 `tests/test_impl_tasks_completion_gate.py`：硬门各失败形态（文件缺失/为空/非法 JSON/顶层非对象/status 白名单外/未完成任务/completed_tasks 缺项或多项/partial 申报不一致）；成功形态放行；error 不施加判据；无数字任务 SPEC 放行
- [ ] 9.2 `tests/test_impl_tasks_completion_gate.py`：能力探测两分支——`init.tools` 含 `TaskCreate` 且 done_ids 不覆盖已勾选项 → 拦截；不含 → 放行且写入 `impl-task-crosscheck-skipped` 审计事件；`init` 不可得 → 按工具不可用处理
- [ ] 9.3 新建 `tests/test_spec_task_reflow.py`：四类拒绝（非 verified / error 非 task-gap 前缀 / 冻结 / 幂等重复调用）+ 合规复位成功 + 不触碰预算与冻结计数器 + PROJECT_LOG 留痕
- [ ] 9.4 `tests/test_dashboard_api.py`：回炉路由成功、project/spec 404、四类拒绝的状态码与错误语义
- [ ] 9.5 `tests/test_pm_verification.py`：`partial` 不放行到 implemented、失败归因非空且含缺口 id、计入实现尝试预算、partial 轮之后 `_task_completion_blocker` 不放行到 done
- [ ] 9.6 `tests/test_agent_prompt_files.py`：两分支（implementer / fast-track）契约段同源断言；工具不可用分支的 prompt 不含 TaskCreate 强制语句
- [ ] 9.7 全量回归：经 `bin/run_full_suite.py --timeout 3600 --baseline HEAD` 有界入口执行，新增用例全绿且既有 pm_engine / dispatch / runner / dashboard 回归无新增失败（以主树基线对照区分存量 flake 与本轮引入）
