## Why

fenixd 的 token 消耗目前只能观测用量（input / output / cache 读写分项），无法换算成金额：网关基本不回传 `cost_usd`，用户对每一轮 run「烧了多少钱」没有感知。LLM 按模型计费且输入/输出/缓存读/缓存写单价不同，而 fenixd 是无人值守的自动化消费进程——成本可观测是治理失控消费的前提（见 fenixd 未覆盖框架缺口清单「成本不可观测」项）。

## What Changes

- 设置页「模型」页签（llm）新增**计费信息**：总开关（启用计费信息）+ 按 **provider+model** 粒度的 4 项单价输入——每百万输入 token 费用、每百万输出 token 费用、缓存命中（cache_read）token 费用、缓存写入（cache_creation）token 费用（单位 $/1M tokens）。计费信息为可选配置，不开关、不填写均不影响现有流程。
- 成本**只认本地计算**：`成本 = input/1M×输入价 + output/1M×输出价 + cache_read/1M×缓存读价 + cache_creation/1M×缓存写价`。每 run 的 usage 与实际 `model@provider`（run 产物尾部 result 事件 + provider_marker，含历史 run）按配置单价计算；未配置价格的模型显示「成本不可用」，**不再展示网关回传金额**。
- SPEC 详情页显示该 spec 的成本信息：可计价 run 的成本求和；存在未计价 run 时附注数量。
- 运行时间轴每个 runner 节点显示该 run 的成本标注。

## Capabilities

### New Capabilities

- `model-billing-config`：设置页模型页签的计费信息配置——总开关、按 provider+model 的 4 项单价输入、后端校验与配置读写回显。

### Modified Capabilities

- `cost-observability`：金额展示口径由「网关回传 cost_usd 才展示」改为「只认本地计算（token×配置单价）」；新增 per-run 成本计算与展示、SPEC 级成本合计展示（需求「金额展示不伪造」口径变更 + 展示范围扩展）。

## Impact

- `core/dashboard/static/src/pages/settings/components/LlmProviderPanel.tsx` — 计费信息 UI（开关 + 每 Provider 价格行）
- `core/dashboard/static/src/services/dashboard.ts` — ConfigData 增 `llm.billing` 类型
- `core/dashboard/data.py` — `read_config`/`write_config` 的 billing 提取与校验、`_run_tail_insights` 提取 usage、`get_spec_timeline` run 节点附成本、`get_spec_detail` 成本合计、`_token_usage_view` 口径
- `core/dashboard/server.py` — `/api/config` 透传（billing 属 llm 受管段，预期零改动或仅校验接入）
- `core/dashboard/static/src/pages/projects/detail.tsx` — 时间轴成本 Tag + 详情成本展示
- 不改 `core/agent_runner/`（usage 已在 run 产物中，无需新增持久化）；STATE `_cost_usd` 网关回传累计保留但退出展示
- 配置热更新（30s mtime 检测）天然生效，价格改动无需重启 daemon
