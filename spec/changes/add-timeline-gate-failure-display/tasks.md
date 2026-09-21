# add-timeline-gate-failure-display — Tasks

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/dashboard/data/runs.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: tests/test_agent_runner_gate.py
  kind: modify
- path: tests/test_dashboard_data.py
  kind: modify
```

> 说明：`core/dashboard/static/dist/`（前端构建产物，被 `.gitignore` 的 `dist/` 排除、主树未跟踪）
> 不入库，属 `reference` 非交付物；仅需保证 `npm run build` 通过（对齐 `add-test-regression-tab`
> tasks.md:110 同款处置），框架 merge 后会自动重建主树产物。

## 1. 写侧：run jsonl 带门禁归因

- [ ] 1.1 `core/agent_runner/runner.py` `_handle_artifact_gate_retry`（`:2653`）：在写 `transient_retry`（`:2709`）与 `superseded`（`:2724`）两处 `append_run_line` 的 payload 中各增 `"error": error[:_GATE_ERROR_TRUNCATE]`；新增模块级常量 `_GATE_ERROR_TRUNCATE = 1024`（附注释：单位为**字符（code point）**、UTF-8 最坏 ≤4 KiB 仍低于 `append_run_line` 的 8 KiB 单行缓冲，见 `run_files.py:56-71`；实现 MUST 用切片 `error[:1024]`，MUST NOT 改成字节截断）
- [ ] 1.2 `core/agent_runner/runner.py` `_handle_artifact_gate_retry`：在「原地预算耗尽 → 返回 `do_break`」（`:2704-2706`）分支，返回前追加终态事件 `{"type": "gate-blocked", "spec": spec_name, "provider": provider_name, "reason": "artifact_gate", "error": error[:_GATE_ERROR_TRUNCATE], "timestamp": datetime.now(timezone.utc).isoformat()}` 到同一 `sub_run_id` 文件；MUST 为末行
- [ ] 1.3 门禁路径**其余早退分支**按 design D2 的分支表逐条落位（穷举，MUST NOT 用一个 `reason` 值糊过去）：
  - `is_task_gate`（`:2702-2703`，任务完成度类）→ 同 1.2 追加 `gate-blocked`，但 `reason` MUST 为 `"task_gate"`（MUST NOT 写 `artifact_gate`——归因是任务完成度门而非产物结构门）；
  - 退避后让位（`:2751-2775`）MUST **NOT** 写 `gate-blocked`：弃置原因是「spec 已被接管」而非门禁，该文件终态由 1.1 的 `superseded` + `error` 承担；写了属误标（把「被接管」显示成「门禁拒绝」）且同一次失败会出现两个失败节点（详见 design D2）
- [ ] 1.4 确认 `provider` 字段在 provider 为 None 时仍可序列化（写 `provider_name or ""`），避免下游解析异常
- [ ] 1.5 `core/agent_runner/liveness.py` `RUN_TERMINAL_EVENT_TYPES`（`:81-90`）增 `"gate-blocked"`，紧邻注释写明：① 两侧同步义务（先例 `:75-80` frozen-terminated）；② 与 `superseded` **故意排除**（`:170-180`）的差异理由（`gate-blocked` 写后该文件再无写入者、attempt 已终止；`superseded` 写在退避 sleep 之前、其窗口内没有别的文件代表该 run）。缺此步 `running_run_ids_for_spec` / `soft_delete_spec` 会把末行 `gate-blocked` 的 run 判成「在跑」→ 刚被门禁拦下的 SPEC 删除/归档被误拦

## 2. 读侧：终态映射与原因提取

- [ ] 2.1 `core/dashboard/data/runs.py` `_RUN_TERMINAL_STATUS_MAP`（`:131-138`）增 `"gate-blocked": "gate-blocked"`，并在紧邻注释补一句归因（门禁因产物硬门失败终止本次 attempt 的终态；`superseded` 是同一失败链的中间弃置件，`gate-blocked` 是其终态收口）
- [ ] 2.2 `_is_run_archivable` 走 `_RETENTION_ARCHIVABLE_STATUSES`（`:736`，由 `_RUN_TERMINAL_STATUS_MAP.values()` 派生）——确认零改代码即自动纳入；若发现任何硬编码枚举清单（`grep gate-blocked` 前置：`grep -rn "_RUN_TERMINAL_STATUS_MAP\|superseded" core/`），逐处补 `gate-blocked`
- [ ] 2.3 确认 `classify_run`（`:148-161`）对 `gate-blocked` 返回该枚举值（无需改代码，由映射查表实现）——加用例锁定
- [ ] 2.4 逐处复核 design D4 表**全部**消费点（归档判定 / 活跃计数 / 预算计数 `core/pm_engine/budget.py:417` / 在跑判定 `admin_actions.py:152` + `spec_archive.py:24` / code-review 进度 `core/code_review.py:713` / 存活探测 `liveness.py:390`），确认 `gate-blocked` 语义正确；任何需要代码改动处 MUST 在本任务说明并实现（已知需改：`RUN_TERMINAL_EVENT_TYPES`，见 1.5）
- [ ] 2.5 `get_spec_timeline`（`core/dashboard/data/timeline.py:266-279`）确认 run 节点已透传 `insights["reason"]`（现状已透传）与 `status`；零改动，仅加断言

## 3. 前端：门禁拒绝渲染

- [ ] 3.1 `core/dashboard/static/src/pages/projects/detail.tsx` run 节点分支（`:1009` 起）：新增 `const isGateBlocked = st === 'gate-blocked';`，`dotColor` 与状态 Tag 颜色把 `isGateBlocked` 并入失败色（红）分支；Tag 文案在 `isGateBlocked` 时显示「门禁拒绝」，`st === 'error'` 时维持现状
- [ ] 3.2 同文件 `reason` 渲染块（`:1071-1078`）：`isErr || isGateBlocked` 用 `danger` 色，前缀按 `isGateBlocked ? '门禁拒绝：' : '失败原因：'` 分派；`superseded` 且 `reason` 非空时用 `secondary` 色 + 前缀「原地重试：」
- [ ] 3.3 未知 status 守卫：`gate-blocked` / `superseded` 之外的未知值行为不变；移动端（`isMobile`）样式与既有卡片一致

## 4. 测试

- [ ] 4.1 `tests/test_agent_runner_gate.py`：新增用例——① 门禁失败写 `transient_retry` 时事件含非空 `error` 且含门禁名；② 门禁失败弃置时 `superseded` 含非空 `error`；③ 原地预算耗尽时该 attempt 文件末行 `type == "gate-blocked"` 且含 `error`/`reason`（结构类 `reason == "artifact_gate"`；`is_task_gate` 类 `reason == "task_gate"`）；④ 该文件末行 MUST NOT 为 `result`；⑤ `error` 超长时被截断至 ≤1024 **字符**（UTF-8 编码后 ≤4096 字节）。构造方式沿用既有 gate 用例的 runner 替身
- [ ] 4.2 `tests/test_dashboard_data.py`：新增用例——① `classify_run` 对末行 `gate-blocked` 返回 `"gate-blocked"`；② `_is_run_archivable` 对 `gate-blocked` 返回 True；③ `_run_tail_insights` 对含 `error` 的 `gate-blocked` / `superseded` 末行返回非空 `reason`；④ `active_run_count` 不计 `gate-blocked`；⑤ 时间轴 run 节点在 `gate-blocked` 时 `status`/`reason` 字段正确下发
- [ ] 4.3 预算侧用例（可置于 `tests/test_agent_runner_gate.py` 或预算测试文件）：`_run_file_died` 对末行 `gate-blocked` 返回 False（不被计作死亡 run）
- [ ] 4.4 在跑判定用例（沿用 `tests/test_freeze_stop_inflight_agents.py` 的构造方式）：① `RUN_TERMINAL_EVENT_TYPES` MUST 含 `gate-blocked`（两侧同步锁定）；② `running_run_ids_for_spec` 对末行 `gate-blocked` 的 run MUST NOT 判在跑；③ `soft_delete_spec`（`stop_callback=None`）对仅剩末行 `gate-blocked` run 的 spec MUST 返回 `running: False` 并完成软删除

## 5. 收尾验证

- [ ] 5.1 `cd core/dashboard/static && npm run build` 构建通过；`dist/` 变动不提交（reference）
- [ ] 5.2 跑受影响测试集（`tests/test_agent_runner_gate.py`、`tests/test_dashboard_data.py`、`tests/test_characterization_dashboard_data.py`、`tests/test_timeline_transition_context.py`、`tests/test_freeze_stop_inflight_agents.py`）全绿
- [ ] 5.3 跑有界全量回归 `python3 bin/run_full_suite.py --timeout 3600`，确认零本次引入失败（允许既有环境性失败，须逐一列举并说明与本次改动无关）
