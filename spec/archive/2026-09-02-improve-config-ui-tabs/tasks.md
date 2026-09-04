## 1. 后端：Administrator 角色注册

- [ ] 1.1 `core/config.py`：`KNOWN_AGENT_TYPES` 增加 `"administrator"`，使 `agents.models.administrator` 通过 `_validate_agent_models` 校验
- [ ] 1.2 `core/agent_runner.py`：`run_administrator` 优先解析 `_get_agent_model_assignment("administrator")`；有 assignment 时 `--model` 用 assignment.model，并向 `_run_claude` 传入 `env_overrides`（provider 的 baseurl/apikey + 自定义 env），同时调用 `_ensure_agent_config_dir(provider.name)`
- [ ] 1.3 `core/agent_runner.py`：无 assignment 时保留现有回退链（`_get_admin_model()` → `admin.agent_model` → `DEFAULT_GATEWAY_MODEL`，不注入 provider env）
- [ ] 1.4 单元测试：`agents.models.administrator` 带 provider 时 Administrator 运行注入 provider env 并使用分配模型；`admin.agent_model` 存在时回退旧键；两者皆无时回退默认网关常量

## 2. 前端：配置页页签化

- [ ] 2.1 `core/dashboard/static/app.js`：`renderConfig` 重构为 `.config-tabs` 容器（tab bar + 4 个 pane：LLM Provider / Agent 模型分配 / 并行度设置 / 审批模式），内容与原 4 个 config-section 一致，pane 一次性全部渲染
- [ ] 2.2 `core/dashboard/static/app.js`：`hydrateConfigPage` 绑定页签切换（切换仅显隐 pane、不清 DOM 状态、不重置 `configInitialized`），配置页不整页重绘（SSE 策略）行为保持不变
- [ ] 2.3 `core/dashboard/static/app.js`：保存按钮与保存提示移至页签栏外（所有 pane 之外）；保存序列化收集全部 pane 字段而非仅当前页签，保存/错误横幅在任意页签下可见
- [ ] 2.4 `core/dashboard/style.css`（或对应样式文件）：新增 `.config-tabs` / tab bar / pane 显隐样式，与现有 fenix 风格一致

## 3. 前端：Administrator 分配卡片

- [ ] 3.1 `core/dashboard/static/app.js`：渲染列表 `KNOWN_AGENT_TYPES` 增加 `{key: 'administrator', label: 'Administrator（运维）'}`，复用 `renderAgentAssignment` 卡片交互（开关 + Provider 下拉 + 模型名）
- [ ] 3.2 回显：`agents.models.administrator` 存在时卡片默认开启并填充 Provider/模型名；不存在时不勾选、字段为空

## 4. 验证

- [ ] 4.1 配置保存校验：无 provider 可用时的提示逻辑对 administrator 卡片生效；保存含未知 provider 的 administrator 分配返回校验错误（400），不落盘
- [ ] 4.2 回归：其余角色（implementer/planner-plan/planner-judge/verifier）分配、并行度、审批模式、Provider CRUD 保存路径在页签化后行为不变
- [ ] 4.3 运行 `tests/test_dashboard.py` 与 `tests/test_core.py` 全量通过；手工浏览器验证页签切换表单状态保留、保存跨页签生效