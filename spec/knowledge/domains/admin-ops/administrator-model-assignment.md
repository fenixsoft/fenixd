<!-- knowledge: capability=administrator-model-assignment rev=1 sources=spec/archive/2026-09-02-improve-config-ui-tabs -->

# Administrator 模型指派

Administrator 角色的 Provider + 模型分配，与其余 Agent 角色同构，运行时按指派注入 Provider 环境。

## 现行规则

- 配置页「Agent 模型分配」区含 Administrator（运维）角色卡片，交互与其他角色一致：启用勾选框、Provider 下拉（列出全部可用 LLM Provider）、模型名输入；保存写入 `agents.models.administrator = {"provider": <名>, "model": <名>}`。
- `administrator` 在 `KNOWN_AGENT_TYPES` 注册，指派经既有 `_validate_agent_models` 校验；Provider 名不在 LLM Provider 列表时保存被拒并指名未知 Provider，不写部分配置。
- 运行时模型解析按序回退：(1) `agents.models.administrator` 指派——模型名作 `--model`，并注入该 Provider 的环境（baseurl/apikey/自定义 env）；(2) 旧键 `admin.agent_model` 字符串；(3) 默认网关模型常量。
- Provider 环境仅在存在 `agents.models.administrator` 指派时注入；走旧键或缺省时按默认网关行为运行、不注入。
- 未指派时卡片渲染为未勾选、Provider/模型空字段，缺 Provider 提示与其他角色一致；配置页回读已保存指派时原样显示。

## 溯源

- 2026-09-02 improve-config-ui-tabs（spec/archive/2026-09-02-improve-config-ui-tabs） — Administrator 纳入 Agent 模型分配区（agents.models.administrator），运行时按指派注入 Provider env 并保留 admin.agent_model → 默认网关回退链
