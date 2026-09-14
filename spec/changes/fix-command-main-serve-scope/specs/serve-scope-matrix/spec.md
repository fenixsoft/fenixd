## ADDED Requirements

### Requirement: 被测实例服务路径的 scope × kind 矩阵完备

系统 SHALL 使 `verify.static_scope`（服务范围）与 `serve.kind`（服务形态）正交：四条组合 `static×main`、`static×worktree`、`command×worktree`、`command×main` 各自提供等价的契约实例语义。任一组合缺失时 MUST NOT 静默降级到 legacy 兜底链。

契约实例语义定义为：框架分配/发现被测实例端口 → 把场景 URL 全量改写（origin）到该实例（BASE_URL 注入铁律）→ 就绪探针通过后放行场景。

#### Scenario: command + main 走契约实例路径
- **WHEN** 项目契约声明 `serve.kind=command` 且配置 `verify.static_scope=main`，场景集含 web/api 场景
- **THEN** 框架以主树项目根为 cwd 启动 `serve.cmd`，对场景文件执行 origin 全量改写，探测就绪后放行场景
- **AND** MUST NOT 退回 `commands.start` 自启链路，MUST NOT 触发逐端口 `_rewrite_scenario_port`

#### Scenario: command + main 下应用自绑默认端口（未迁移契约）
- **WHEN** `serve.cmd` 未引用 `{port}`/`$FENIX_VERIFY_PORT`，被启动实例自绑应用声明的默认端口
- **THEN** 框架经进程归属发现定位该实例真实端口，场景 origin 全量改写到该端口，就绪探针通过后放行

#### Scenario: 其余三条组合行为不变
- **WHEN** 契约/配置为 `static×main`、`static×worktree` 或 `command×worktree`
- **THEN** 各组合行为与其既有实现一致（无回归）

### Requirement: legacy 兜底链不再作出无据归因

契约缺失或无效、回退 legacy 兜底链时，端口改写日志 MUST NOT 断言「planner 臆测」或其他指向场景编写者的无据归因；MUST 如实描述「场景声明端口 ≠ 框架分配端口，已改写对齐」。

#### Scenario: 无契约项目的端口改写日志
- **WHEN** 项目无有效验证契约，进入 legacy 兜底链，场景声明端口与框架启动端口不一致
- **THEN** 框架改写场景端口并记录中性的对齐说明，日志不含「planner 臆测」措辞
