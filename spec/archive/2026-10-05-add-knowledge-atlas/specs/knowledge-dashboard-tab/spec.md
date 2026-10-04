## ADDED Requirements

### Requirement: 项目知识页签

项目详情页 Tabs SHALL 在「会话接入」页签之前新增「项目知识」页签（即位于「架构」与「会话接入」之间）。页签内容 SHALL 按需加载：仅在该页签处于选中态时发起数据请求（对齐 QualityTab/RegressionTab/ArchitectureTab 的 active 门控语义）。

#### Scenario: 页签位置与按需加载

- **WHEN** 用户打开项目详情页且未选中「项目知识」页签
- **THEN** 页签栏中「项目知识」位于「会话接入」之前；网络面板中无 knowledge 相关请求；点选该页签后才发起请求

### Requirement: 知识内容渲染

「项目知识」页签 SHALL 提供：①`index.md` 渲染视图——总目录的 Markdown 渲染，域/能力链接可点击进入对应能力页渲染；②ADR 索引视图——`adr/index.md` 的列表渲染（编号、标题、状态标签），点击可看 ADR 三段正文，superseded 条目带「已被 ADR-NNN 取代」标识与跳转；③关系图渲染位——当 `spec/knowledge/graph/graph.html` 存在时内嵌展示，不存在时显示「关系图尚未生成」占位文案（图生成本 SPEC 不交付，由 add-knowledge-atlas-maintenance 承接）。后端 SHALL 提供只读 API 返回真相源文件内容（Markdown 原文，前端渲染），路径穿越 MUST BE 拒绝。

#### Scenario: 浏览总目录并进入能力页

- **WHEN** 用户选中「项目知识」页签并点击 index 中的某能力链接
- **THEN** 页签内渲染该能力页的 Markdown（含规则散文与溯源段）；后端返回该能力页文件内容

#### Scenario: graph 缺位时占位

- **WHEN** `spec/knowledge/graph/` 不存在（maintenance SPEC 未执行）
- **THEN** 关系图区域显示占位文案，页面其余部分（index/ADR）正常可用

#### Scenario: 路径穿越被拒绝

- **WHEN** 请求携带 `../../.fenix/STATE.md` 类路径参数访问知识文件 API
- **THEN** 后端返回 4xx，不泄露任何文件内容
