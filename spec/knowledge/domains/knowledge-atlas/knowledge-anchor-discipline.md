# 能力页代码锚点与退役纪律

<!-- knowledge: capability=knowledge-anchor-discipline rev=1
     sources=spec/changes/add-knowledge-anchor-lint-and-prune -->

能力页「写什么/不写什么」的提效纪律全集：代码锚点段让 agent 读页即达实现定位（替代试错式 grep），退役与命名纪律防真相源堆积误导检索。段的契约形态细则（段位、四类标签定义、150 行硬顶）见真相源目录契约能力页，本页装纪律与处置语义。

## 规则

- 代码锚点段按四类固定标签承载实现定位：主实现（文件路径）/ 单源符号（`路径:符号` 形态）/ 消费方（谁调用/挂载）/ 守卫测试（钉住本行为的测试文件）。粒度一律文件级路径 + 符号名，MUST NOT 写行号（行号必腐）；段内路径 MUST 指向盘上真实存在的仓库内文件。
- 覆盖面：新建能力页（蒸馏折叠与回填车道产出）MUST 带锚点段；存量页按触达增量补，不做全量回填批次；纯契约/流程类能力（无实现载体）允许缺省，段位写一行「无独立实现载体」。
- 锚点存活检查只扫能力页 `## 代码锚点` 段内的路径 token（`路径:<纯数字>` 行号尾形态报「行号必腐」格式违规，与悬空并列两类发现）；`spec/archive/`、`spec/knowledge/_inbox/`、`node_modules/` 前缀豁免——历史/候选区/第三方不受锚点纪律约束，不做全页启发式扫描。
- 消费面：悬空与格式违规进 audit 体检报告病灶⑥「待人工/定向转写」档计数与明细。两道纪律边界：不并入 `validate_knowledge` 硬门（折叠前置校验跑全树，一处陈旧锚点会把内容问题放大成全树折叠管线阻塞）；不机械自删悬空锚点行（修复需语义判断定位新位置，脚本删除丢信息）。
- 退役即删不墓碑：能力主体从产品删除时，其能力页从真相源直接删除（主从分片全删，MUST NOT 保留页面加退役注记的墓碑形态——历史由 git 历史 + `spec/archive/` 承载）；唯一墓碑 = 所在域 `_domain.md` 表尾一行退役注记。先前置盘点 grep 引用面，再按八步 checklist（代码路由删除→镜像指令收口→删页→域表收口注记→ADR 翻 retired→index 计数→log 登记→复核 grep）照 [能力退役 runbook](knowledge-retirement-runbook.md)（`knowledge-retirement-runbook`）能力页同批执行。
- ADR 翻 retired：accepted 条目头部翻 `status: retired` 并追加 `Retired: <YYYY-MM-DD> <一句话>` 注记行，三段正文逐字不动；retired 语义 = 裁定主体已退役且无取代裁定（有后继裁定时走 supersede 而非 retired）。状态词汇三值校验与索引一致性纪律见 [ADR 决策索引](knowledge-adr-index.md)（`knowledge-adr-index`）能力页。
- 新能力页命名禁世代前缀：MUST NOT 使用 `v2-`/`v3-` 式世代前缀，一律功能名；命名无机械校验面，由蒸馏车道复核与 spec 评审判定拦截。
- 死引用禁令：能力页规则段 MUST NOT 携带指向已删除文件/域的现行口径引用；「镜像 X 两处同改」类同步指令的主语被删除时，该指令 MUST 同批收口为历史出处口径或移除。

## 代码锚点

- 主实现：`core/knowledge.py`（锚点存活检查实现）
- 单源符号：`core/knowledge.py:check_anchor_references`
- 消费方：`core/knowledge_audit.py`（体检报告病灶⑥接线）
- 守卫测试：`tests/test_knowledge_anchor_check.py`

## 溯源

- 2026-11-08 add-knowledge-anchor-lint-and-prune（spec/changes/add-knowledge-anchor-lint-and-prune/） — 新建本能力页：锚点段四类标签纪律与存活检查软档语义（病灶⑥消费、不进折叠硬门、不机械自删）、退役即删不墓碑语义、世代前缀与死引用禁令
