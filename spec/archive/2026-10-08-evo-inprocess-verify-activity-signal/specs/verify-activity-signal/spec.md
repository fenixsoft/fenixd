# Spec Delta: verify-activity-signal

## NEW Requirements

### Requirement: spec_is_undriven 必须识别进程内验证形态

spec_is_undriven（core/admin_monitor.py:706-778）MUST 新增条件⑤：daemon 进程内存在名为 fenix-verifier-<spec> 的活线程（threading.enumerate()，线程名出处 core/pm_engine/dispatch/queue.py 线程构造 name=f"fenix-{agent_type}-{spec_name}"）时判定「有驱动」。同进程调用的两个消费点（admin_monitor._detect_orphaned_state :2666、event_bus._recover_testing :439）因此自动豁免，MUST NOT 再对活跃中的 in-process 全量验证发 orphaned_state 或重派验证。

- 进度文件 mtime MUST 作为条件⑤ helper 的 OR 臂（评审钉死落点：NOT 条件①扩展）：.fenix/verify-progress/<spec>.json（verify_engine._write_progress 既有产物，engine.py:700-733）mtime 落入独立活动窗口内即判有驱动；条件① _has_recent_spec_run（120s run 宽限）保持不动。窗口常量 MUST 独立于 ORPHANED_RUN_GRACE_SECONDS（120s），缺省对齐 DEFAULT_ORPHANED_STATE_THRESHOLD_MINUTES（15 分钟）——单场景长批间隔实测 4-5 分钟，120s 会假阴性。
- docstring MUST 按既有记忆惯例增补条件⑤的由来实证（2026-10-02 cimbar-airgap-transfer 误报孤儿态+重复验证），保持「每次误报补条件并留证」的演化记录。
- 两类新信号 MUST NOT 产生假阳性豁免：线程已退出且进度文件超窗时，判定结果 MUST 与现状完全一致。

**背景（事件依据）**：2026-10-02 09:50:36Z/10:35:37Z 两条 orphaned_state 告警均发生在验证引擎活跃期；fenixd.log 09:50:34Z 与 09:58:19Z 两次自动重派致三个 23 场景批交错；admin-cimbar-airgap-transfer-1790934636 调查 run $1.289。

#### Scenario: 验证活跃期不再误判孤儿

- **WHEN** 全量验证在 daemon 线程 fenix-verifier-<spec> 内执行（无论进度文件 mtime 新旧）
- **THEN** spec_is_undriven 判「有驱动」；_detect_orphaned_state 与 _recover_testing 均不触发重派

#### Scenario: 长单场景批间静默仍豁免

- **WHEN** verifier 线程存活但单场景执行超 120s（进度文件 mtime 停滞）
- **THEN** 条件⑤仍判有驱动（线程探测零时间窗依赖），不因沿用 120s 宽限而假阴性

#### Scenario: 验证结束后口径不变

- **WHEN** verifier 线程已退出且 .fenix/verify-progress/<spec>.json 超独立窗口
- **THEN** 判定结果与现状四条件口径完全一致，无新增豁免

### Requirement: 处置复位直通道重派前必须复核在飞验证

_reset_orphaned_after_disposition（core/admin_monitor.py:4679）testing 分支的复位直通道（transition + 重派，:4720-4733）在执行重派前 MUST 复核条件⑤/进度 mtime（复用同一 helper），命中即顺延重派——该出口不经 spec_is_undriven，是 2026-10-02 09:58:19Z 第三批重派的直接来源。

#### Scenario: 处置完成瞬间不打断在飞批

- **WHEN** admin 处置写 result 触发 testing 复位直通道，而 verifier 线程仍在执行
- **THEN** 复位语义保留（transition_gate(testing) 幂等 + 清 error），重派跳过、无重复批；在飞验证结果路径照常推进状态，不设延迟队列