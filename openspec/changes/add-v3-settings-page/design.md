# Design: add-v3-settings-page

## Context

- v3 位于 `core/dashboard/static/v3`（UmiJS Max 4 + antd 6 + pro-components），`/settings` 现为 `PagePlaceholder` 占位。
- 后端 `/api/config`（`core/dashboard/data.py` + `server.py`）已完整支持：`GET /api/config?project=<name>`（返回 llm/agents/gates + `sources` 来源标注 + `scope` + `raw_exists`）、`PUT /api/config`（仅受管键 `_MANAGED_KEYS = ["llm","agents","gates"]` 白名单合并写回）。v1 前端（`static/app.js` renderConfig ~2135-2945 行）是功能基线。
- 界面风格不走配置接口：v1 存 localStorage `fenix.theme`（light/dark，默认 dark），v3 当前无主题切换实现。

## Goals / Non-Goals

- Goals：v3 设置页补齐 v1 配置管理全部六个子项；布局与交互对齐 ant-design account/settings 风格。
- Non-Goals：不新增/修改任何后端端点；不实现配置版本历史、diff 预览；不迁移 v1 的"链编辑器"增强交互（保持简单 Provider+模型两级分配即可，若实现方认为需要可在 Agent 模型分配内做更直观的编排，但必须等价覆盖 v1 的 `agents.models` 数据结构）。

## Decisions

- **D1 布局**：`Card` 包裹 + 左侧 `Menu mode="inline"`（六子项）+ 右侧面板区；页面骨架参考 antd account/settings demo 的 account/settings 布局（左侧菜单固定宽 224px，右侧 `Card bordered={false}`）。子项选中状态放组件内 state（不做路由子分段，保持 `/settings` 单路由）。
- **D2 数据流**：`src/services/dashboard.ts` 新增 `getConfig(project?: string)` 与 `saveConfig(project: string | undefined, payload)` 封装；页面挂载与作用域切换时拉取；保存成功后重新拉取（静默刷新 sources/继承标注）。
- **D3 表单方案**：每个子项一个 antd `Form` 实例（`form` 隔离），子项切换不销毁已填内容；保存仅提交当前子项涉及的键（但 PUT body 携带完整受管结构——从最近一次 GET 的数据上 merge 当前子项变更，避免把其它子项未保存的半成品写回）。
- **D4 控件选型**（实现方可按效果微调，但语义必须等价）：
  - Provider 列表：卡片 + `Form.List`；apikey 用 `Input.Password`；删除走 `Popconfirm`。
  - Agent 模型分配：每角色一行 `Select`（Provider）+ `Input`/`AutoComplete`（model）。
  - 并行度/Token 预算：`InputNumber`（min/max/step 按 v1 约束：max_concurrent≥1、max_turns≥1、run_timeout_seconds≥1、token_budget_millions≥0、daily_run_limit≥0、impl_run_budget 1-10）。
  - 审批模式：`Radio.Group`（manual/auto，附说明文案）。
  - 界面风格：`Radio.Group` 或 `Segmented`（亮色/暗色），onChange 即写 localStorage `fenix.theme` 并切换 `document.documentElement.dataset.theme`；v3 当前无暗色样式实现，先落地存储与切换语义，暗色样式可作为本 spec 的一部分做最小实现（antd `theme.darkAlgorithm` 通过 ConfigProvider 切换）。
- **D5 作用域切换**：设置页头部提供作用域选择（用户级 / 各项目下拉，同 v1），切换即重新 GET；未选择项目时默认用户级。作用域状态放 URL query（`/settings?scope=user` / `?project=<name>`）以支持刷新保持。
- **D6 反馈**：统一 `App.useApp()` 的 message；400 校验错误展示后端 `error` 字段。

## Risks / Trade-offs

- `agents.models` 结构 v1 中存在历史链式增强（chain rows）；本 spec 只保证读写等价（键为角色、值为 provider/model），v1 链编辑器的复杂交互不迁移。
- 暗色主题：若实现方仅落地 antd darkAlgorithm，v1 遗留的自定义暗色细节（v2/v1 CSS 变量）不做像素级对齐；以"可切换、可持久化、可读性可用"为验收线。
- 配置保存是全量受管键写回：并发编辑（v1 与 v3 同时开）后保存者胜出，与 v1 行为一致，不额外处理。

## Migration Plan

1. services 增加 config 封装 → settings 页骨架（菜单+面板路由）→ 逐子项实现（Provider → 模型分配 → 并行度 → 审批 → Token 预算 → 界面风格）→ 保存/错误反馈联调。
2. 每步完成后浏览器实测对应 Scenario。

## Open Questions

- 无（控件细节授权实现方自行探索，行为以 spec Scenario 为准）。
