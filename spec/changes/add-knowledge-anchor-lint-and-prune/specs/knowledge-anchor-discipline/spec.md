## ADDED Requirements

### Requirement: 代码锚点段契约

能力页可含一个 `## 代码锚点` 段（置于 `## 规则` 之后、`## 溯源` 之前），按四类
固定标签承载实现定位：**主实现**（文件路径）/ **单源符号**（模块内常量、函数、
类的 `路径:符号` 形态）/ **消费方**（谁调用/挂载）/ **守卫测试**（钉住本行为
的测试文件）。粒度纪律：一律文件级路径 + 符号名，MUST NOT 写行号（必腐）；
段内路径 MUST 指向盘上真实存在的仓库内文件。新建能力页（蒸馏折叠与回填车道
产出）MUST 带代码锚点段；存量页按触达增量补，不做全量回填批次。段为可选——
纯契约/纯流程类能力（无实现载体）允许缺省并在段位写一行「无独立实现载体」。

#### Scenario: 新折叠页带锚点

- **WHEN** 蒸馏/回填车道新建一个有实现载体的能力页
- **THEN** 该页含 `## 代码锚点` 段且段内路径均真实存在，锚点存活检查零报告

#### Scenario: 行号锚点违例

- **WHEN** 某能力页代码锚点段写 `core/knowledge.py:179` 形态的行号锚点
- **THEN** 体检报告记格式违规（行号必腐），处置走定向转写改写为文件级形态

### Requirement: 退役即删不墓碑

能力主体从产品删除时，其能力页 MUST 从真相源**直接删除**（MUST NOT 保留页面
加退役注记的墓碑形态），同批动作 MUST 含：`_domain.md` 表行移除、表尾追加一行
退役注记（退役日期 + 指向 spec/archive 或 git 历史的指针）、相关 ADR 状态翻转、
`index.md` 能力数量更新、`log.md` 登记。删除前 MUST grep 该能力页 capability 名
在其余知识页/ADR/提示词中的引用并收口，防悬空交叉引用。

#### Scenario: 页面退役全链收口

- **WHEN** 某产品能力（含其代码）被整体删除
- **THEN** 真相源中不存在该能力的独立页；域表尾有对应退役注记行；全库 grep
  该 capability 名零残留（历史溯源行的纯文本提及不算残留）

### Requirement: 退役 runbook 成页

knowledge-atlas 域新增能力页 `knowledge-retirement-runbook`：退役一个能力的
完整 checklist（删路由/代码与死代码清理、镜像同步指令收口、知识页删除、域表
收口与注记、ADR 翻转、index 计数、log 登记、复核 grep），后续退役动作照单执行。

#### Scenario: runbook 可独立执行

- **WHEN** agent 接到「退役能力 X」任务并读该 runbook
- **THEN** checklist 覆盖上表全部动作且无需会话内重新发明步骤

### Requirement: 世代前缀与死引用禁令

新能力页命名 MUST NOT 使用世代前缀（`v2-`/`v3-` 式），一律功能名；能力页规则段
MUST NOT 携带指向已删除文件/域的现行口径引用（「镜像 X 两处同改」类同步指令的
主语被删除时，该指令 MUST 同批收口为历史出处口径）。

#### Scenario: 世代前缀拦截

- **WHEN** 蒸馏产出新能力页 `v4-xxx-page.md`
- **THEN** 校验/复核判命名违规，改功能名（如 `xxx-page.md`）

### Requirement: ADR retired 状态词汇

ADR 状态词汇表扩展为 `accepted | superseded | retired`：retired 表示裁定主体已
从产品退役且无取代裁定。合法 retired 条目 = 头部 `status: retired` + 追加
`Retired: <YYYY-MM-DD> <一句话>` 注记行，三段正文逐字保持原样（改写纪律同
superseded）；`adr/index.md` 状态列 MUST 与条目头同步。校验器对 retired 的
校验行为：缺 `Retired:` 行记违规；正文改写检测与 superseded 同口径；
`accepted`/`superseded` 既有校验行为零变化。

#### Scenario: retired 条目合规放行

- **WHEN** ADR 条目头部为 `status: retired` 且含 `Retired: 2026-11-08 主体退役` 行、
  三段正文与 HEAD 逐字一致
- **THEN** validate_knowledge 零违规，adr/index.md 该行状态为 retired

#### Scenario: retired 缺注记行拦截

- **WHEN** 条目 `status: retired` 但缺 `Retired:` 行
- **THEN** validate_knowledge 报违规，提示补注记行

#### Scenario: 既有二值行为不回归

- **WHEN** 存量 accepted 条目（无 Retired 行）与合法 superseded 条目（含
  Superseded by 行）分别接受校验
- **THEN** 判定结果与词汇扩展前完全一致
