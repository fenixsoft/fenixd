## ADDED Requirements

### Requirement: 车道知识纪律段

拟覆盖车道（`planner-plan`、`implementer`、`code-fix`、`administrator`、`self-review`、
`arbiter`）的 `agents/<lane>.md` MUST 各含一个知识纪律段，段内 MUST 指路
`spec/knowledge/index.md` 并采用条件 MUST 语义：接任务先读 index 判断相关域，
命中相关域则 MUST 下钻该域 `domains/<域>/_domain.md` 与相关能力页后再动手；
未命中可跳过，MUST NOT 为走流程而全量阅读。文案 MUST 含存在性条件：项目尚无
`spec/knowledge/` 目录时静默跳过。分车道措辞可按车道职责微调一句话，语义不得偏离
上述框架。

#### Scenario: 实现车道下钻已蒸馏能力

- **WHEN** implementer 接到涉及已蒸馏能力（如 code-fix 车道编排）的任务
- **THEN** 其 prompt 含知识纪律段，run 转录中出现读取 `spec/knowledge/index.md`
  与相关能力页的 Read 调用，实现引用的能力页规则与当前代码行为一致

#### Scenario: 无关任务不下钻

- **WHEN** 任务与任何能力域无关
- **THEN** agent 读完 index 即继续任务，无域页/能力页阅读，无告警、无阻塞

#### Scenario: 无知识目录项目静默跳过

- **WHEN** daemon 管辖的某项目尚无 `spec/knowledge/` 目录
- **THEN** 纪律段存在性条件使 agent 静默跳过，无报错、无常驻开销、无新增配置项

### Requirement: 交互会话指路与回填预告

项目 `CLAUDE.md` MUST 含与车道同款的知识消费指路，并预告回填纪律「值得沉淀的排查/
立项结论投递 `spec/knowledge/_inbox/`」（该目录由依赖 SPEC
`add-knowledge-inbox-pipeline` 创建，文案标注目录可能尚不存在）。仓内
`skills/fenix-new/SKILL.md` 与 `skills/fenix-process/SKILL.md` MUST 分别增加
立项前先查相关知识域、查进度时对账知识域状态的指路。

#### Scenario: 立项动作携带知识查询

- **WHEN** 交互会话通过 fenix-new skill 起草新需求
- **THEN** skill 指引包含「先读 index 识别相关域并下钻能力页」步骤，
  立项 proposal 可引用既有能力页避免重复立项

### Requirement: index 域级简介增厚

`spec/knowledge/index.md` 的每个能力域行 MUST 具备能独立支撑「任务 ↔ 域」判断的
简介：2~3 句、覆盖该域主要能力面；素材取自各域 `_domain.md` 既有简介与能力清单，
不引入新事实；文件顶部盖戳行刷新为更新时刻（本地时区 `UTC+8` 形态）；域行结构与
能力数量列保持不变。目录契约页 `spec/knowledge/domains/knowledge-atlas/knowledge-atlas-directory.md`
中 index 简介的表述（「一行简介」）MUST 同步对齐增厚后形态——该页是蒸馏 run 维护
`index.md` 的契约依据，不同步则增厚会被下次蒸馏回退。

#### Scenario: 仅凭 index 可定位相关域

- **WHEN** agent 拿到「修复回归熔断分档」类任务读 index
- **THEN** 无需打开任何 `_domain.md` 即能从增厚简介定位
  `code-fix-lane` 与 `run-resilience` 为候选域，随后正确下钻
