# add-freeze-stop-inflight-agents — Tasks

## Deliverables

```yaml
- path: core/agent_runner/runner.py
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
- path: core/dashboard/data/runs.py
  kind: modify
- path: core/dashboard/data/spec_archive.py
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

- [ ] 1.1 `core/agent_runner/runner.py`：新增 `FrozenTerminatedError` 异常类（携带 reason），与 `RunCancelledError` 并列定义于同处；导出供 pm_engine 判定
- [ ] 1.2 `core/agent_runner/runner.py`：`_run_claude` 轮询环在既有 `_cancel_is_requested` 检查**之前**插入 frozen 检查——`self._spec_is_frozen(spec_name)` 命中则：① 对当前 worktree 执行 `_wip_checkpoint_on_forced_kill`（新增 anchor 常量 `freeze-hold`，失败 WARNING 不阻断）② `proc.terminate()` → `wait(timeout=AGENT_TERMINATE_GRACE_SECONDS)` → 超时 `proc.kill()` ③ 置 `returncode = -15`、构造 `FrozenTerminatedError(reason=...)`、`break`；同时清理该 base_run_id 残留的 cancel 旗标（`_cancel_clear`）
- [ ] 1.3 `core/agent_runner/runner.py`：`_run_claude` 的 `finally` 段在既有 `cancel_error` 落盘之后并列处理 `frozen_error`——追加 `{"type": "frozen-terminated", "reason", "by", "timestamp"}` 终态行（保证为文件末行），并抛 `FrozenTerminatedError`
- [ ] 1.4 `core/agent_runner/runner.py`：`_execute_agent` 原地重试子循环在 `except RunCancelledError` 旁新增 `except FrozenTerminatedError`——不重试、不计秒挂、不触发 provider 切换，置 `frozen_terminated_flag = True` 与 error 文案（含「冻结」语义）后 `break`
- [ ] 1.5 `core/agent_runner/runner.py`：`_AttemptState` 增加 `frozen_terminated_flag` 字段；`_exhausted_result` 增加 `frozen_terminated_flag` 参数与分支，返回 `AgentRunResult(frozen_terminated=True, ...)`；`AgentRunResult` 增加 `frozen_terminated: bool = False` 并按既有 `cancelled` 同款纳入 `to_dict` 序列化
- [ ] 1.6 `core/agent_runner/runner.py`：`_finalize_failure_keep` 增加 `frozen_terminated_flag` 参数——冻结终止时 MUST `break`（不进入下一 attempt、`time.sleep(10)` 重试）；worktree 处置沿用既有 `repair`/`fast-track` 保留语义，其余类型按 `shutdown_interrupted` 同款的「保留现场」分支处理（`kept_wt_path` + `handed_off.add`），MUST NOT 走 `cleanup(success=False)` 销毁保全现场
- [ ] 1.7 `core/agent_runner/runner.py`：`_attempt_top_guards` 的 frozen 分支改为复用同一 `FrozenTerminatedError` 通道（保持既有「不派发 attempt」行为，补 `frozen_terminated=True` 结果字段），使边界守卫与在飞终止语义一致
- [ ] 1.8 `core/agent_runner/liveness.py`：`RUN_TERMINAL_EVENT_TYPES` 加入 `"frozen-terminated"`（写侧权威），并在注释中标注与 `core/dashboard/data/runs.py::_RUN_TERMINAL_STATUS_MAP` 的同步义务
- [ ] 1.9 `core/dashboard/data/runs.py`：`_RUN_TERMINAL_STATUS_MAP` 加入 `"frozen-terminated": "frozen-terminated"`，并更新该表上方的注释（说明新终态的行来源与读侧缺映射的后果）

## 2. STATE 独立保持标记

- [ ] 2.1 `core/state_machine.py`：新增字段常量 `FROZEN_HOLD_FIELD = "_frozen_hold"`；纳入序列化显式键表与布尔显式转换分支（与 `_cancelled_hold` 同处），注释固化「与 `_cancelled_hold` 并列、互不读写」契约
- [ ] 2.2 `core/state_machine.py`：`freeze_spec` 增加保全锚点行为——冻结时若该 spec 当前 status 在 `INTERRUPTED_STATES`（implementing/testing/reviewing）则把 `branch` / `implementer_run` / `reviewer_run` 一并写入同一次 `update_spec`（MUST NOT 因冻结清空这些锚点，否则解冻无从续做）
- [ ] 2.3 `core/state_machine.py`：新增 `mark_frozen_hold(spec_name, error)` 方法——单次原子写 `{FROZEN_HOLD_FIELD: True, "_cancelled_hold": False, "error": error}`，MUST NOT 改 `status`、MUST NOT 清 `branch`/`implementer_run`；注释固化调用方（dispatch 侧冻结终止分支）
- [ ] 2.4 `core/state_machine.py`：从 `_recovery_preserve_spec` 提取共享判定主体为 `_resolve_preserved_branch(name, entry, project_root, worktree_manager)`（三层分支解析 + `rev-list` 非空闸门 + `resolve_resume_site` 载体三态），返回 `(resolved_branch, wt) | (None, None)`；原方法改为调用它，MUST NOT 保留第二份副本（前缀表/解析口径漂移已有事故先例）
- [ ] 2.5 `core/state_machine.py`：`unfreeze_spec` 在既有清理更新集基础上接入续做接线——若 `_frozen_hold` 为真，调用 2.4 的共享判定：命中则在同一原子写中保留 `branch`/`implementer_run`、置 `_recovery_resume: True`、置 `_frozen_hold: False`、`status` 用解析出的原状态；未命中则清 `_frozen_hold`、不置 `_recovery_resume`、WARNING 记录降级原因；`_frozen_hold` 缺失时行为与改动前逐位一致
- [ ] 2.6 `core/state_machine.py`：`unfreeze_spec` 传入共享判定所需的 `project_root` / `worktree_manager`（缺省 None 时跳过续做判定，保持脚本/测试场景零变化）；`core/dashboard/data/admin_actions.py::unfreeze_spec` 与 Dashboard API 调用点同步传入真实 project_root 与 WorktreeManager 实例

## 3. dispatch 冻结终止收口

- [ ] 3.1 `core/pm_engine/dispatch/queue.py`：implementer/fast-track 结果处置在既有 `cancelled` 分支**之前或并列**新增 `frozen_terminated` 分支——调 `state_machine.mark_frozen_hold(spec, error)`，不翻转 status、不动 `_retry_count`/`_merge_fp`/`_merge_streak`、不入队重派、不豁免预算（区别于死亡 run 豁免）
- [ ] 3.2 `core/pm_engine/dispatch/fast_track.py`：同 3.1 的冻结终止分支（复用 `mark_frozen_hold`），MUST NOT 复用 `_cancelled_hold` 写入路径
- [ ] 3.3 `core/pm_engine/dispatch/repair_lane.py`：repair run 结果处置新增冻结终止分支（同 3.1）
- [ ] 3.4 `core/pm_engine/verification/legacy.py` 与 `core/pm_engine/verification/pipeline.py`：verifier/judge run 结果处置新增冻结终止分支——写 `mark_frozen_hold`，保持原 status 与 error 语义（与既有 cancelled hold-state 分支并列，不复用其代码路径）
- [ ] 3.5 `core/pm_engine/dispatch/queue.py`：`spec-review` 结果收口路径新增冻结终止分支（同 3.1），使评审在飞 run 被冻结终止时不重派

## 4. 删除：先停后删（数据层）

- [ ] 4.1 `core/dashboard/data/spec_archive.py`：`soft_delete_spec` 的运行中保护由「120s mtime 拒绝」升级为「先停后删」——检测到该 spec 有在跑 run 时，经注入的停止回调（缺省为 None 时回退既有 409 拒绝语义，保持既有单测零改动）请求终止，并在有界窗口（每 run 宽限 `AGENT_TERMINATE_GRACE_SECONDS` + 总上限常量）内轮询等待终态；超时返回 `{ok: False, running: True, pending: [run_id...]}` 且不改动 STATE 与目录
- [ ] 4.2 `core/dashboard/data/spec_archive.py`：run 归属匹配统一走 `run_spec_part(p.stem) == spec` 全等（既有实现已是全等，本任务补「在跑」判定升级为「含新终态 `frozen-terminated` 判非在跑」的读侧同步，避免新终态的 run 被误判仍在跑而永久阻塞删除）
- [ ] 4.3 `core/dashboard/data/admin_actions.py`：新增 `request_spec_delete(project_root, spec, stopping)`——原子写 `.fenix/spec_delete_request.json`（`{spec, source, created, stopping}`，tmp+rename+fsync）；已有未消费信号 → `{ok: False, conflict: True}`；托管态非 `managed` → `{ok: False, unmanaged: True}` / `{ok: False, daemon_down: True}`（复用既有 `hosting_state` 判定，对齐 `request_spec_approve_push` 契约）
- [ ] 4.4 `core/dashboard/data/admin_actions.py`：新增 `running_run_ids_for_spec(project_root, spec) -> list[str]`——扫描 `.fenix/runs/*.jsonl` 顶层，按 `run_spec_part` 全等归属 + 末行非终态（复用 `classify_run` 口径）判定在跑，返回 run_id 列表（供 API 计数与 daemon 消费方共用）
- [ ] 4.5 `core/dashboard/data/__init__.py`：门面转导 `request_spec_delete` 与 `running_run_ids_for_spec`（保持既有导入路径可用）

## 5. 删除：异步受理 API 与 daemon 消费

- [ ] 5.1 `core/dashboard/routes/spec_routes.py`：`_api_spec_delete` 改造——先调 `running_run_ids_for_spec` 取在跑 run：无在跑时保持既有同步软删除（200 + 既有结果字段）；有在跑时走 `request_spec_delete` 写信号并返回受理结果（含 `{accepted: true, stopping: N}`），`unmanaged`/`daemon_down` → 409、`conflict` → 409（文案对齐既有信号族）
- [ ] 5.2 `fenixd.py`：主循环新增 `_check_spec_delete_requests()`（挂载位置与 `_check_cancel_requests` 同区、同构：读取→删除→消费，损坏 JSON 删除防卡死，删除失败下轮再试）——消费 `.fenix/spec_delete_request.json`：调 `agent_runner.cancel_run` 逐个停止该 spec 在跑 run（或经 spec 级停止入口）→ 有界等待终态 → 调 `soft_delete_spec` 完成删除 → 记日志
- [ ] 5.3 `fenixd.py`：为 5.2 的等待提供有界等待实现（复用/参照 `agent_runner` 的 `running_run_ids` 轮询与 `drain_wait` 形态，MUST 有总超时上限，超时记 WARNING 并放弃本轮删除、信号不再重写以免无限循环）

## 6. 前端反馈

- [ ] 6.1 `core/dashboard/static/src/services/dashboard.ts`：`deleteSpec` 返回类型扩展为可含 `{accepted: true, stopping: number}`；`freezeSpec` 返回类型扩展为可含 `stopped_agents?: number`
- [ ] 6.2 `core/dashboard/static/src/pages/projects/list.tsx`：`handleDeleteSpec` 收到受理结果时提示「已受理，正在停止 N 个进行中的 agent」并保持既有 `load()` 轮询（spec 行在停止+删除完成后自然消失）；无在跑 agent 时保持既有成功提示
- [ ] 6.3 `core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx`：冻结成功后，若返回 `stopped_agents > 0` 则提示「已停止 N 个在跑 agent，进度已留存，解冻后可续做」；为 0 或缺省时不提示
- [ ] 6.4 `core/dashboard/static/src/pages/projects/list.tsx`：删除确认弹窗文案补充「若有在跑的 agent 会先停止并留存进度」（纯文案，不改交互）

## 7. 单元测试

- [ ] 7.1 `tests/test_freeze_stop_inflight_agents.py`（新建）：轮询环 frozen 命中单测——`_spec_is_frozen` 判定为真时终止序列被触发、`frozen-terminated` 终态行落盘且为末行、抛出 `FrozenTerminatedError`；未冻结时零影响；STATE 读取异常时 fail-open 不终止
- [ ] 7.2 `tests/test_freeze_stop_inflight_agents.py`：优先级与旗标清理——frozen 检查先于 cancel 检查；frozen 命中时残留 cancel 旗标被清理
- [ ] 7.3 `tests/test_freeze_stop_inflight_agents.py`：`_frozen_hold` 序列化往返（`"True"`/`"False"` 字符串正确转布尔、缺省 False）；`mark_frozen_hold` 一次写入 `{_frozen_hold: True, _cancelled_hold: False, error}` 且保留 `branch`/`implementer_run`、不改 status
- [ ] 7.4 `tests/test_freeze_stop_inflight_agents.py`：`unfreeze_spec` 续做分支——`_frozen_hold` + 分支有未合并提交 → 保留 branch/implementer_run + `_recovery_resume: True` + `_frozen_hold: False` + status 为原状态；分支零提交/缺失 → 清标记不置 `_recovery_resume`；无 `_frozen_hold` 时行为与改动前一致（回归断言）
- [ ] 7.5 `tests/test_freeze_stop_inflight_agents.py`：共享判定零漂移——`_recovery_preserve_spec` 与 `unfreeze_spec` 续做经同一函数（断言两路径对同一 fixture 产出同形结果）
- [ ] 7.6 `tests/test_delete_stop_inflight_agents.py`（新建）：`running_run_ids_for_spec` 全等归属——`fix-x` 不被 `impl-fix-x-y-*` 命中；`-a<n>`/`-r<n>` 后缀正确剥离；末行为 `frozen-terminated`/`cancelled`/`result`/`error` 均判非在跑
- [ ] 7.7 `tests/test_delete_stop_inflight_agents.py`：`request_spec_delete` 原子写与冲突——信号文件内容含 `spec`/`source`/`created`/`stopping`；已有信号时返回 conflict；`unmanaged`/`daemon_down` 分别返回对应标志且不写文件
- [ ] 7.8 `tests/test_delete_stop_inflight_agents.py`：`soft_delete_spec` 先停后删——无在跑 run 时零等待直接删除（回归）；有在跑 run 且停止回调使其中止 → 删除成功；停止后仍不落终态（模拟）→ 超时返回 `running: True` 且 STATE/目录不变
 
## 8. 完成收尾

- [ ] 8.1 `core/dashboard/static`：执行 `npm run build` 完成前端构建，确认无类型错误（dist 为 reference，构建产物不入库）
- [ ] 8.2 运行本次新增与受影响的测试文件（`tests/test_freeze_stop_inflight_agents.py`、`tests/test_delete_stop_inflight_agents.py`、`tests/test_run_cancel.py`、`tests/test_cancel_holdstate_recovery.py`、`tests/test_run_spec_prefixed_attribution.py`、`tests/test_interrupt_recovery_preserve.py`、`tests/test_dashboard_data_modules_contract.py`）并修复全部失败
- [ ] 8.3 全量回归走有界入口 `python3 bin/run_full_suite.py --timeout 3600`，修复本次引入的失败（存量失败按 `--baseline` 归类）
- [ ] 8.4 更新 `docs/help/09-config.md` 或 `docs/help/02-concepts.md` 中关于冻结/删除语义的段落，说明「冻结即停在跑 agent、解冻自动续做」「删除先停后删」的新行为
