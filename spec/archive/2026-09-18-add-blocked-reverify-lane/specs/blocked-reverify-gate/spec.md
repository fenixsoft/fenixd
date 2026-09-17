# Spec Delta: blocked-reverify-gate

## ADDED Requirements

### Requirement: BLOCKED 重验直通道（实现分支已合并时）

环境阻塞类冻结（`_escalate_env_blocked` 写入的 blocked，`_env_block_rounds >= 1` 且非人工冻结）在 admin 处置完成、结果为 resolved/partially-resolved 时，若该 spec 的实现分支已合并进主树（branch 字段非空且 branch 的 merge commit 存在于主树历史），框架必须将 spec 自动转换为 testing 重新派发 verifier，不得经由 ready→implementing 触发全量重实现。

#### Scenario: branch 已合并的 env 阻塞复位直达 testing

- **WHEN** spec 处于 blocked（env 阻塞，`_env_block_rounds=1`），branch=fenix/&lt;spec&gt;-&lt;ts&gt; 且该分支已 merge 进 main，admin 处置完成且 result=resolved
- **THEN** 框架调用门禁转换 `transition_gate(spec, "testing")`（GATE_TRANSITIONS 扩展后允许 BLOCKED→TESTING），清 error、保留 implementer_run/branch/_env_block_rounds，verifier 入队重验
- **AND** 全程不产生新的 implementer run，`_impl_run_budget_used` 不变

#### Scenario: branch 未合并或实现阶段冻结保持 ready 通道

- **WHEN** spec 处于 blocked 但 branch 为空（实现阶段熔断）或 branch 未合并进主树
- **THEN** 处置完成复位仍走既有 blocked→ready（VALID_TRANSITIONS），implementer 正常重派
- **AND** 该路径 `_env_block_rounds` 不清零（生命周期累计语义）

#### Scenario: 人工路径不得绕过 VALID_TRANSITIONS

- **WHEN** 人工/任意调用方对 blocked spec 直接调用 `transition(spec, "testing")`
- **THEN** 转换被拒绝（VALID_TRANSITIONS 中 BLOCKED 仅允许 READY），返回 False
- **AND** 仅 `transition_gate`（GATE_TRANSITIONS 声明 BLOCKED: [TESTING]）+ 守卫条件满足时才放行，与 VERIFIED→TESTING 逃生门（verifier-judgment-integrity D7）同款约束

### Requirement: admin 处置复位动作收敛为框架机械动作

`verify_env_blocked` 自动呼叫的提示词必须声明：处置范围限于环境修复（依赖/服务/端口/容器/验证产物），完成后由框架在处置收尾自动判定复位路径（branch 已合并→testing 直通道；否则→ready），Administrator 不得手动写 spec 状态。处置收尾消费点（admin_monitor 摄取 disposition result 的位置）必须内建复位调用，admin 手动 StateMachine 写法不再为完成闭环所必需。

#### Scenario: admin 处置完成无需手动操作状态

- **WHEN** admin 处置 env 阻塞完成，写入 disposition 文件 result=resolved，未触碰 spec 状态
- **THEN** admin_monitor 消费 disposition 后自动执行复位判定：branch 已合并 → transition_gate(testing)；否则 → transition(ready)
- **AND** 提示词（admin prompt 模板）明确「不要手动 reset spec 状态」，处置建议文本同步修订

#### Scenario: admin 手动复位兼容（防御）

- **WHEN** admin（或用户）仍手动把 blocked 复位为 ready（如经 Dashboard unfreeze）
- **THEN** 行为与现状一致（ready→implementing 重派），框架不报错不重复派发
- **AND** 该路径 `_env_block_rounds` 保持不清零

### Requirement: _env_block_rounds 生命周期累计

`_env_block_rounds` 的清零点收敛为两处：验证通过（verified 落定，两处既有清零点保留）与人工 `unfreeze_spec`。admin 处置复位（无论复位到 testing 还是 ready）、daemon 恢复、fix 链等一切中间转换不得清零。字段须以显式常量（ENV_BLOCK_ROUNDS_FIELD）登记进 state_machine 字段名单，与 IMPL_RUN_BUDGET_USED_FIELD 同款。冻结阈值维持 `rounds >= 2` 不变：spec 生命周期内第 2 次 env 阻塞即冻结转人工。

#### Scenario: 连续两轮 env 阻塞冻结转人工可达

- **WHEN** spec 第 1 轮 env 阻塞（rounds=1）→ admin 处置复位（不清零）→ 重验再次全批 env 阻塞
- **THEN** `_escalate_env_blocked` 计算 rounds=2 → frozen 结构化冻结 + 人工升级告警（含 planner 成本参考）
- **AND** 唯一出路为人工 unfreeze_spec（清零 rounds 与 error）

#### Scenario: 验证通过是唯一自动清零点

- **WHEN** spec 曾经历 env 阻塞（rounds=1）后重验全绿
- **THEN** verified 落定处清零 `_env_block_rounds`（与 `_verify_fail_rounds` PASS 唯一归零点同语义）
- **AND** 后续新阻塞从 1 重新计数（跨验证周期不累计）

#### Scenario: 中间转换不清零

- **WHEN** admin 处置复位（任一目标态）、daemon 重启恢复、fix 链打回等中间转换发生
- **THEN** `_env_block_rounds` 值保持不变
