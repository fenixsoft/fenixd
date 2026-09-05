# Proposal: improve-provider-billing-config

## Why

模型页签的计费配置当前是「面板级全局开关 + 与 Provider 卡片分离的价格行列表」形态：全局开关与卡片脱节，价格行要求手填 Provider 下拉与模型名（与卡片既有信息重复），4 项单价挤在单行内无标题栏、且可输入任意字符。交互成本高、数据结构与「Provider 卡片」的心智模型不一致。

## What Changes

- **计费开关下沉到 Provider 卡片**：移除面板顶部全局「启用计费信息」开关，改为每个 Provider 卡片内部独立的「启用计费」开关；价格编辑区仅在该卡片开关开启时出现。
- **价格行去掉 Provider 选择框**：价格行归属当前卡片（不再有 Provider 下拉）；**模型名输入保留**，新增价格行时自动预填该卡片「默认模型名」，可修改（支持同 Provider 多模型价格）。
- **价格布局重排**：4 项单价改为每行两项、带标题栏（Form.Item label，同「名称 / Base URL」行的布局范式）；每个价格行 = 模型名 + 2×2 价格网格。
- **金额输入约束**：4 项单价输入框只允许输入金额（数字与小数点），禁止任意字符。
- **BREAKING（存储结构）**：`llm.billing = {enabled, prices: [{provider, model, 4价}]}` 改为内嵌 `llm.providers[i].billing = {enabled, prices: [{model, 4价}]}`；顶层 `llm.billing` 段移除。当前 `.fenix/config.yaml` 中 `billing: null`，无存量价格数据，不做迁移、不做双读兼容。
- **计价闸门语义同步**：成本计算从「全局 enabled 闸门 + provider+model 匹配价格行」改为「run 实际网关 provider 的卡片 billing.enabled 开启 + 价格行 model 匹配」；未开启计费的 provider 的 run 不下发成本字段（timeline / SPEC 级合计口径随动）。

## Capabilities

### New Capabilities

<!-- spec/specs/ 与 spec/archive/ 均无已定义的计费能力（add-model-billing-cost-display 尚为活跃 change 未归档），本次为新增能力声明，并实质修订该活跃 change 中 model-billing-config 的存储与开关语义。 -->

- `provider-billing-config`: 计费配置收敛到 Provider 卡片——卡片级启用开关、价格行（模型名预填默认模型名 + 4 项单价 2×2 布局 + 金额输入约束）、存储结构内嵌 `providers[i].billing`、按卡片开关与模型匹配的计价闸门语义。

### Modified Capabilities

<!-- 无（spec/specs/ 为空，无既有已定义能力） -->

## Impact

- **后端**：`core/dashboard/data.py` —— `_load_billing_config`（改读 providers 内嵌 billing）、`compute_run_cost`（匹配逻辑改为卡片 billing + 行 model）、`get_spec_timeline` / SPEC 级成本合计的闸门与口径、`update_config` 的 `llm.billing` 校验段重写为 per-provider billing 校验。
- **核心校验（可选加固）**：`core/config.py` `_validate_llm` 顺带校验 provider.billing 子对象（enabled 布尔、prices 行 model 非空、4 价非负数值），手工编辑 config.yaml 防呆。
- **前端**：`core/dashboard/static/src/pages/settings/components/LlmProviderPanel.tsx`（开关下沉、价格区重排、金额约束、保存逻辑）、`core/dashboard/static/src/services/dashboard.ts`（`LlmProvider` 增 billing、`LlmBillingConfig`/`LlmBillingPrice` 类型调整）。
- **无需改动**：`projects/detail.tsx` 仅消费 `cost_usd` 展示字段，闸门语义变化对其透明。
- **测试**：`tests/test_model_billing.py`（61 处 billing 引用）按新结构与新匹配语义更新。
- **配置契约**：`.fenix/config.yaml` 的 `llm` 段结构变化（BREAKING，无存量数据负担）。
