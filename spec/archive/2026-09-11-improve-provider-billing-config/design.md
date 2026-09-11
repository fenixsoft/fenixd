# Design: improve-provider-billing-config

## Context

活跃 change `add-model-billing-cost-display` 刚落地了模型计费展示：全局「启用计费信息」开关 + 独立 `llm.billing = {enabled, prices: [{provider, model, 4价}]}` 段 + `data.py` 本地成本计算（`compute_run_cost` 按 provider+model 精确匹配价格行）+ timeline / SPEC 级合计。用户试用后提出交互与结构问题：开关与卡片脱节、价格行手填 Provider/模型名重复、单价无标题栏、金额可输入任意字符。当前 `.fenix/config.yaml` 中 `billing: null`——无存量价格数据，结构切换无迁移负担。

约束：fast-track 单 Agent 完成；`llm.providers` 是核心配置段（`core/config.py` 校验、runner 读取），向其中内嵌 `billing` 子对象不得破坏既有消费方。

## Goals / Non-Goals

**Goals:**
- 计费开关下沉到每个 Provider 卡片；价格区仅卡片开启时可见。
- 价格行去 Provider 选择框、模型名预填卡片默认模型名（可改）、4 价 2×2 带标题栏、仅可输入金额。
- 存储结构改为 `providers[i].billing = {enabled, prices: [{model, 4价}]}`，移除顶层 `llm.billing`。
- 后端保存校验与计价闸门语义随结构同步（per-provider 开关 + 行模型匹配）。

**Non-Goals:**
- 不做旧结构迁移或双读兼容（存量无价格数据）。
- 不改 `projects/detail.tsx` 的成本展示（仅消费 `cost_usd`，对闸门语义透明）。
- 不改 usage 采集链路（`_run_tail_insights` / provider_marker 不动）。
- 不新增 dashboard 界面之外的配置能力（遵循「新增配置项必须带 Dashboard 界面」约定，本次配置键与 UI 同步调整）。

## Decisions

### D1: 存储内嵌 provider 对象，删除顶层 llm.billing
`providers[i].billing = {enabled, prices: [{model, input_per_million, output_per_million, cache_read_per_million, cache_creation_per_million}]}`。
- 为什么：UI 与存储同构（「卡片内部」直接映射）；删除 Provider 时价格随删无孤儿；价格行 provider 字段自然消失。
- 备选：保留 `llm.billing` 改 per-provider map——两处维护 provider 名引用、删卡片需联动清理，放弃。
- 影响面已核实：`ConfigLoader._validate_llm` 只校验已知键不拒绝未知键；runner 以 `dict.get` 访问 provider 字段，多余 `billing` 键无害。全库仅 `data.py` 读取 billing（前端 `detail.tsx` 只消费 cost_usd）。

### D2: 计价闸门从全局布尔改为 per-provider 谓词
`_load_billing_config` 改为从 providers 收集 `{provider_name: {enabled, model, prices}}` 计价表；`compute_run_cost` 匹配键 = provider_used 找卡片（须 enabled）→ 行 model == model_used。
- 为什么：开关粒度变为卡片后，「任一卡片开启即对该 provider 计价、未开启不下发 cost 字段」是规格要求；failover 语义保持（按实际完成网关归属，与现状一致）。
- timeline / SPEC 合计的 `billing_enabled` 闸门改为「收集表非空」（有任一开启卡片才进入计价分支），单 run 计价由匹配函数自行判定未开启 → None。

### D3: 价格行保留多行模型名，预填而非锁死
新增行时 `addPrice({model: 卡片默认模型名})`；行内 4 价改为 2×2 Form.Item（label：输入/输出/缓存读/缓存写 + 单位注释），每行价格块右上角删除按钮。
- 为什么：用户修正明确保留模型名（支持同 provider 多模型价格）；预填满足「不必要填写」的诉求（单模型场景零输入），可改保留多模型能力。同卡片重复 model 由前端保存拦截 + 后端校验双保险（沿用现状 provider+model 去重的双保险模式）。

### D4: 金额约束用 antd InputNumber parser 前端拦截
`parser={(v) => v.replace(/[^\d.]/g, '')}`（配合既有 `min={0}`、`controls={false}`），非数字字符输入即被剔除，不产生非法值；后端校验兜底非负数值。
- 为什么：现状 InputNumber 允许键入中间态任意字符（blur 才纠正），用户明确要求「只能输入金额」；parser 是 antd 的标准做法，无需引入受控组件复杂度。

### D5: 保存校验重写为 per-provider，核心校验器顺带加固
`update_config` 中原 `llm.billing` 校验段改为遍历 `llm.providers[i].billing`（enabled 布尔、prices 行 model 非空、4 价非负数值非 bool、卡片内 model 不重复、billing 非 dict 报错）；`ConfigLoader._validate_llm` 顺带加入同规则子集校验（手工编辑 config.yaml 防呆，与 env 校验并列，风格一致）。
- 为什么：结构搬进核心段后，校验也应随迁；dashboard 保存校验（强）+ load-time 校验（防手工编辑坏配置）双层与现状 `llm.providers` 基础字段校验的分层一致。

## Risks / Trade-offs

- [老用户已按旧结构手工填写过 billing] → 当前主树 billing 为 null；若其他被管项目配置了旧结构，读侧收集函数对未知形态容错返回空表（fail-open 不计价，不崩溃），UI 打开即按新结构重写。
- [providers 内嵌 billing 后 agents.models 等引用 provider 的消费方受影响] → 已核实均按 `name` 引用与 `dict.get` 取值，不枚举键；`_validate_llm` 新增校验仅针对 billing 子对象自身。
- [每卡片价格区常驻表单字段变多，校验阻塞保存] → 沿用现状「空行保存前剔除」（isBlankPriceRow 改造为不含 provider 字段的版本）；开关关闭的卡片价格区不渲染不参与校验。
- [成本口径变化引起展示回归] → 未开启卡片 run 从「全局关闭无成本」变为「该卡片未开启无成本」，语义更细；`tests/test_model_billing.py` 按新结构与新谓词重写覆盖四类场景（开启计价/未开启无字段/模型不匹配 unpriced/failover 归属）。

## Migration Plan

无迁移：存量 `llm.billing` 为空。部署（daemon 重启加载新码）后首次在设置页保存即写入新结构；旧键若手工残留于 config.yaml 会被读侧忽略（不报错），下次保存自然清除。

## Open Questions

<!-- 无 -->
