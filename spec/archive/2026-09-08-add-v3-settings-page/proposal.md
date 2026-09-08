# Proposal: add-v3-settings-page

## Why

v3 dashboard（`core/dashboard/static/v3`）目前「设置」菜单是"建设中"占位页，用户无法在 v3 中完成 v1 配置页提供的任何设置操作（LLM Provider、Agent 模型分配、并行度、审批模式、界面风格、Token 预算），只能回退 v1。为完成 v3 对 v1 的全功能替换，需要将配置管理迁移至 v3。

## What Changes

- v3 新增 `/settings` 路由页面（替换现有占位组件），整体布局参考 ant-design account/settings 示例：左侧竖向菜单 + 右侧设置面板。
- 设置拆分为 6 个子项（每个对应左侧菜单一项，右侧独立面板）：
  1. **LLM Provider**（`llm.providers`）：Provider 卡片列表（baseurl / apikey / 默认模型），支持新增、编辑、删除；迁自动 v1 "LLM Provider 列表"。
  2. **Agent 模型分配**（`agents.models`）：按 Agent 角色逐个分配 Provider 与模型；迁自动 v1 "Agent 模型分配"。
  3. **并行度设置**（`agents.max_concurrent` / `agents.max_turns` / `agents.run_timeout_seconds`）：数值设置；迁自动 v1 "并行度设置"。
  4. **审批模式**（`gates.approve_mode`）：manual / auto 单选；迁自动 v1 "审批模式"。
  5. **Token 预算**（`agents.token_budget_millions` / `agents.daily_run_limit` / `agents.impl_run_budget`）：数值设置；迁自动 v1 "Token 预算"。
  6. **界面风格**：亮色/暗色主题切换，仅写浏览器 localStorage（`fenix.theme`），不进入保存路径；迁自动 v1 "界面风格"。
- 数据流复用现有 v1 后端：`GET /api/config?project=<name>` 读取、`PUT /api/config` 保存（受管键见 `core/dashboard/data.py` `_MANAGED_KEYS`），作用域切换（用户级/项目级）随 v1 语义；**后端零改动**。
- 各子项内部控件由实现方自行探索合适的 ant design 组件（如 Form / InputNumber / Radio.Group / Select / Card 等），但须满足本文 spec 的行为 Scenario。

## Capabilities

### New Capabilities

- `v3-settings-page`: v3 设置页的布局、六个设置子项、保存与继承语义、界面风格本地持久化。

## Impact

- **前端**：`core/dashboard/static/v3/src/pages/settings/`（替换占位页）、`src/services/dashboard.ts`（新增 config 读写封装）、`config/routes.ts`（/settings 指向真实页面）。
- **后端**：无改动（复用 `/api/config` GET/PUT）。
- **影响范围**：v3 设置页可用性；不影响 v1 与其余页面。
