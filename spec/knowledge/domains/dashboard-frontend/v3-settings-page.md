<!-- knowledge: capability=v3-settings-page rev=1 sources=spec/archive/2026-09-08-add-v3-settings-page -->

# v3 设置页

v3 的统一设置入口：左侧子项菜单 + 右侧面板，复用 v1 配置后端，覆盖 Provider、模型分配、并行度、审批、预算与主题。

## 现行规则

- `/settings` 路由采用 account/settings 风格布局：左侧竖向子项菜单（LLM Provider / Agent 模型分配 / 并行度设置 / 审批模式 / Token 预算 / 界面风格），右侧为当前子项面板；默认选中「LLM Provider」。
- 配置经 `GET /api/config?project=<name>` 读取（复用 v1 后端，零后端改动）；支持用户级（无项目参数，写 `~/.fenix/config.yaml`）与项目级（写 `.fenix/config.yaml`）作用域切换，默认项目级；无配置文件时展示提示且表单为默认值；受管键在响应 `sources` 中标记 `user` 时，面板展示「继承自用户级」提示。
- LLM Provider 子项管理 `llm.providers` 列表：Provider 卡片（名称、baseurl、apikey、默认模型）支持追加空白卡片、编辑、删除，保存时整体写回数组。
- Agent 模型分配子项按 Agent 角色（KNOWN_AGENT_TYPES 全集）逐个分配：Provider 下拉（取自 `llm.providers`）+ 模型名（留空使用该 Provider 默认模型），写回 `agents.models`（`{provider, model}`）；作用域内无 Provider 时展示「请先在 LLM Provider 子项添加 Provider」引导。
- 并行度设置子项提供三个正整数：`agents.max_concurrent`（默认 2）、`agents.max_turns`、`agents.run_timeout_seconds`（秒），附严格优先级并行语义与「约 30 秒内热加载生效」说明。
- 审批模式子项为 `gates.approve_mode` 单选：manual（SPEC 完成后停留 done，等待人工推送）/ auto（自动推送）。
- Token 预算子项提供三个数值：`agents.token_budget_millions`（百万，0=关闭，默认 50）、`agents.daily_run_limit`（0=不限）、`agents.impl_run_budget`（1-10）。
- 界面风格子项提供亮色/暗色切换：选择后立即全站生效并写入浏览器 localStorage（键 `fenix.theme`）；不参与 `PUT /api/config` 保存路径。
- 各子项统一保存：保存前基础校验（数值范围等）；成功后提示并静默刷新配置数据；失败时展示可读错误（后端 `error` 字段优先），不重置用户已填写内容。

## 溯源

- 2026-09-08 add-v3-settings-page（spec/archive/2026-09-08-add-v3-settings-page） — 建立 v3 设置页六子项布局、作用域读写与继承标注、各子项配置键契约及统一保存 / 错误反馈
