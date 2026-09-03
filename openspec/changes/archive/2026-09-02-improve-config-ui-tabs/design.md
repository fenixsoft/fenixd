## Context

配置页（`core/dashboard/static/app.js` 的 `renderConfig`）当前将 4 个区块垂直平铺：LLM Provider 列表 / Agent 模型分配 / 并行度设置 / 审批模式。页面为单文件原生 JS（vanilla + 模板字符串），无前端框架，视图由 hash 路由（`#config/<project>`）驱动，SSE 推送时不整页重绘配置页（保持表单输入）。

Administrator 角色由 `add-administrator-agent` 引入，运行时 `run_administrator` 通过 `_get_admin_model()` 解析模型：`admin.agent_model`（配置键）→ `DEFAULT_GATEWAY_MODEL`（`claude-sonnet-5`），不分配 Provider、不注入 Provider 环境变量，走默认网关。其余 Agent（implementer/planner-plan/planner-judge/verifier）通过 `agents.models[role] = {provider, model}` 分配，运行时有 Provider 时注入 `ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY`/自定义 env 直连并可放置自定义模型。

后端校验白名单 `ConfigLoader.KNOWN_AGENT_TYPES = ["implementer", "planner-plan", "planner-judge", "verifier"]` 与前端渲染列表（app.js 顶部 `KNOWN_AGENT_TYPES`）两处各有一份。

## Goals / Non-Goals

**Goals:**
- 配置页 4 区块页签化，各页签内容与原区块一致，页面聚焦、不再长距滚动。
- Agent 模型分配区补上 Administrator，交互与其余 Agent 完全同构（勾选 + Provider 下拉 + 模型名），写入 `agents.models.administrator`。
- Administrator 运行时优先使用该 assignment（走 Provider 直连），未配置时保持现有行为（`admin.agent_model` → 默认网关），兼容存量配置。
- 保存仍为全局一次写回（跨所有页签收集），保存后需重启 daemon 生效的提示语义不变。

**Non-Goals:**
- 不改动各配置键的语义与校验规则（approve_mode / max_concurrent / run_timeout_seconds 保持不变）。
- 不做配置项分组排序、搜索、批量导入导出等进阶 UI。
- 不把页签子状态纳入 URL hash（刷新后回到默认页签可接受）。
- 不迁移/废弃 `admin.agent_model` 键（保留为回退链的一环）。

## Decisions

### D1. 页签采用「一次渲染全部 pane + display 切换」，而非按需渲染

页签容器 `.config-tabs`（tab bar + 4 个 pane）在 `renderConfig` 时全部渲染到 DOM，切换仅切换 pane 的 `hidden`/`active` class。**理由**：用户在 LLM Provider 页签编辑中途切去其他页签再切回时，表单输入必须保留——按需渲染（切到哪渲染哪）会丢输入。这与现有「配置页不整页重绘」的 SSE 策略一致。

### D2. 保存按钮位于页签栏（4 个 pane）之外，序列化遍历所有页签

保存逻辑改为从全部 pane 的 DOM 收集字段（现有 `hydrateConfigPage` 已按 id 读取字段，pane 一次性渲染后选择器无需感知页签）。每次切换页签不重置 `configInitialized`，避免重复绑定事件。

### D3. Administrator 进入统一分配结构 `agents.models.administrator`

- 后端 `ConfigLoader.KNOWN_AGENT_TYPES` 增加 `administrator` → `_validate_agent_models` 自动放行该键的 {provider, model} 校验，无需新校验路径；前端渲染列表同步增加（label「Administrator（运维）」）。
- dashboard 受管键白名单已含整个 `agents` 段（`_MANAGED_KEYS`/`_SOURCE_KEYS`），`agents.models.administrator` 读写自动透传，无需改 data.py。
- **备选**（否决）：继续扩展 `admin.agent_model` 单字段 = UI 交互与其他 Agent 不一致、用户已确认采用 Provider+模型 同构方案。

### D4. Agenda Runtime 解析链（agent_runner.run_administrator）

```
1. _get_agent_model_assignment("administrator") → 有 assignment：
   - model_override = assignment.model
   - env_overrides = {ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY} + provider.env 自定义项
   - _ensure_agent_config_dir(provider.name)（与其他 Agent 相同的隔离配置目录）
2. 无 assignment → 现状：_get_admin_model()（admin.agent_model → DEFAULT_GATEWAY_MODEL），
   不注入任何 provider env（走默认网关）
```

沿用 `_run_agent` 中已存在的 provider 注入范式（`_run_claude` 已支持 `env_overrides` 参数），只差 administrator 分支补 env 构造。行为变更仅发生在用户显式给 Administrator 分配了 Provider 时。

### D5. 配置校验交叉依赖

若用户给 administrator 分配了不存在于 `llm.providers` 的 provider，`_validate_agent_models` 会在保存/启动时拒绝（400），与其余角色一致，无需额外处理。

## Risks / Trade-offs

- [与 `improve-agent-config-and-verify-resume`（agent-run-params-config）同改 `agents.models` 区域] → 该 change 已完成实现（commit 179254c 已合并），本 change 在其后开发，合并冲突概率低；若冲突以本 change 为准补齐 administrator 键。
- [Administrator 从默认网关切到 Provider 直连是运行时行为变化] → 仅在显式分配后发生；回退链完整保留旧配置语义；spec 中明确该行为供用户知悉。
- [SSE 推送配置页刷新策略与页签共存] → 现有「配置页不整页重绘」逻辑不变，页签状态纯粹是前端 DOM 状态，互不影响。
- [前端/后端两份 KNOWN_AGENT_TYPES 易漂移] → 两者本就是静态清单，本次同步增加一条；spec 要求实现时保持两端一致。

## Migration Plan

1. 代码合入后重启 dashboard/daemon 即可生效（前端静态文件直接替换，无数据库）。
2. 存量配置若有 `admin.agent_model` 且未给 administrator 分配 providers → 运行行为不变。
3. 回滚：还原 app.js/style.css 的页签渲染与 agent_runner 的 administrator 分支即可，配置数据无结构迁移。

## Open Questions

无（Administrator 分配形式已与用户确认：Provider + 模型 同构方案）。