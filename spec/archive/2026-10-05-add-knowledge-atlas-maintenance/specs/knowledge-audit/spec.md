## ADDED Requirements

### Requirement: 周期 audit 体检

框架 SHALL 提供真相源周期 audit 车道：每日一次（自然日语义，对齐自省调度先例）对 `spec/knowledge/` 全量体检，检测五类病灶：①同页或跨页规则矛盾（同一事实两处陈述不一致）；②溯源链接悬空（指向不存在的归档目录）；③跨页重复规则（同一规则在多个能力页重复陈述）；④超 150 行硬顶页；⑤ADR 病灶（supersede 链断裂、accepted 正文被改动、index 状态与条目头不一致）。`knowledge.audit_enabled` 为 false 时 SHALL 跳过。

#### Scenario: 每日体检照常运行

- **WHEN** daemon 运行跨自然日且 `knowledge.audit_enabled` 为 true
- **THEN** audit 车道当日执行一次全量体检（真相源无病灶时产出「通过」报告，不产生修复提交）

#### Scenario: 禁用时静默跳过

- **WHEN** `knowledge.audit_enabled` 为 false
- **THEN** audit 车道不派发，无任何告警或日志噪音

### Requirement: 分级处置（机械自修、语义转写）

audit 发现 SHALL 分两级处置：**机械项**（悬空溯源行删除、格式违规、行数硬顶超标报告）由确定性脚本自动修复并 pathspec 限定提交（commit 形如 `[fenix] knowledge: audit fix <摘要>`）；**语义项**（矛盾、重复）MUST NOT 由脚本直接改写，SHALL 转定向蒸馏 run 读两处冲突上下文后重写（复用增量蒸馏契约），重写失败登记 todo.md 供人工/后续处置。体检结果 SHALL 汇总为体检报告（过/修/转写/待人工四计数与明细）。

#### Scenario: 悬空链接自动修复

- **WHEN** audit 检测到某能力页溯源行指向已不存在的归档目录
- **THEN** 该行被脚本删除并自动提交，体检报告计入「修」

#### Scenario: 规则矛盾转写而非脚本改写

- **WHEN** audit 检测到两个能力页对同一机制陈述矛盾
- **THEN** 派发定向蒸馏 run 重写受影响页（不脚本改写）；成功后自动提交并计入「转写」，失败登记 todo.md 计入「待人工」

### Requirement: audit 不膨胀真相源

audit 车道 SHALL 以「真相源页面数与总行数不随时间单调膨胀」为维护目标：体检报告 SHALL 包含真相源规模趋势（页数/行数相对上次体检的变化），连续增长超阈值（实现裁量建议 +10%）时在报告中显式标记「需精简」并给出候选页清单（按行数排序），供下一轮蒸馏/audit 处置。

#### Scenario: 膨胀趋势被标记

- **WHEN** 真相源总行数相对上次体检增长超过 +10%
- **THEN** 体检报告显式标记「需精简」并列出候选页清单
