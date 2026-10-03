## Why

Dashboard「模型」页签配置 Provider（Base URL / API Key / 默认模型名）、「模型分配」页签把 Provider+模型分配给各 Agent 角色，但配置是否真正可用（端点可达、密钥有效、模型名正确）只能等下一次 agent 派发失败才知道——排障链路太长。需要一个一键健康检测：发一条极小请求（如 hello），直接看到「模型是否回复 + 响应时间」。

## What Changes

- 新增后端健康检测端点 `POST /api/config/llm-health-check`：接收表单当前值（`baseurl` / `apikey` / `model`），向 `{baseurl}/v1/messages` 发送一条 `max_tokens` 极小的最小消息请求，返回「是否回复 + 响应耗时（毫秒）+ 失败原因分类」。由 daemon 后端代理执行（浏览器直连任意 baseurl 受 CORS 限制，且 API Key 不经第三方转发）。
- 「模型」页签（LlmProviderPanel）：每张 Provider 卡片标题栏新增**文字按钮**「健康检测」，用该卡片表单当前值（含未保存修改）发起检测，结果内联显示在卡片上（检测中 → 正常 · X.Xs / 失败：原因）。
- 「模型分配」页签（AgentModelPanel）：每个 Provider 行在**删除图标之前**新增**图标按钮**（健康检测），检测对象按行内 Provider + 模型解析（行内模型留空时按运行期同款链解析：角色级缺省模型 → Provider 默认模型），结果内联显示在该行。
- 检测使用**表单当前值**语义：Provider 的 baseurl/apikey 优先从本表单正在编辑的 Provider 列表按名字解析，表单中找不到（如引用了未在表单展示的用户级 Provider）时回退已保存配置。

## Capabilities

### New Capabilities

- `llm-health-check`: LLM Provider 健康检测——后端代理探测端点（最小请求、耗时测量、失败分类、超时）与两处前端入口（模型页签文字按钮、模型分配行图标按钮）的交互与结果展示。

### Modified Capabilities

（无——既有页签能力的需求不变，仅新增按钮与端点。）

## Impact

- 后端：`core/dashboard/routes/settings_routes.py`（新 handler）、`core/dashboard/routes/base.py`（POST 路由表注册）、新增 `core/dashboard/llm_health.py`（检测逻辑，参照 `bin/probe_prompt_cache.py` 的 stdlib urllib + `/v1/messages` + `x-api-key`/`anthropic-version`/`Authorization: Bearer` 请求构造先例）。
- 前端：`core/dashboard/static/src/services/dashboard.ts`（service 函数）、`core/dashboard/static/src/pages/settings/components/LlmProviderPanel.tsx`、`AgentModelPanel.tsx`。
- 成本：每次检测一条极小请求（`max_tokens: 64`，"hello"），计费影响可忽略。
- 无数据迁移、无既有 API 行为变更。
