# Proposal: add-knowledge-atlas-maintenance —— 知识真相源存量回填与持续维护

## Why

`add-knowledge-atlas`（前置 SPEC）建立了真相源机制：目录契约、归档触发的蒸馏管线、ADR 索引、项目知识页签。但该 SPEC 上线时真相源是空的——存量 300 个归档 SPEC 不会自动回流（蒸馏管线只挂在「归档动作」上，已归档的不会再归档一次），且真相源缺少持续的淘汰与纠错机制，也不具备用户要求的关系图能力。

本 SPEC 补齐三块：**存量回填**（300 个归档按域分批蒸馏，一次性）、**audit 淘汰车道**（周期检测矛盾/悬空/重复，持续防真相源腐烂与膨胀）、**Graphify 关系图集成**（低频自动生成 `graph/`，点亮前置 SPEC 预留的前端渲染位）。

依赖：`add-knowledge-atlas` 已合并（复用其 `core/knowledge.py` 校验器、蒸馏提示词、`KnowledgeTab` 渲染位与 `knowledge.enabled` 配置）。

## What Changes

- **存量回填批处理车道**：遍历 `spec/archive/` 全部归档，按域聚类分批（agent 自动聚类定域骨架后逐批归位蒸馏），批间断点续跑（进度落 `.fenix/` 运行时），每批经既有 `validate_knowledge` 校验后 pathspec 限定提交。批处理可中断重入，进度台账记录每归档的回填状态（pending/distilled/failed）。
- **周期 audit 淘汰车道**：低频（每日一次，对齐自省调度自然日模式）对真相源全量体检：同域/跨页规则矛盾、溯源链接悬空、跨页重复规则、超 150 行硬顶、ADR supersede 链断裂。机械可修项（悬空行、格式违规）自动修复提交；语义问题（矛盾、重复）转蒸馏 run 定向重写，重写失败登记 todo.md。audit 产出体检报告（过不过、修了什么）。
- **Graphify 关系图集成**：每日低频对 `spec/knowledge/` 运行 Graphify 生成 `graph/graph.html` + `GRAPH_REPORT.md` + `graph.json`；graphify CLI 不可用时 fail-open 跳过（不告警噪音，状态可查询）；生成后前端「项目知识」页签的 graph 渲染位自动点亮（前端无需改动，探测接口已在前置 SPEC 就绪）。
- **配置项**：`knowledge.audit_enabled`（默认 true）、`knowledge.graph_enabled`（默认 true）入配置模板 + Dashboard 设置页。

## Capabilities

### 新能力
- `knowledge-backfill`：存量归档批量回填车道（聚类分批、断点续跑、批间校验提交）
- `knowledge-audit`：周期 audit 淘汰车道（五类病灶检测、机械自修/语义转写分级处置、体检报告）
- `knowledge-graph`：Graphify 关系图低频生成（fail-open、前端点亮、报告产出）

## Impact

- **新增文件**：`core/knowledge_backfill.py`（回填批处理）、`core/knowledge_audit.py`（audit 车道）、`core/knowledge_prompts/backfill.md` 与 `audit.md`（提示词）
- **修改文件**：`core/config.py` + `.fenix/config.template.yaml`（新配置项）、`core/dashboard/static/src/pages/settings/index.tsx`（设置页控件）、daemon 主循环挂周期调度（`fenixd.py`）；`core/knowledge.py` 仅 import 复用（校验器与提交工具），不修改
- **不修改**：真相源目录契约与 marker 格式（前置 SPEC 定稿，本 SPEC 只消费）；KnowledgeTab 前端（graph 探测接口已就绪）
- **风险**：300 个归档回填是批量 agent run，存在 token 成本（批处理 + 断点续跑控制浪费，复用 code-fix 亲和性分批的教训）；audit 自动修复误删风险（机械项白名单化，语义项必须走 LLM 重写而非脚本改写）
