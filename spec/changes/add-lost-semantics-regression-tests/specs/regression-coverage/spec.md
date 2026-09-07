# regression-coverage 变更

## ADDED Requirements

### Requirement: replan 循环上限退回保护

PMEngine 对 planner 产物不合格触发的 replan/重派循环 MUST 有可验证的上限行为：达到上限后不得无限重派，最终状态可观测（退回 blocked/人工升级/显式终止，以当前实现为准）。

#### Scenario: replan 达到上限后停止重派
- **WHEN** planner 连续产出不合格结果且循环计数达到实现定义的上限
- **THEN** 引擎不再发起新一轮 planner run，最终状态为上限退回形态（blocked/升级/终止之一），且该状态转换有日志或状态记录可断言

#### Scenario: replan 计数在成功后不残留
- **WHEN** 某轮 replan 后 planner 产出合格结果
- **THEN** 循环计数归零（或等价的不再累计语义），后续独立失败从零起算

### Requirement: provider 熔断打开时 verifier 状态保持

provider 熔断（ProviderCircuit open）期间 verifier run 的失败 MUST 被归类为基础设施失败：spec 状态保持原状（testing/在跑态），MUST NOT 被判为 bug-found、MUST NOT 递增 `_verify_fail_rounds`。

#### Scenario: 熔断打开时 verifier 失败不误判 bug-found
- **WHEN** ProviderCircuit 对当前 provider 处于 open 状态，verifier run 因此失败（异常/非零退出）
- **THEN** spec 状态保持不变（不发生 →bug-found 迁移），`_verify_fail_rounds` 不递增，失败按基础设施口径记录（告警/日志可断言）

### Requirement: 验证失败形态归一与轮次计数

verification 层 MUST 把验证失败的多种形态（verifier run 异常 / verdict bug-found / 结果文件缺失或畸形）归一到统一失败信号，且各形态均正确递增 `_verify_fail_rounds`。

#### Scenario: 各失败形态统一递增失败轮次
- **WHEN** 分别注入「verifier run 异常」「verdict bug-found」「结果文件畸形」三种失败形态
- **THEN** 三种形态都产生统一的失败信号（bug-found 语义的打回/计数路径），`_verify_fail_rounds` 各自 +1，打回注入的「验证修复」任务段语义一致

#### Scenario: 验证通过时失败轮次归零
- **WHEN** 任一失败后下一轮验证通过（verified）
- **THEN** `_verify_fail_rounds` 归零

### Requirement: 截图时机门禁

verify_engine 的截图产物 MUST 与断言执行绑定：断言未执行（浏览器未到达断言阶段/场景被跳过/前置失败）时 MUST NOT 产生截图文件或截图事件。

#### Scenario: 断言未执行不出图
- **WHEN** 场景在到达断言阶段前失败（页面加载失败/前置步骤异常/场景被跳过）
- **THEN** 不产生该场景的截图文件，验证产物中的截图清单不含该场景

#### Scenario: 断言执行后截图可归因
- **WHEN** 场景断言执行并失败
- **THEN** 产生的截图能与该场景/断言关联（文件名或元数据含场景标识），供裁决证据链使用
