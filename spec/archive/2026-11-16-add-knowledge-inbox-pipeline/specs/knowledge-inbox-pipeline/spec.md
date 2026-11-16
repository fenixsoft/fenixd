## ADDED Requirements

### Requirement: 候选区投递与扫描豁免

`spec/knowledge/_inbox/` 为交互会话投递候选知识的自由格式区（markdown，含背景/
结论/证据段即可，MUST NOT 要求能力页契约——marker/150 行/溯源段均不适用），
目录含 `README.md` 说明投递契约与失败滞留语义。`validate_knowledge` 与
knowledge_audit 的扫描范围 MUST 显式排除 `_inbox/**`，并 MUST 有测试钉死该豁免
（防未来扫描范围变更误伤）。

#### Scenario: 烂格式候选不触发契约违规

- **WHEN** `_inbox/` 存在一份不含 marker、超 150 行、含失效链接的候选 markdown
- **THEN** validate_knowledge 与 audit 轮均不报该文件的契约违规，audit 仅按积压
  提醒规则计数

### Requirement: piggyback 折叠管线

distill 车道每轮（现触发点：SPEC push 终态）MUST 在处理当轮 SPEC 蒸馏之前先消化
`_inbox/` 存量条目：按能力页契约将候选内容折叠进相关能力页（或新建能力页），
超 150 行硬顶 MUST 拆页（主从分片互链）；折叠落盘前 MUST 跑实时
`validate_knowledge`，失败不得落盘、条目滞留原地待下轮重试；折叠成功后条目移入
`spec/knowledge/_inbox/done/` 永久保留，能力页 marker sources 指向
`_inbox/done/<文件名>`。`_inbox` 非空 MUST NOT 构成独立派发条件
（piggyback-only，无 fold-only run 形态）。

#### Scenario: 候选条目折叠闭环

- **WHEN** `_inbox/` 有 1 条合法候选且到达下一个 distill 轮
- **THEN** 轮结束后相关能力页规则段出现折叠内容、marker sources 含
  `_inbox/done/` 路径且机器校验通过、候选条目已移 `done/`、`log.md` 追加 fold 行

#### Scenario: 超顶拆页

- **WHEN** 折叠将使目标能力页超 150 行硬顶
- **THEN** distill 拆页（主从分片互链）而非放行超顶文件

#### Scenario: 校验失败不落盘

- **WHEN** 折叠产出的能力页内容未通过实时 `validate_knowledge`
- **THEN** 该条不落盘、候选条目滞留 `_inbox/` 原地，`log.md` 记录失败，下轮重试

#### Scenario: 无 SPEC 批次时不派发

- **WHEN** `_inbox/` 有积压但无任何待蒸 SPEC 批次
- **THEN** 不派发任何 run（无 fold-only 轮），积压滞留由提醒机制兜底可见性

### Requirement: marker sources 契约扩展

能力页 marker 的 sources 机器校验 MUST 在既有 `spec/changes/<SPEC名>` 目录形态
之外放行 `spec/knowledge/_inbox/done/` 前缀：该前缀按 file 形态校验文件真实存在；
其余前缀校验行为不变。

#### Scenario: done 路径机器校验放行

- **WHEN** 能力页 marker sources 含 `spec/knowledge/_inbox/done/2026-11-03-foo.md`
  且该文件存在
- **THEN** validate_knowledge 通过；同场景文件被删除时校验失败

### Requirement: log.md 编年账

`spec/knowledge/log.md` 为追加式编年账，行前缀
`## [YYYY-MM-DD HH:MM UTC+8] <操作> | <主题>`（操作 ∈ distill/fold/backfill/lint），
时间取本地时区并显式标注 `UTC+8`；distill/audit/backfill 轮收尾 MUST 追加对应行；
并发追加 MUST NOT 丢行（文件锁或单写者纪律）。

#### Scenario: 轮次收尾留痕

- **WHEN** 一轮 distill（含折叠）完成
- **THEN** `log.md` 依次出现 fold 行（如有折叠）与 distill 行，时间戳为本地
  `UTC+8` 形态，unix 工具可按日期前缀 grep

### Requirement: 归档改写豁免

`rewrite_source_links_to_archive` MUST 显式排除 `spec/knowledge/log.md` 与
`spec/knowledge/_inbox/**`（含 `done/`），其余 `spec/knowledge/` 文件的既有改写
行为不变；MUST 有测试钉死豁免。

#### Scenario: 归档迁出逐字节冻结候选原文

- **WHEN** SPEC 归档迁出触发 `rewrite_source_links_to_archive`，且 `_inbox/done/`
  候选原文含 `spec/changes/<已归档SPEC>` 字符串
- **THEN** 能力页/ADR 照常改写，候选原文与 `log.md` 逐字节不变

### Requirement: 积压提醒

audit 周期轮 MUST 检测 `_inbox/` 积压：积压 ≥10 条或最老条目滞留 ≥7 天（条目
mtime 起算）时落 `log.md` lint 提醒行，随周期轮幂等去重；提醒 MUST NOT 走
AdminStore 人工告警；dashboard KnowledgeTab MUST 展示 `_inbox/` 积压计数
（含最老条目滞留天数）。

#### Scenario: 阈值触发仅 log 与面板

- **WHEN** `_inbox/` 积压达 10 条
- **THEN** `log.md` 出现 lint 提醒行、KnowledgeTab 计数更新、无任何
  AdminStore 人工告警产生；同轮不重复落行

### Requirement: 知识车道 prompt 归位

`core/knowledge_prompts/{distill,audit,backfill,prehistoric}.md` MUST 迁移为
`agents/knowledge-{distill,audit,backfill,prehistoric}.md`，知识车道加载点同步
改造且「`agents/` 是 prompt 唯一真相」不破例；迁移后 `core/knowledge_prompts/`
目录 MUST NOT 存在，全仓 MUST NOT 有对旧路径的残留引用；distill prompt 迁移时
一并包含折叠管线段。

#### Scenario: 新路径加载成功且旧路径消失

- **WHEN** daemon 以新代码启动并派发知识车道
- **THEN** prompt 从 `agents/knowledge-*.md` 加载成功，`core/knowledge_prompts/`
  不存在，全仓 grep 无该路径残留引用
