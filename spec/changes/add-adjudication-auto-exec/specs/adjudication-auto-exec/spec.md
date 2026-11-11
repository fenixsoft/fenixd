## ADDED Requirements

### Requirement: 可逆推荐项到点自动执行

系统 MUST 对满足全部自动执行判据的 pending 升级告警，在其 grace 窗（缺省 30 分钟，自**推荐可用时刻**起算——即告警 `arbiter_upgrade.upgraded_at`，无 upgrade 痕时回退告警 `created`；单源 core/config.py）结束时仍处于未处理状态时，自动执行推荐 choice 并落处置留痕（actor=auto-policy）。自动执行判据 MUST 全部满足：①该告警关联的 arbiter 完整调查 ≥1 次且存在明确推荐 choice（推荐 choice 由告警 `choices[]` 注册 id 对 recommended_action 文本的**正向提及**机械解析：否定语境「不推荐/不选/勿选/不作为」就近修饰的不计正向；唯一正向命中方视为明确，零或多义命中一律判不明确、跳过等人工）；②推荐 choice 的 risk_tier 为 `reversible-experiment`；③同 SPEC 无共存更高风险档 pending 告警；④本 SPEC 连续自动执行计数低于上限（缺省 2）。任一判据不满足 MUST 跳过本轮并记录日志，不得部分执行。

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

### Requirement: 自动执行与人工处置同构留痕

自动执行 MUST 复用既有 choice 执行机器（execute_choice_for_disposition 同源），留痕形态与人工点击同构：disposition 记录含 choice_id、执行结果、actor=auto-policy 与触发告警 id；dashboard 告警列表 MUST 将自动执行记录以独立可识别标注展示（非静默混入人工记录）。禁止为自动执行复制第四份执行逻辑。

#### Scenario: 留痕与人工同构可审计
- **WHEN** 引擎自动执行 manual_fixed_reverify 成功
- **THEN** 处置留痕结构与人工 alert-resolve 执行同一 choice 的留痕字段一致，仅 actor 与触发告警 id 不同，dashboard 展示自动执行标注

#### Scenario: 执行复用单机器
- **WHEN** 注册表某 choice 的执行逻辑变更（如新增 payload 校验）
- **THEN** 自动执行路径与人工路径行为一致变更，无需分别修改两处实现

### Requirement: 连续自动执行上限与降级

同一 SPEC 的连续自动执行计数（从处置留痕按 actor=auto-policy 派生，不新增状态文件）达到上限（缺省 2，config 单源可调）时，系统 MUST 停止自动执行并转纯人工等待。config 开关 `auto_exec.enabled=false` 时策略引擎 MUST 完全停用。策略引擎任何异常 MUST 单条捕获记录日志并跳过本轮，不得阻塞验证、派发等其他车道。

#### Scenario: 连续超限强制人工
- **WHEN** 某 SPEC 已连续 2 次自动执行且重验后再次冻结产生新 pending 告警
- **THEN** 引擎不自动执行，告警等待人工，日志记录连续超限原因

#### Scenario: 开关降级与异常隔离
- **WHEN** auto_exec.enabled=false，或引擎扫描中某告警判定抛出异常
- **THEN** 前者引擎完全停用不产生任何自动处置；后者该告警本轮跳过、其余告警判定不受影响、其他车道运行无感知

### Requirement: human-only 档告警老化升级

risk_tier 为 `state-advance` 或 `terminal` 的 pending 告警 MUST NOT 被自动执行；引擎扫描时对 pending 超过老化阈值（缺省 2h/6h 两档）的此类告警 MUST 写升级活动记录供 dashboard 高可见度展示。老化升级只做可见性提升，不改变告警处置语义。

#### Scenario: 不可逆档持续可见不自动动
- **WHEN** 一条推荐 force_advance（risk_tier=state-advance）的告警 pending 超 2 小时
- **THEN** 引擎不执行该 choice，写一条老化升级活动记录，dashboard 呈现升级标注，告警仍等待人工
