# Proposal: add-knowledge-atlas —— 项目知识真相源机制

## Why

`spec/archive/` 已积累 300 个归档 SPEC，远超人类阅读范畴，AI 检索同样费力。归档目录是「历史过程」与「当前事实」的混合体：想知道「定时拣选现在到底什么规则」，只能翻遍多个归档 SPEC 自行拼装（同一能力被 2-6 个 SPEC 先后修改，如 dashboard-spec-table ×6）。openspec 式的「全量平铺主 spec」也不能解决问题——几十个能力拼成一份大文档同样不可读，且丢失溯源能力。

需要一个**真相源**（knowledge atlas）：按能力域组织的、只装当前业务规则的、人类可读性优先的常驻知识层。归档 SPEC 继续承担历史职责，真相源承担「现在是什么规则」的职责，两者用溯源链接连接。

本 SPEC 建立真相源的**目录契约、蒸馏管线与 ADR 索引**；存量 300 个归档的批量回填、周期 audit 淘汰车道、Graphify 关系图集成由后续 SPEC `add-knowledge-atlas-maintenance` 承接。

## What Changes

- **新增 `spec/knowledge/` 真相源目录**：`index.md` 总目录 + `domains/<域>/<能力>.md` 能力页 + `adr/` 决策索引。能力页遵循统一契约：HTML 注释 marker（机器接口：capability 名、rev、sources 链表）+ 人类可读散文（角色一句话 / 规则 / 关键行为 / 溯源段）。
- **归档蒸馏管线**：SPEC 归档（手工 `fenix_archive.py` 与自动归档 `auto_archive_check` 两条路径）完成后，自动派发一次蒸馏 agent run（knowledge-distill 车道）：读归档 SPEC 的 `specs/` delta 与 proposal 摘要，按 ADDED/MODIFIED/REMOVED 语义重写受影响能力页（后写覆盖前写，非机械拼接），更新域清单与总目录。失败 fail-open 不阻塞归档，重试进台账。
- **ADR 索引**：蒸馏 run 同时从归档 SPEC 的 `design.md` Decisions 段抽取**跨 SPEC 影响架构走向**的决策（高门槛，宁缺勿滥），生成 `adr/ADR-NNN-*.md`（context/decision/consequences 三段）；与既有 ADR 冲突时旧 ADR 头部标 `Superseded by:` 链接、正文不改写。
- **蒸馏收尾校验**（确定性脚本，非 LLM）：marker 格式、溯源链接指向的归档目录存在性、单页行数硬顶检查；校验通过后自动提交（沿用 archive_commit 模式）。
- **Dashboard「项目知识」页签**：项目页 Tabs 中、「会话接入」之前新增页签，按需拉取渲染 `spec/knowledge/index.md`（Markdown 渲染）、域/能力页浏览、ADR 索引列表；graph.html 渲染位预留（本 SPEC 生成图，后续 SPEC 接入）。
- **配置项**：`knowledge.enabled`（默认 true）与相关开关入 `config.template.yaml` + Dashboard 设置页（新增配置项必须带 Dashboard 界面）。

## Capabilities

### 新能力
- `knowledge-atlas-directory`：真相源目录契约与能力页格式（marker 契约、溯源链接、行数硬顶）
- `knowledge-distill-pipeline`：归档触发蒸馏管线（双入口挂载、ADDED/MODIFIED/REMOVED 合并语义、fail-open、收尾校验与自动提交）
- `knowledge-adr-index`：ADR 抽取判据、三段式格式、supersede 链纪律、不可变性
- `knowledge-dashboard-tab`：项目知识页签（按需加载、Markdown/ADR/graph 占位渲染）
- `knowledge-config`：配置项与设置页集成

## Impact

- **新增文件**：`core/knowledge.py`（蒸馏管线核心）、`core/dashboard/routes/knowledge_routes.py`（API）、`core/dashboard/static/src/pages/projects/components/KnowledgeTab.tsx`（页签）、`spec/knowledge/` 初始骨架（index.md + 域目录由首个蒸馏 run 产出，本 SPEC 附种子空目录与 README）
- **修改文件**：`.fenix/bin/fenix_archive.py`（归档后挂蒸馏触发）、`core/dashboard/data/spec_archive.py`（auto_archive_check 同样触发）、`core/dashboard/static/src/pages/projects/list.tsx`（新增页签）、`core/dashboard/server.py`（路由 Mixin 注册）、`core/config.py` + `config.template.yaml`（配置项）、Dashboard 设置页
- **不修改**：归档目录本身的内容与移动逻辑（蒸馏只读归档）；fenix-archive skill 的交互流程（蒸馏对 skill 透明）
- **风险**：蒸馏 agent run 的输出质量决定真相源可读性——管线要求「散文重写」而非 delta 拼接，收尾校验拦截格式违规但无法校验语义质量（与 blueprint-index 的 honest boundary 一致：digest 是人审内容）；daemon 重启后需重启生效（后端约定）
