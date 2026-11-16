## ADDED Requirements

### Requirement: agent 驱动通道的人类专属 choice 执行边界

全部 agent 驱动的 Administrator 处置执行通道（升级链 closed 出口、admin_monitor 直派、admin_auto_exec 自动执行；三者共用 `core/admin_choice_exec.execute_choice_for_disposition`）MUST 在调用动作执行器前复核 choice_id 是否属于 `ADMIN_CHAIN_EXCLUDED_CHOICE_IDS`。命中时 MUST 拒绝执行并返回可识别的失败结果（ok=false、skipped=true、error 含「人类拍板面专属」），MUST NOT 调用 `execute_adjudication_choice`。人工 Dashboard alert-resolve 通道 MUST 保持原有放行语义。信号在命中拒绝时 MUST NOT 被回写 handled/resolved。

#### Scenario: 直派通道拒绝 grant_env_exemption
- **WHEN** admin_monitor 直派的 disposition 携带 choice_id=grant_env_exemption，signal_type=inconclusive_loop
- **THEN** execute_choice_for_disposition 返回 ok=false、skipped=true、error 含「人类拍板面专属」，并记录 ERROR 日志；execute_adjudication_choice 未被调用；spec 的 `_env_exemptions` 不发生写入

#### Scenario: 自动执行通道同样被拦
- **WHEN** admin_auto_exec 对推荐项 grant_env_exemption 调用 execute_choice_for_disposition
- **THEN** 返回同一拒绝形态，不执行豁免动作（risk_tier 门之外的第二层防线）

#### Scenario: 链通道双层设防仍先 handoff
- **WHEN** 升级链 Admin 产出 choice_id=abandon
- **THEN** escalation_chain 的越界复核先行返回 handoff（不计失败、转 Arbiter），执行机器守卫不成为唯一防线

#### Scenario: 人工通道不受影响
- **WHEN** Dashboard 人工 alert-resolve 以 choice_id=grant_env_exemption 调用 execute_adjudication_choice
- **THEN** 动作正常执行，人类拍板语义保留，不因本变更被拦截

#### Scenario: 拒绝后信号不静默收口
- **WHEN** 直派通道命中排除集
- **THEN** disposition 记录 handoff_reason，信号保持 pending（handled/resolved 不被回写），交既有升级链/Arbiter 接管
