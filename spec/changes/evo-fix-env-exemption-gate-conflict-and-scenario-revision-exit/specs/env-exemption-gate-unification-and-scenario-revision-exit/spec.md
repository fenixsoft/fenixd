## ADDED Requirements

### Requirement: 跨轮 env 豁免的统一数据源

env 豁免以「场景 id+归一化失败签名」为键持久化到 spec 级 STATE 字段（带时效锚点）；升级握手与白化门禁（verdict_check）消费同一数据源：门禁校验命中有效豁免时，该项不计入 whitewash_violations；豁免在场景定义变更或时效过期时失效；0-pass 不变量与 fail-closed 语义保持。

#### Scenario: 第二轮同因失败不再升级

- **WHEN** 同一场景以同一失败签名再次触发 verify_env_blocked，且有效豁免在
- **THEN** 白化门禁与升级握手均认可豁免，不派发新升级

#### Scenario: 场景定义变更使豁免失效

- **WHEN** 该场景的定义文件被修订
- **THEN** 既有豁免失效，后续失败重新走裁决

### Requirement: 场景修订重验出口

adjudication choices 提供 revise_scenario_reverify 执行器：凭 admin 诊断结论修订场景定义文件（仅限场景文件与夹具供给层，拒绝产品代码路径），修订后经规划车道出修订场景并重验；重验前从冻结集合摘除该 spec；修订次数有上限（默认 2），超限转人工。

#### Scenario: 场景不可行走修订而非冻结

- **WHEN** env 类失败经 admin 诊断确认场景按设计不可行
- **THEN** 裁决可选修订场景定义并重验，spec 不被冻结

#### Scenario: 修订越权被拒

- **WHEN** 修订请求涉及产品代码路径
- **THEN** 执行器拒绝该修订，维持既有升级路径

### Requirement: env 归因证据要求

env 归因结论须附送帧与解码两段证据引用；证据缺失时裁决结论降级为 inconclusive 而非 env。

#### Scenario: 单句归因被降级

- **WHEN** 裁决报告仅以一句现象描述归因 env 且无两段证据
- **THEN** 该结论按 inconclusive 处理，不触发 env 豁免/升级语义