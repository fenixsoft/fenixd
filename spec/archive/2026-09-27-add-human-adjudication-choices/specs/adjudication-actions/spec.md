## ADDED Requirements

### Requirement: reset_verification 裁决动词

`core/dashboard/data/admin_actions.py` MUST 新增 `reset_verification(project_root, spec)`：语义为「人工裁定验证链输入已失真，重置验证重跑」。执行序列：(1) 前置校验——spec 存在且处于冻结或 blocked 态，冻结原因属验证链信号（judge_rerun_cap / 验证失败升级闸门 / env 阻塞族），否则拒绝并说明；(2) 删除该 spec 的冻结场景与验证进度运行时文件（`.fenix/verify-progress/<spec>/` 下场景集文件）；(3) 清零 judge 重跑计数与验证失败轮计数（生命周期累计字段除外，不清零历史审计）；(4) 解除冻结并按既有复位路径推进——实现分支已合并走 testing 直通道重验，否则回 ready 重实现（复用 `resolve_env_blocked_reset_path` 判定）；(5) 返回结构化结果（执行了哪些步骤、目标状态）。

#### Scenario: 冻结态 spec 重置验证成功
- **WHEN** 对因 judge_rerun_cap 冻结的 spec 调用 reset_verification
- **THEN** 场景文件被删除、judge 重跑计数清零、冻结解除、spec 进入重验路径，返回结果含执行步骤明细

#### Scenario: 非验证类冻结被拒绝
- **WHEN** 对因 SPEC 评审否决冻结的 spec 调用 reset_verification
- **THEN** 返回拒绝错误说明冻结原因不属验证链，spec 状态不变

### Requirement: force_advance 裁决动词

`core/dashboard/data/admin_actions.py` MUST 新增 `force_advance(project_root, spec, target_status="done", note="")`：语义为「人工裁定接受现状，豁免剩余缺口推进」。执行序列：(1) 前置校验——spec 存在且处于冻结或 blocked 态，否则拒绝；(2) 解除冻结；(3) 将 spec 推进到 `target_status`（缺省 done），清 error 字段。推进路径约定：冻结 spec 实际处于 blocked（或 reviewing）态，而 `blocked→done` 不在 `VALID_TRANSITIONS`（core/state_machine.py，blocked 仅可达 ready/reviewing）——本步骤 MUST 走 `StateMachine.update_spec` 显式豁免通道（updates 同时携带 `frozen=False` 与 `status`，冻结剥离守卫对自带 frozen 键的更新原样放行），与 design D4 及既有 admin 处置复位路径同一范式；MUST NOT 为达成推进直写 STATE.md；(4) 裁决依据（note）写入推进留痕（STATE Transition 记录或处置记录，MUST 可追溯「这是人工豁免推进而非自然达成」）。该动词是 `/fenix-approve` 人工豁免语义在 dashboard 侧的最小等价物；MUST NOT 触碰实现分支内容或主树工作区文件。

#### Scenario: 冻结 spec 豁免推进 done
- **WHEN** 对实现预算耗尽冻结的 spec 调用 force_advance（缺省 target_status=done，note 说明依据）
- **THEN** spec 状态变为 done、冻结解除、error 清空，且推进留痕含人工豁免标记与 note 原文

#### Scenario: 未冻结 spec 被拒绝
- **WHEN** 对处于 implementing 正常态的 spec 调用 force_advance
- **THEN** 返回拒绝错误，spec 状态不变

### Requirement: skip_review_gate 裁决动词

`core/dashboard/data/admin_actions.py` MUST 新增 `skip_review_gate(project_root, spec, note="")`：语义为「评审器持续基础设施失败时人工授权跳过评审门」。执行序列：(1) 前置校验——spec 处于评审冻结态（`spec-review-incomplete` 冻结，状态 reviewing + frozen），否则拒绝；(2) 解除冻结并将 spec 从 reviewing 推进到 ready（跳过评审门），推进留痕标注「人工授权跳过评审」与 note；(3) 返回结构化结果。该动词 MUST 仅对评审器自身失败冻结开放，MUST NOT 能跳过评审否决（方向不成立）类冻结。

#### Scenario: 评审器连坏冻结的 spec 跳过评审门
- **WHEN** 对 `spec-review-incomplete` 冻结的 spec 调用 skip_review_gate
- **THEN** spec 从 reviewing 推进到 ready、冻结解除，留痕含人工授权标记，spec 进入正常实现调度

#### Scenario: 评审否决冻结不可跳过
- **WHEN** 对因评审否决达上限（方向不成立）冻结的 spec 调用 skip_review_gate
- **THEN** 返回拒绝错误说明该冻结类型不支持跳过，spec 状态不变
