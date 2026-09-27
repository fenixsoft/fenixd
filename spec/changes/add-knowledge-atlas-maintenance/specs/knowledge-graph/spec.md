## ADDED Requirements

### Requirement: Graphify 关系图低频生成

框架 SHALL 低频（每日一次，与 audit 同窗口或独立计时，实现裁量）对 `spec/knowledge/` 运行 Graphify 生成关系图产物至 `spec/knowledge/graph/`：`graph.html`（可交互关系图）、`GRAPH_REPORT.md`（关键概念与意外连接摘要）、`graph.json`（全量图数据）。graphify CLI 不可用（未安装、执行失败）时 SHALL fail-open 跳过本次生成，记单行日志（不产生告警噪音）；`knowledge.graph_enabled` 为 false 时 SHALL 跳过。生成产物 SHALL 入库（git tracked），提交 pathspec 限定 `spec/knowledge/graph/`。

#### Scenario: 正常生成并入库

- **WHEN** graphify CLI 可用且每日窗口到达
- **THEN** `spec/knowledge/graph/` 下产出 graph.html、GRAPH_REPORT.md、graph.json 并自动提交；「项目知识」页签 graph 渲染位经既有探测接口点亮（前端零改动）

#### Scenario: CLI 缺失降级

- **WHEN** graphify 未安装
- **THEN** 当次生成跳过，记单行日志；真相源本体与页签其余功能不受影响；graph 渲染位维持「关系图尚未生成」占位

#### Scenario: 禁用开关生效

- **WHEN** 用户在设置页将 `knowledge.graph_enabled` 置为 false
- **THEN** 不再派发生成（既有 graph/ 产物保留可渲染，不删除）
