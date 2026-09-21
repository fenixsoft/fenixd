# add-freeze-stop-inflight-agents — Tasks

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/pm_engine/dispatch/fast_track.py
  kind: modify
- path: core/pm_engine/dispatch/repair_lane.py
  kind: modify
- path: core/pm_engine/verification/legacy.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/worktree_manager/stale_sweep.py
  kind: modify
- path: core/dashboard/data/runs.py
  kind: modify
- path: core/dashboard/data/spec_archive.py
  kind: modify
- path: core/dashboard/data/__init__.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/dashboard/routes/spec_routes.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: tests/test_freeze_stop_inflight_agents.py
  kind: new
- path: tests/test_delete_stop_inflight_agents.py
  kind: new
```

## 1. 冻结即停：runner 轮询环与独立终态

- [x] 1.1 `core/agent_runner/result_gate.py`：新增 `FrozenTerminatedError` 异常类（携带 reason，构造签名与 `RunCancelledError` 并列定义于同处，`result_gate.py:72` 之后）；`core/agent_runner/runner.py` 的既有 `from core.agent_runner.result_gate import (...)` re-export 块加入该类（`runner.py:30-45`），使 pm_engine 侧经 `core.agent_runner.runner` 判定与既有 `RunCancelledError` 同路径可达；同步 `tests/test_agent_runner_modules_contract.py` 的 `D6_NAMES` / re-export 同对象断言（该两个清单当前各列 `RunCancelledError`，`test_agent_runner_modules_contract.py:40/55`）
- [x] 1.2 `core/agent_runner/runner.py`：`_run_claude` 轮询环在既有 `_cancel_is_requested` 检查**之前**插入 frozen 检查——`self._spec_is_frozen(spec_name)` 命中则：① 对当前 worktree 执行 `_wip_checkpoint_on_forced_kill`（新增 anchor 常量 `freeze-hold`，失败 WARNING 不阻断）② `proc.terminate()` → `wait(timeout=AGENT_TERMINATE_GRACE_SECONDS)` → 超时 `proc.kill()` ③ 置 `returncode = -15`、构造 `FrozenTerminatedError(reason=...)`、`break`；同时清理该 base_run_id 残留的 cancel 旗标（`_cancel_clear`）
- [x] 1.3 `core/agent_runner/runner.py`：`_run_claude` 的 `finally` 段在既有 `cancel_error` 落盘之后并列处理 `frozen_error`——追加 `{"type": "frozen-terminated", "reason", "by", "timestamp"}` 终态行（保证为文件末行），并抛 `FrozenTerminatedError`
- [x] 1.4 `core/agent_runner/runner.py`：`_execute_agent` 原地重试子循环在 `except RunCancelledError` 旁新增 `except FrozenTerminatedError`——不重试、不计秒挂、不触发 provider 切换，置 `frozen_terminated_flag = True` 与 error 文案（含「冻结」语义）后 `break`
- [x] 1.5 `core/agent_runner/runner.py`：`_AttemptState`（`runner.py:329`）增加 `frozen_terminated_flag` 字段；`_exhausted_result`（`runner.py:3191`）增加 `frozen_terminated_flag` 参数与分支，返回 `AgentRunResult(frozen_terminated=True, ...)`；`core/agent_runner/result_gate.py` 的 `AgentRunResult`（`result_gate.py:105`）增加 `frozen_terminated: bool = False` 并按既有 `cancelled` 同款纳入 `to_dict` 序列化（`result_gate.py:115/156/169`）
- [x] 1.6 `core/agent_runner/runner.py`：`_finalize_failure_keep`（`runner.py:2957`）增加 `frozen_terminated_flag` 参数——冻结终止时 MUST `break`（不进入下一 attempt、不 `time.sleep(10)` 重试）；worktree 处置沿用既有 `repair`/`fast-track` 保留语义，**含 implementer 在内的其余类型 MUST 按 `shutdown_interrupted` 同款「保留现场」分支处理**（`kept_wt_path = st.wt_path` + `handed_off.add(...)`，可选再 `keep_for_reuse` 登记）——既有 `else` 分支的 `cleanup(success=False)` 会**删除 implementer 的 worktree 目录**（`runner.py:3029-3030`），会使本 SPEC 的「WIP 保全」与「解冻后在保留分支续做」双双落空
- [x] 1.7 `core/agent_runner/runner.py`：`_attempt_top_guards` 的 frozen 分支改为复用同一 `FrozenTerminatedError` 通道（保持既有「不派发 attempt」行为，补 `frozen_terminated=True` 结果字段），使边界守卫与在飞终止语义一致
- [x] 1.8 `core/agent_runner/liveness.py`：`RUN_TERMINAL_EVENT_TYPES` 加入 `"frozen-terminated"`（写侧权威），并在注释中标注与 `core/dashboard/data/runs.py::_RUN_TERMINAL_STATUS_MAP` 的同步义务
- [x] 1.9 `core/dashboard/data/runs.py`：`_RUN_TERMINAL_STATUS_MAP` 加入 `"frozen-terminated": "frozen-terminated"`，并更新该表上方的注释（说明新终态的行来源与读侧缺映射的后果）

## 2. STATE 独立保持标记

- [x] 2.1 `core/state_machine.py`：新增字段常量 `FROZEN_HOLD_FIELD = "_frozen_hold"`（置于字段名单区，与 `VERIFY_REDO_COUNT_FIELD` 等并列）；**落盘不需要改显式键表**（`serialize` 的「`_` 前缀全量透传」分支已覆盖，`state_machine.py:423-427`），但 MUST 纳入**读侧布尔显式转换**分支（`state_machine.py:330-338`，与 `_cancelled_hold` 同处——`"False"` 字符串 truthy，不转会把解冻后的 spec 永久误判为保持态）；注释固化「与 `_cancelled_hold` 并列、互不读写」契约
- [x] 2.2 `core/state_machine.py`：`freeze_spec` 增加保真锚点行为——冻结时若该 spec 当前 status 在 `INTERRUPTED_STATES`（implementing/testing/reviewing）则把 `branch` / `implementer_run` / `reviewer_run` 的现值一并写入同一次 `update_spec`（MUST NOT 因冻结清空这些锚点，否则解冻无从续做）。注意：现有 `freeze_spec` 只写 `{status, frozen, error}`、本身不清锚点，但**必须显式带值透传**——否则一旦将来有清理路径把 `branch` 置空，冻结终止后的 `mark_frozen_hold`（MUST NOT 清锚点）也会拿着空锚点、续做判定必然降级
- [x] 2.3 `core/state_machine.py`：新增 `mark_frozen_hold(spec_name, error)` 方法——单次原子写 `{FROZEN_HOLD_FIELD: True, "_cancelled_hold": False, "error": error}`，MUST NOT 改 `status`、MUST NOT 清 `branch`/`implementer_run`；注释固化调用方（dispatch 侧冻结终止分支）。**形态约束**：MUST 写 `_frozen_hold: True` 并**清** `_cancelled_hold`（而非两字段同写 True）——`tests/test_cancel_holdstate_recovery.py::test_no_new_holdstate_write_point_missed` 断言全库 `'"_cancelled_hold": True'` 字面命中恰好 6 处，新增该字面即红灯
- [x] 2.4 `core/state_machine.py`：从 `_recovery_preserve_spec` 提取共享判定主体为 `_resolve_preserved_branch(name, entry, project_root, worktree_manager)`（三层分支解析 + `rev-list` 非空闸门 + `resolve_resume_site` 载体三态），返回 `(resolved_branch, wt) | (None, None)`；原方法改为调用它，MUST NOT 保留第二份副本（前缀表/解析口径漂移已有事故先例）
- [x] 2.5 `core/state_machine.py`：`unfreeze_spec` 在既有清理更新集基础上接入续做接线——若 `_frozen_hold` 为真，调用 2.4 的共享判定：命中则在同一原子写中保留 `branch`/`implementer_run`、置 `_recovery_resume: True`、置 `_frozen_hold: False`、`status` 用解析出的原状态；未命中则清 `_frozen_hold`、不置 `_recovery_resume`、WARNING 记录降级原因；`_frozen_hold` 缺失时行为与改动前逐位一致
- [x] 2.6 `core/state_machine.py`：`unfreeze_spec` 传入共享判定所需的 `project_root` / `worktree_manager`（缺省 None 时跳过续做判定，保持脚本/测试场景零变化）；`core/dashboard/data/admin_actions.py::unfreeze_spec`（`admin_actions.py:167`）与 Dashboard API 调用点（`core/dashboard/routes/spec_routes.py:206`）同步传入真实 project_root 与 WorktreeManager 实例。**注意 dashboard 侧是独立进程**：`core/dashboard/` 目前零处 import `WorktreeManager`，故该侧 MUST 就地构造（`WorktreeManager(base_dir, project_root, logger=None)`，`resolve_resume_site` 是无副作用只读查询），失败/构造异常时降级为传 None（跳过续做判定，与脚本场景同语义）；MUST NOT 因构造失败使解冻本身失败
- [x] 2.7 `core/worktree_manager/stale_sweep.py`：`_branch_protected_by_state`（`stale_sweep.py:175-215`）的 (a) 判据扩展一条——`frozen` 且 `_frozen_hold` 均为真的 spec，其 `branch` 字段值属于在飞引用（保留分支）。依据：冻结终止的保留分支所在 spec 是 `blocked`（不在既有豁免集 `implementing/implemented/testing/ready+_recovery_resume` 内），而清理器 `_reclaim_expired_legacy` **不查该保护**地 `git branch -D`（`legacy_registry.py:354-359`），宽限期仅 `LEGACY_GRACE_SECONDS = STALE_LOCK_IDLE_SECONDS = 120s`（`worktree_manager/__init__.py:42/47`）——若不扩展，冻结终止后在解冻前重启 daemon（`cleanup_stale_worktrees` 在 `fenixd.py:494` 启动路径）就可能删除该分支，使「解冻后续做」降级为从零重派；同时该扩展使 `_reclaim_expired_legacy` 的 `branch -D` 与清扫路径同口径（两处共用本方法）

## 3. dispatch 冻结终止收口

> **覆盖边界（如实表述）**：`frozen_terminated=True` 只有**经 `_execute_agent` 收口**的 run 才产出——即 implementer / fast-track / verifier / tester / planner / judge / repair / 经 `_run_spec_review_worker` 的 spec-review。**administrator / code-review / self-review / evolution** 走 `maintenance_runs.py` 的独立入口（`run_administrator` / `run_code_review` / `run_self_review` / `run_evolution`），它们把 `_run_claude` 的异常就地转成 `success=False` 的普通结果（`maintenance_runs.py:209-215` / `754`），**不存在** spec 级 hold-state 收口分支（既有的 `cancelled=True` 分支同样不覆盖它们）。故 spec 名称谓里的「administrator」在本节无实现落点，实现时 MUST NOT 为这四类强加 `_frozen_hold` 写点（会与「与既有 cancelled 分支同宽」的约束自相矛盾）。

- [x] 3.1 `core/pm_engine/dispatch/queue.py`：`_run_agent_worker` 的 implementer/fast-track 结果处置在既有 `cancelled` 分支（`queue.py:1495`、紧邻 `if getattr(result, "cancelled", False)`）**之前或并列**新增 `frozen_terminated` 分支——调 `state_machine.mark_frozen_hold(spec, error)`，不翻转 status、不动 `_retry_count`/`_merge_fp`/`_merge_streak`、不入队重派、不豁免预算（区别于死亡 run 豁免）
- [x] 3.2 `core/pm_engine/dispatch/fast_track.py`：同 3.1 的冻结终止分支（落点对齐既有 `if getattr(result, "cancelled", False)`，`fast_track.py:195`；复用 `mark_frozen_hold`），MUST NOT 复用 `_cancelled_hold` 写入路径
- [x] 3.3 `core/pm_engine/dispatch/repair_lane.py`：repair run 结果处置新增冻结终止分支（同 3.1）
- [x] 3.4 `core/pm_engine/verification/legacy.py`（`legacy.py:40` 的 `if getattr(result, "cancelled", False)` 处）与 `core/pm_engine/verification/pipeline.py`（`pipeline.py:1582` 已用 `FROZEN_TERMINATED_ERROR_PREFIX` 做 frozen 让位；冻结终止分支与之并列、写 `mark_frozen_hold`）：verifier/judge run 结果处置新增冻结终止分支——保持原 status 与 error 语义，不复用既有 cancelled hold-state 代码路径
- [x] 3.5 `core/pm_engine/dispatch/queue.py`：`spec-review` 结果收口路径新增冻结终止分支——评审经 `SpecReviewManager.dispatch_review` → `_handle_review_failure` 收口（`spec_review.py:228-258/854`），冻结终止 MUST 在 `_run_spec_review_worker`（`queue.py:1735`）的「四步链外异常」收口之前拦截，避免走 `_classify_run_failure` 的 content/infra 分支递增 `_review_attempts` 或触发熔断（`_INFRA_FINGERPRINTS` 含裸 `"503"`，评审 run 的 503 重试会被判 infra）；命中时写 `mark_frozen_hold`、保持 `reviewing`、不重派、不递增 `_review_attempts`

## 4. 删除：先停后删（数据层）

- [x] 4.1 `core/dashboard/data/spec_archive.py`：`soft_delete_spec` 的运行中保护由「120s mtime 拒绝」升级为「先停后删」——检测到该 spec 有在跑 run 时，经注入的停止回调（缺省为 None 时回退既有 409 拒绝语义，保持既有单测零改动）请求终止，并在有界窗口（每 run 宽限 `AGENT_TERMINATE_GRACE_SECONDS` + 总上限常量）内轮询等待终态；超时返回 `{ok: False, running: True, pending: [run_id...]}` 且不改动 STATE 与目录
- [x] 4.2 `core/dashboard/data/spec_archive.py`：run 归属匹配统一走 `run_spec_part(p.stem) == spec` 全等（既有实现已是全等，本任务补「在跑」判定升级为「含新终态 `frozen-terminated` 判非在跑」的读侧同步，避免新终态的 run 被误判仍在跑而永久阻塞删除）
- [x] 4.3 `core/dashboard/data/admin_actions.py`：新增 `request_spec_delete(project_root, spec, stopping)`——原子写 `.fenix/spec_delete_request.json`（`{spec, source, created, stopping}`，tmp+rename+fsync）；已有未消费信号 → `{ok: False, conflict: True}`；托管态非 `managed` → `{ok: False, unmanaged: True}` / `{ok: False, daemon_down: True}`（复用既有 `hosting_state` 判定，对齐 `request_spec_approve_push` 契约）
- [x] 4.4 `core/dashboard/data/admin_actions.py`：新增 `running_run_ids_for_spec(project_root, spec) -> list[str]`——扫描 `.fenix/runs/*.jsonl` 顶层（活跃目录，`core/dashboard/data/runs.py::_resolve_run_file` 的 archive 回读口径不适用于「在跑」判定），按 `run_spec_part` 全等归属 + 末行非终态判定，返回 run_id 列表（供 API 计数与 daemon 消费方共用）。**终态口径 MUST 用写侧权威集合并集**：`core/agent_runner/liveness.py::RUN_TERMINAL_EVENT_TYPES`（result/interrupted/error/cancelled）∪ 本 SPEC 新增的 `frozen-terminated`；**MUST NOT 复用 `core.dashboard.data.classify_run`**——其读侧映射（`runs.py:128-134`）含 `superseded`，而 `superseded` **不在** `RUN_TERMINAL_EVENT_TYPES` 内（原地重试弃置事件，其后还有新 attempt 在跑，`liveness.py:168` 有明确反向注释），直接复用会把被原地重试的活跃 run 误判为已终态、让删除在 run 仍可能写盘时移走 spec 目录（违反本 SPEC「等待超时不删除」的硬约束）
- [x] 4.5 `core/dashboard/data/__init__.py`：门面转导 `request_spec_delete` 与 `running_run_ids_for_spec`（保持既有导入路径可用；`tests/test_dashboard_data_modules_contract.py` 的 `KEY_FUNCTIONS` 抽样清单可按需登记）

## 5. 删除：异步受理 API 与 daemon 消费

- [x] 5.1 `core/dashboard/routes/spec_routes.py`：`_api_spec_delete` 改造——先调 `running_run_ids_for_spec` 取在跑 run：无在跑时保持既有同步软删除（200 + 既有结果字段）；有在跑时走 `request_spec_delete` 写信号并返回受理结果（含 `{accepted: true, stopping: N}`），`unmanaged`/`daemon_down` → 409、`conflict` → 409（文案对齐既有信号族）
- [x] 5.2 `fenixd.py`：主循环新增 `_check_spec_delete_requests()`（挂载位置与 `_check_cancel_requests` 同区、同构：读取→删除→消费，损坏 JSON 删除防卡死，删除失败下轮再试）——消费 `.fenix/spec_delete_request.json`：调 `agent_runner.cancel_run` 逐个停止该 spec 在跑 run（或经 spec 级停止入口）→ 有界等待终态 → 调 `soft_delete_spec` 完成删除 → 记日志
- [x] 5.3 `fenixd.py`：为 5.2 的等待提供有界等待实现（复用/参照 `agent_runner` 的 `running_run_ids` 轮询与 `drain_wait` 形态，MUST 有总超时上限，超时记 WARNING 并放弃本轮删除、信号不再重写以免无限循环）

## 6. 前端反馈

- [x] 6.1 `core/dashboard/static/src/services/dashboard.ts`：`deleteSpec` 返回类型扩展为可含 `{accepted: true, stopping: number}`；`freezeSpec` 返回类型扩展为可含 `stopped_agents?: number`
- [x] 6.2 `core/dashboard/static/src/pages/projects/list.tsx`：`handleDeleteSpec` 收到受理结果时提示「已受理，正在停止 N 个进行中的 agent」并保持既有 `load()` 轮询（spec 行在停止+删除完成后自然消失）；无在跑 agent 时保持既有成功提示
- [x] 6.3 `core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx`：冻结成功后，若返回 `stopped_agents > 0` 则提示「已停止 N 个在跑 agent，进度已留存，解冻后可续做」；为 0 或缺省时不提示
- [x] 6.4 `core/dashboard/static/src/pages/projects/list.tsx`：删除确认弹窗文案补充「若有在跑的 agent 会先停止并留存进度」（纯文案，不改交互）

## 7. 单元测试

- [x] 7.1 `tests/test_freeze_stop_inflight_agents.py`（新建）：轮询环 frozen 命中单测——`_spec_is_frozen` 判定为真时终止序列被触发、`frozen-terminated` 终态行落盘、抛出 `FrozenTerminatedError`；未冻结时零影响；STATE 读取异常时 fail-open 不终止。**末行口径**：终态行须在 `finally` 内、读线程 join 之后追加，位置与 `cancelled` 行同级（`runner.py:3850`）；`run_metrics` 行（`runner.py:3794`）本就在终态行之后追加、且不属于终态事件，断言 MUST 按「末行终态」口径而非「最后一字节」——即以 `classify_run`/`_file_tail_is_terminal` 的读侧口径反查，MUST NOT 断言文件物理末行字符串
- [x] 7.2 `tests/test_freeze_stop_inflight_agents.py`：优先级与旗标清理——frozen 检查先于 cancel 检查；frozen 命中时残留 cancel 旗标被清理
- [x] 7.3 `tests/test_freeze_stop_inflight_agents.py`：`_frozen_hold` 序列化往返（`"True"`/`"False"` 字符串正确转布尔、缺省 False）；`mark_frozen_hold` 一次写入 `{_frozen_hold: True, _cancelled_hold: False, error}` 且保留 `branch`/`implementer_run`、不改 status
- [x] 7.4 `tests/test_freeze_stop_inflight_agents.py`：`unfreeze_spec` 续做分支——`_frozen_hold` + 分支有未合并提交 → 保留 branch/implementer_run + `_recovery_resume: True` + `_frozen_hold: False` + status 为原状态；分支零提交/缺失 → 清标记不置 `_recovery_resume`；无 `_frozen_hold` 时行为与改动前一致（回归断言）
- [x] 7.5 `tests/test_freeze_stop_inflight_agents.py`：共享判定零漂移——`_recovery_preserve_spec` 与 `unfreeze_spec` 续做经同一函数（断言两路径对同一 fixture 产出同形结果）
- [x] 7.6 `tests/test_delete_stop_inflight_agents.py`（新建）：`running_run_ids_for_spec` 全等归属——`fix-x` 不被 `impl-fix-x-y-*` 命中；`-a<n>`/`-r<n>` 后缀正确剥离；末行为 `frozen-terminated`/`cancelled`/`result`/`error` 均判非在跑；**末行为 `superseded` 时 MUST 判仍在跑**（`superseded` 是原地重试弃置事件，不在 `liveness.RUN_TERMINAL_EVENT_TYPES` 内——防误用 `classify_run` 口径）
- [x] 7.7 `tests/test_delete_stop_inflight_agents.py`：`request_spec_delete` 原子写与冲突——信号文件内容含 `spec`/`source`/`created`/`stopping`；已有信号时返回 conflict；`unmanaged`/`daemon_down` 分别返回对应标志且不写文件
- [x] 7.8 `tests/test_delete_stop_inflight_agents.py`：`soft_delete_spec` 先停后删——无在跑 run 时零等待直接删除（回归）；有在跑 run 且停止回调使其中止 → 删除成功；停止后仍不落终态（模拟）→ 超时返回 `running: True` 且 STATE/目录不变
- [x] 7.9 `tests/test_freeze_stop_inflight_agents.py`：分支保护扩展（任务 2.7）——`frozen: True` + `_frozen_hold: True` 的 `blocked` spec 的 `branch` 被 `_branch_protected_by_state` 判为受保护；`_frozen_hold` 缺失/为 False 时回归不变

## 8. 完成收尾

- [x] 8.1 `core/dashboard/static`：执行 `npm run build` 完成前端构建，确认无类型错误（dist 为 reference，构建产物不入库）
- [x] 8.2 运行本次新增与受影响的测试文件（`tests/test_freeze_stop_inflight_agents.py`、`tests/test_delete_stop_inflight_agents.py`、`tests/test_run_cancel.py`、`tests/test_cancel_holdstate_recovery.py`、`tests/test_run_spec_prefixed_attribution.py`、`tests/test_interrupt_recovery_preserve.py`、`tests/test_dashboard_data_modules_contract.py`、`tests/test_agent_runner_modules_contract.py`、`tests/test_dashboard_data.py`、`tests/test_daemon_lifecycle_races.py`）并修复全部失败。**仓库无 `bin/run_full_suite.py`**，全量回归入口见 8.3。
- [x] 8.3 全量回归（有界入口：`python3 -m pytest tests -x -q --timeout=3600`，与既有 `tests/` 布局一致；若确需分档则用 `pytest -k` 分批），修复本次引入的失败
- [x] 8.4 更新 `docs/help/09-config.md` 或 `docs/help/02-concepts.md` 中关于冻结/删除语义的段落，说明「冻结即停在跑 agent、解冻自动续做」「删除先停后删」的新行为## 验证修复（原地打回第 2 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/add-freeze-stop-inflight-agents/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [x] 修复后重跑验证确认通过

## 验证修复（原地打回第 1 轮）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/add-freeze-stop-inflight-agents/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
