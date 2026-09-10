# Proposal: add-dashboard-help-center

## Why

fenixd 的能力面（状态机、调度治理、验证链、预算熔断、告警分级、Dashboard 四页、7 个 CLI skill）全部沉淀在代码与配置里，除一份已过时的 README 外没有任何面向人类的系统性使用文档。新用户不知道完整流程怎么走、SPEC 卡住时不知道哪条规则在起作用、出问题时不知道去哪查——排查成本全部压在对话与口口相传上。需要一组以当前代码为准、人类可流畅阅读的使用帮助文档，并内置到 Dashboard 中随时可查。

## What Changes

- 新增文档集：仓库新增 `docs/help/` 目录，承载 11 篇中文 Markdown 帮助文档（1 篇目录索引 + 10 篇正文：快速上手 / 核心概念与架构 / SPEC 生命周期与状态机 / CLI 操作手册 / 验证体系 / 调度与治理规则 / Dashboard 使用指南 / 配置参考 / 文件与数据地图 / FAQ 与故障排查）。
- 文档内所有图表使用 mermaid（不使用 ASCII 图），以当前代码行为为唯一事实来源（已识别 README 与 config.template.yaml 若干过时点，文档按实际行为写）。
- Dashboard 新增「帮助」菜单：位于侧边栏「运维」菜单之下，路由 `/help`；帮助页左侧文档目录、右侧 Markdown 正文渲染，支持 mermaid 图渲染与移动端适配。
- 后端新增帮助文档读取 API：从框架仓库 `docs/help/` 目录动态读取文档列表与正文（文档更新无需重建前端 dist）。
- 前端新增 mermaid 渲染依赖，dist 重建入库。

## Capabilities

### New Capabilities

- `help-docs`: 帮助文档内容本体——11 篇文档的结构、覆盖范围、撰写原则（以代码为准、mermaid 图表、交叉链接、每篇可独立阅读）。
- `help-center`: Dashboard 帮助中心功能——「帮助」菜单项（运维之下）、帮助页（目录 + 正文布局）、Markdown 与 mermaid 渲染、后端文档读取 API（动态读 `docs/help/`，改文档免重建）、移动端适配。

### Modified Capabilities

（无——不修改任何既有能力的需求）

## Impact

- **新增文件**：`docs/help/`（11 篇 .md）、`core/dashboard/static/src/pages/help/index.tsx` 及配套组件。
- **修改文件**：`core/dashboard/server.py`（新增文档读取端点）、`core/dashboard/static/config/routes.ts`（注册 `/help` 路由）、`core/dashboard/static/src/app.tsx`（菜单数组 + 面包屑映射）、`core/dashboard/static/package.json`（mermaid 依赖）、`core/dashboard/static/dist/`（构建产物入库）。
- **依赖**：前端新增 `mermaid` npm 包；后端零新依赖（标准库读文件）。
- **风险**：文档内容与代码漂移（缓解：文档中标注「以代码为准」的关键行为均经代码核对）；mermaid 包体积影响 dist 体积（采用动态 import 按需加载）。
