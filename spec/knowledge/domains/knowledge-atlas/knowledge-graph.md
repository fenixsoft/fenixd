# Graphify 关系图低频生成

<!-- knowledge: capability=knowledge-graph rev=1
     sources=spec/archive/2026-10-05-add-knowledge-atlas-maintenance -->

低频对真相源运行 Graphify 生成概念关系图的车道，点亮「项目知识」页签的关系图渲染位。

## 规则

- 调度与窗口：每日一次，与 audit 车道共用自然日计时器（同一次自然日检查点先后跑 audit 与 graph）。`knowledge.graph_enabled`（布尔，缺省 true）为 false 时不再派发生成，既有 `graph/` 产物保留可渲染、不删除；配置改动经既有 30s 热更新生效，开关与 audit 开关同落设置页「归档」页签的 knowledge 设置卡片。
- 产物契约：对 `spec/knowledge/` 执行 Graphify，产物入 `spec/knowledge/graph/` 三件套——`graph.html`（可交互关系图）、`GRAPH_REPORT.md`（关键概念与意外连接摘要）、`graph.json`（全量图数据）。产物入库（git tracked），提交 pathspec 限定 `spec/knowledge/graph/`；GRAPH_REPORT.md 直接入库、不二次加工。
- 前端点亮零改动：graph 渲染位经既有探测端点 GET /api/knowledge/graph 判定——产物未生成时返回 404 结构化错误（code=knowledge_graph_not_generated），前端渲染「关系图尚未生成」占位；产物落盘后同端点返回 200 text/html 并携带 CSP sandbox 头。前端 iframe 内嵌渲染、不解析 graph.html 内部结构（与其内部结构零耦合，graphify 版本升级改结构不影响前端）。
- fail-open 降级：graphify CLI 不可用（未安装、执行失败）时跳过本次生成，记单行日志、不产生告警噪音；真相源本体与页签其余功能不受影响。
- 依赖形态：graphify 为可选外部依赖，人工一次性安装（`uv tool install graphifyy`，步骤登记于 docs/help/knowledge-atlas.md 帮助文档与帮助目录表）；daemon 侧以 `shutil.which('graphify')` 探测可用性，不做运行时安装。图语义通道的 LLM pass 使用 graphify 自身配置，独立于 fenixd agent 网关、不横加干预。

## 溯源

- 2026-10-05 add-knowledge-atlas-maintenance（spec/archive/2026-10-05-add-knowledge-atlas-maintenance） — 新增本能力页：graph/ 三件套产物契约、与 audit 共用自然日窗口、fail-open 降级、人工一次性安装、探测端点点亮与占位语义
