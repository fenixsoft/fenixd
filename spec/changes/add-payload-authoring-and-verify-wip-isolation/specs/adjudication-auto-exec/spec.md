# Spec Delta: adjudication-auto-exec

## MODIFIED Requirements

### Requirement: 可逆推荐项到点自动执行

系统 MUST 对满足全部自动执行判据的 pending 升级告警，在其 grace 窗（缺省 30 分钟，自**推荐可用时刻**起算——即告警 `arbiter_upgrade.upgraded_at`，无 upgrade 痕时回退告警 `created`；单源 core/config.py）结束时仍处于未处理状态时，自动执行推荐 choice 并落处置留痕（actor=auto-policy）。自动执行判据 MUST 全部满足：①该告警关联的 arbiter 完整调查 ≥1 次且存在明确推荐 choice（推荐 choice 由告警 `choices[]` 注册 id 对 recommended_action 文本的**正向提及**机械解析：否定语境「不推荐/不选/勿选/不作为」就近修饰的不计正向；唯一正向命中方视为明确，零或多义命中一律判不明确、跳过等人工）；②推荐 choice 的 risk_tier 为 `reversible-experiment`；③同 SPEC 无共存更高风险档 pending 告警；④本 SPEC 连续自动执行计数低于上限（缺省 2）。任一判据不满足 MUST 跳过本轮并记录日志，不得部分执行。

**载荷门跳过闩锁（本变更新增）**：载荷门（推荐 choice 经注册表解析 `requires_payload=True` 且自动通道无载荷，core/admin_auto_exec.py:403-408）跳过时 MUST 闩锁：首次跳过即把 `skip_reason="requires_payload"`（附推荐 choice id）写入告警记录的 auto_exec 投影字段；后续监视 tick 命中闩锁时 MUST 短路——不再重复走完整判据链、不再重复输出 INFO 级跳过日志（DEBUG 级可留）。闩锁 MUST 在以下任一事件时解除并恢复正常评估：告警状态变化（被处置/升级/消除）、载荷草稿落位或移除（见 admin-payload-drafting 能力）、告警记录被编辑。闩锁 MUST NOT 影响人工处置通道的可达性，也 MUST NOT 改变既有四判据中任何判据的判定结果。

#### Scenario: 到点自动执行可逆推荐
- **WHEN** 一条 judge_rerun_cap 升级告警的 arbiter 推荐已落账超 30 分钟（grace 窗自推荐可用时刻起算已满），arbiter 已完成完整调查并推荐 manual_fixed_reverify（risk_tier=reversible-experiment），同 SPEC 无更高档 pending 告警，连续自动执行计数为 0
- **THEN** 策略引擎经既有 choice 执行机器执行该 choice，处置留痕 actor=auto-policy，告警转为已处理，verify 车道在秒级内重新派发

#### Scenario: 判据缺失跳过并留日志
- **WHEN** 一条 pending 告警的推荐 choice risk_tier=terminal，或无 arbiter 完整调查记录
- **THEN** 策略引擎不执行任何动作，跳过原因记录于日志，告警维持 pending 等人工

#### Scenario: 推荐歧义跳过
- **WHEN** 一条 pending 告警的 recommended_action 文本对多个 choices[] 注册 id 均构成正向提及，或对任何 id 均无正向提及
- **THEN** 策略引擎判推荐不明确，不执行任何动作，跳过原因记录于日志，告警维持 pending 等人工

#### Scenario: 异步升级件否决窗完整
- **WHEN** 告警创建约 1.5 小时后 arbiter 调查完成、推荐经 arbiter_upgrade 落账（upgraded_at 晚于 created）
- **THEN** grace 窗自 upgraded_at 起算，引擎在 upgraded_at + 30 分钟前 MUST NOT 执行该告警，人工在该窗内否决或改选先到先得

#### Scenario: 人工先到先得
- **WHEN** grace 窗内人工经 alert-resolve 处理了该告警（任一 choice 或标记已处理）
- **THEN** 窗口到期时引擎重读已处理状态后跳过，不产生重复处置留痕

#### Scenario: 载荷门首跳闩锁并投影 skip_reason
- **WHEN** 一条 pending 告警的推荐 choice 为 revise_scenario_reverify（requires_payload=True），grace 窗已满且其余判据均通过，载荷门首次命中
- **THEN** 引擎跳过执行，告警记录 auto_exec 投影写入 skip_reason="requires_payload" 与推荐 choice id，INFO 日志记录一次；后续监视 tick 再遇同告警时 MUST NOT 重复输出 INFO 跳过日志、MUST NOT 重复完整评估（DEBUG 级短路痕迹可留）

#### Scenario: 闩锁后草稿落位解除重评
- **WHEN** 闩锁成立期间，载荷起草 run 将该告警的草稿落位（告警获得 draft 指针）
- **THEN** 闩锁解除，引擎重评该告警——自动通道对 requires_payload 选项仍 MUST NOT 直接执行（保守原则不变），但投影与徽标反映"草稿待人工批准"状态

#### Scenario: 闩锁不影响人工路径
- **WHEN** 闩锁成立期间用户在面板打开该告警的选择题
- **THEN** 选项下拉、载荷编辑器（adjudication-ui 能力）与执行按钮全部照常可达可提交，人工提交经既有 alert-resolve 通道正常执行
