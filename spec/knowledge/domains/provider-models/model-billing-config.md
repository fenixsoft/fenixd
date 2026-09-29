<!-- knowledge: capability=model-billing-config rev=1 sources=spec/archive/2026-09-11-add-model-billing-cost-display -->

# 模型计费单价与成本口径

按「provider × 模型」维护四项单价，并约定 run 成本的计算闸门与归属口径；配置载体与编辑交互见 [provider-billing-config](provider-billing-config.md)。

## 规则

- 价格行按 provider + model 建模：每行含模型名（必填非空）与四项单价——每百万输入 token 费用（`input_per_million`）、每百万输出 token 费用（`output_per_million`）、缓存命中 token 费用（`cache_read_per_million`）、缓存写入 token 费用（`cache_creation_per_million`），单位 $/1M tokens。
- 同一价格行的四项单价必须全部填写（非负数值），不支持部分填写；同一 provider + model 组合不得重复。
- 成本现算：单 run 成本 `cost_usd = Σ(token/1M × 对应单价)`，仅当 run 实际驱动网关（provider_marker 的 provider）对应卡片计费开启，且该卡片存在 model 等于 run 实际模型的价格行、usage 四分项齐全时计算。
- 不可计价不下发：未开启计费的 provider、无匹配价格行、usage 缺失或价格字段残缺的 run 不下发 cost 字段（成本不可用），不得回退网关回传金额；此类 run 以 unpriced_runs 计数。
- SPEC 级成本合计仅累计已计价 run；failover 切换后成本按实际完成 run 的网关（及其价格与 usage）归属，与切换前 provider 配置无关。
- 计费配置随 `/api/config` 既有读写链路持久化与回显（含项目级 effective 视图），无需新增端点；写入校验失败必须拒绝并返回错误，不静默忽略。

## 溯源

- [2026-09-11 add-model-billing-cost-display](spec/archive/2026-09-11-add-model-billing-cost-display/) — 引入按 provider+model 的四项单价价格行模型与完整性校验，确立「全部填写才合法、重复组合拒绝」的口径（存储结构其后收敛进 provider 对象内嵌，见 provider-billing-config 页）
