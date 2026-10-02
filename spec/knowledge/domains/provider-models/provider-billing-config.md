<!-- knowledge: capability=provider-billing-config rev=1 sources=spec/archive/2026-09-11-improve-provider-billing-config -->

# provider 计费配置（卡片级开关与内嵌存储）

计费配置收敛到 provider 卡片：卡片级启用开关、价格行归属卡片编辑、存储内嵌于 provider 对象。

## 规则

- 每个 provider 卡片拥有独立「启用计费」开关；不存在面板级全局计费开关。价格编辑区仅在该卡片开关开启时出现；开关关闭的卡片不参与任何成本计算。
- 价格行归属其所在 provider 卡片，行内不提供 provider 选择框；新增价格行时模型名自动预填该卡片「默认模型名」字段当前值，可修改以支持同 provider 多模型价格。
- 单价输入仅接受正数金额（数字与小数点），其他字符不产生非法值；四项单价以每行两项、带标题栏（含 $/1M tokens 单位说明）的网格布局呈现；模型名与四项单价均为必填。
- 存储内嵌于 provider 对象：`llm.providers[i].billing = {enabled: bool, prices: [{model, input_per_million, output_per_million, cache_read_per_million, cache_creation_per_million}]}`；不存在顶层 `llm.billing` 段，亦无旧结构迁移或双读兼容（存量配置 billing 为空）。
- 开关关闭的卡片保存时不写入价格数据（billing 缺省，或 enabled: false 且无生效价格行）。
- 保存时后端按 provider 校验 billing 子对象：enabled 为布尔；prices 为列表且每行 model 为非空字符串、四项单价为非负数值（bool 除外）、行 model 在同一卡片内不重复；任一非法拒绝写入并在错误信息中列出违规项（如 `providers[0].billing.prices[0]` 相关描述），不静默忽略。
- 计价闸门、成本公式与 failover 归属口径见 [model-billing-config](model-billing-config.md)。

## 溯源

- 2026-09-11 improve-provider-billing-config（spec/archive/2026-09-11-improve-provider-billing-config） — 将计费从面板级全局开关收敛为 provider 卡片级开关、存储从顶层 llm.billing 内嵌进 provider 对象，固化价格行预填、输入约束与按卡片校验契约
