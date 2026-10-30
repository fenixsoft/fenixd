# 验证证据分级留存

<!-- knowledge: capability=verify-evidence-tiered-retention rev=1 sources=spec/archive/2026-10-30-evo-verify-evidence-tiered-retention -->

验证证据（截图、录屏、日志等验证产物）按体积分级留存：文本与小文件直接入库，超阈值二进制以哈希旁证与登记信息替代，防止验证证据把仓库体积撑爆。

## 现行规则

- 分级阈值单源在契约：verify 契约模板提供可选声明 `evidence_retention.max_binary_bytes`（缺省 10485760，即 10MB），这是证据入库分级的唯一阈值来源；契约解析结果暴露给落位指引渲染，指引中的阈值随契约声明联动。
- 阈值解析静默容错：契约缺失 `evidence_retention` 段、或声明值为非法值（负数、非整数、bool），解析一律静默回退缺省 10MB——不报错、不阻断契约加载（仿 `_positive_int_or_default` 回退范式）；合法正整数声明值直接生效。
- 落位指引携带分级条款：prompt 注入的证据落位指引恒包含分级留存规则——文本/JSON/哈希/小日志类证据直接入 git；超过契约阈值的二进制证据不得入 git，改落 sha256 sidecar、复现命令与存放路径登记文件。契约声明自定义阈值与走缺省阈值两种形态下条款均渲染，仅阈值数值不同。
- 软约束定位：分级靠契约字段声明 + prompt 指引实现，框架不设执行闸门拦截证据入库（框架自身从不执行 `git add` 证据，无拦截环节）；已跟踪证据的体积普查观测归 stray_wip 信号侧，不进落位契约。超阈值二进制本体对逐字节一致性论证无增量价值——同目录 sha256 sidecar 与哈希旁证在场时，本体入库不提供额外证明力，此即分级以旁证替代本体的依据。

## 溯源

- 2026-10-30 evo-verify-evidence-tiered-retention（spec/archive/2026-10-30-evo-verify-evidence-tiered-retention） — 新建本能力：契约分级字段 `evidence_retention.max_binary_bytes` 三态解析与落位指引分级条款；此前验证证据无体积分级约束，agent 契约外手工提交使项目根 verify-evidence/ 累计入库 67 文件约 690MB
