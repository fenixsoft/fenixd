# 验证报告：add-knowledge-atlas-maintenance

> ⚠️ 本报告由框架于 2026-09-27T05:51:00Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-27T05:51:00.697313+00:00

## 结论：✅ 通过（verified）

**状态：verified — 16/16 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 16/16 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 16 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 5.73M |
| 本链增量 Token（输出） | 0.13M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| api-config-knowledge-maintenance-roundtrip | 新配置项 knowledge.audit_enabled 与 knowledge.graph_enabled 经配置接口写读回环：POST 部分节合并镜像设置页 saveConfig 契约（core/dashboard/routes/base.py:412 POST /api/config；core/dashboard/static/src/services/dashboard.ts:1526），先写 false 读回 false，再写 true 读回 true，验证设置页开关的持久化链路 | pass | 0/7 | - |
| api-knowledge-index-baseline | 真相源目录端点可用性基线（audit/graph 车道与「项目知识」页签的共同读取面）：GET /api/knowledge/index 返回 200 与项目名，未初始化时返回占位结构（出处：前置 SPEC core/dashboard/routes/knowledge_routes.py:47，经依赖 add-knowledge-atlas 合并进被测树） | pass | 0/3 | - |
| cli-graph-fixture-cleanup | graph 占位探测前置自建：清除 spec/knowledge/graph/ 产物三件套，保证 api-knowledge-graph-placeholder 的「graph.html 未生成」前置不依赖跨轮残留（上一轮 seed 场景落盘后无清理，主树残留 graph.html 曾使占位探测得 200） | pass | 0/1 | - |
| api-help-docs-list-knowledge-atlas | 帮助条目可发现：GET /api/help/docs 返回的文档清单包含 knowledge-atlas.md（docs/help/knowledge-atlas.md 交付且命名符合 HELP_DOC_NAME_RE core/dashboard/server.py:79；清单接口出处 core/dashboard/routes/help_routes.py:55） | pass | 0/2 | - |
| cli-deliverables-and-imports | 交付物落盘与可导入：core/knowledge_backfill.py 与 core/knowledge_audit.py 模块可 import（含语法与依赖完整性），core/knowledge_prompts/backfill.md 与 audit.md 提示词文件存在且分别含批量模式与「判无矛盾」契约（tasks.md 交付物清单 2.1/3.2） | pass | 0/6 | - |
| cli-backfill-unit-tests | 回填车道行为单测全绿：进度台账 pending/distilled/failed 三态、断点重入只处理未完成条目、单批失败不阻塞后续批、批间 validate_knowledge 校验与 pathspec 提交（commit 形如 [fenix] knowledge: backfill batch N/total）、收敛汇报统计（tasks.md 2.2 单测三支路：全量成功/批失败续跑/中断重入） | pass | 0/2 | - |
| cli-audit-unit-tests | audit 车道行为单测全绿：五类病灶检测（矛盾/悬空链接/重复/超150行/ADR 链断裂）、机械项脚本直修直提交、语义项转蒸馏 run 而非脚本改写、重写失败登记 todo.md、体检报告四计数与规模趋势超 +10% 标「需精简」（tasks.md 3.1 单测三支路：机械自修/语义转写/零病灶） | pass | 0/2 | - |
| cli-config-template-registration | 配置模板登记与解析：.fenix/config.template.yaml 含 knowledge.audit_enabled 与 knowledge.graph_enabled 模板行，且经 ConfigLoader 点号 key 读取（core/config.py:212 get(cls, config, dotted, default) 同款调用形态）得到布尔 true 缺省 | pass | 0/5 | - |
| cli-settings-controls-wired | 设置页控件接线：core/dashboard/static/src/pages/settings/index.tsx 源码含两新开关与配置键的绑定（audit_enabled/graph_enabled 字样出现），且 core/dashboard/static/tests/ 前端渲染单测整体全绿（tasks.md 1.2 补渲染单测） | pass | 0/4 | - |
| cli-audit-scheduling-hookup | daemon 调度接线与体检门控：fenixd.py 主循环含 knowledge_audit 自然日检查点挂载（tasks.md 3.3 与自动归档 300s 周期检查同款），audit 车道受 knowledge.audit_enabled 门控；graph 生成挂载于 core/knowledge_audit.py（tasks.md 4.1 允许独立模块但每日窗口与 audit 共用计时器） | pass | 0/4 | - |
| cli-help-doc-registered | 帮助文档落盘与目录表登记：docs/help/knowledge-atlas.md 存在且含 graphify 人工安装步骤（uv tool install graphifyy），docs/help/README.md 目录表补登记行（tasks.md 5.1 帮助条目必须可发现） | pass | 0/4 | - |
| web-settings-knowledge-section | 设置页 knowledge 区块渲染回归：navigate http://localhost:8787/settings（SPA 路由出处 core/dashboard/static/src/app.tsx:133）→ 点击「归档」页签（PAGE_LABELS.misc，core/dashboard/static/src/pages/settings/pageLabels.ts:14）→ knowledge 设置卡片与开关可见（data-testid 出处：MiscSettingsPanel.tsx:116 knowledge-settings-card、:126 knowledge-enabled-switch），新两开关落位同页不破坏既有渲染 | pass | 0/4 | - |
| web-help-knowledge-atlas-doc | 帮助页直链渲染知识图谱文档：navigate http://localhost:8787/help?doc=knowledge-atlas.md（SPA 路由出处 core/dashboard/static/src/app.tsx:135；?doc= 直链还原出处 core/dashboard/static/src/pages/help/index.tsx:41-43）→ 文档卡片渲染且正文含 graphify 安装步骤 | pass | 0/3 | - |
| api-knowledge-graph-placeholder | graph 渲染位占位语义：graph.html 未生成时探测端点 GET /api/knowledge/graph 返回 404 结构化错误且 code=knowledge_graph_not_generated（前端按 code 渲染「关系图尚未生成」占位；出处：knowledge_routes.py _api_knowledge_graph，atlas 分支实现） | pass | 0/2 | - |
| cli-graph-product-probe-seed | graph 产物落盘探测前置态：按交付契约形态在 spec/knowledge/graph/ 种入 graph.html（内容带标记 graph-probe-fixture）、GRAPH_REPORT.md 与 graph.json，模拟生成车道执行后的产物态（graphify CLI 为人工一次性安装的外部依赖，验证实例不可假定已装；产物契约见 specs/knowledge-graph/spec.md） | pass | 0/5 | - |
| api-knowledge-graph-served | graph 产物落盘后探测端点点亮：GET /api/knowledge/graph 返回 200，Content-Type 为 text/html、携带 CSP sandbox 头（生成物内联脚本以不透明源运行）且响应体含种入标记（出处：knowledge_routes.py _api_knowledge_graph 下发分支） | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 16 个（第 1 轮）。

- 首轮写入 16 个场景

