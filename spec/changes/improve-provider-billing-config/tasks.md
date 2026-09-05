## Deliverables

```yaml
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/LlmProviderPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/config.py
  kind: modify
- path: tests/test_model_billing.py
  kind: modify
```

## 1. 后端存储结构与计价闸门

- [ ] 1.1 `data.py` `_load_billing_config` 改造：从 `llm.providers[i].billing` 收集 per-provider 计价表 `{provider_name: {enabled, prices}}`；读失败/旧形态/异常容错返回空表（fail-open 不计价不崩溃）
- [ ] 1.2 `data.py` `compute_run_cost` 匹配语义改造：provider_used 命中且卡片 enabled 为真 → 遍历该卡片价格行按行 model == model_used 匹配；usage 缺失/无匹配/价格残缺 → None（保留「绝不回退网关回传金额」）
- [ ] 1.3 `data.py` `get_spec_timeline` 与 SPEC 级成本合计：闸门从全局 enabled 改为「计价表非空」，未开启卡片 run 不下发 `cost_usd`，unpriced 统计口径随动

## 2. 保存校验（后端）

- [ ] 2.1 `data.py` `update_config`：原 `llm.billing` 校验段重写为遍历 `llm.providers[i].billing`——enabled 布尔、prices 行 model 非空、4 项单价非负数值（排除 bool）、同一卡片内行 model 不重复；任一非法拒绝写入并列出违规项
- [ ] 2.2 `core/config.py` `_validate_llm` 新增 billing 子对象校验（同规则子集，风格与既有 env 校验一致），手工编辑 config.yaml 防呆

## 3. 前端类型与模型页签重排

- [ ] 3.1 `services/dashboard.ts`：`LlmProvider` 增 `billing?: ProviderBilling`（enabled + prices 行含 model 与 4 价）；移除顶层 `LlmBillingConfig`/`LlmBillingPrice` 旧形态引用
- [ ] 3.2 `LlmProviderPanel.tsx`：移除面板级全局「启用计费信息」开关；每个 Provider 卡片标题区/内部加「启用计费」Switch；价格编辑区仅该卡片开关开启时渲染
- [ ] 3.3 价格行重构：去掉 Provider Select；新增行 `addPrice` 自动预填当前卡片「默认模型名」（可修改）；4 项单价改为每行两项带标题栏（Form.Item label：输入/输出/缓存读/缓存写 + $/1M tokens 单位说明）；`InputNumber` 加 parser 仅允许数字与小数点；`isBlankPriceRow` 与同卡片 model 重复前端拦截同步调整
- [ ] 3.4 `handleSave` 组装新结构：价格行写入 `providers[i].billing = {enabled, prices}`，不再产出顶层 `llm.billing`；关闭计费的卡片不携带生效价格行

## 4. 测试与验证

- [ ] 4.1 `tests/test_model_billing.py` 按新结构与新匹配语义重写：卡片开启且模型匹配现算 cost_usd / 未开启卡片 run 无 cost 字段 / 模型不匹配 unpriced 计数 / failover 按实际网关归属 / 保存校验非法拒绝（负数单价、空模型名、卡片内重复 model）/ 保存后 config.yaml 落盘新结构且无顶层 llm.billing
- [ ] 4.2 验证收口：billing 相关 pytest 全绿 + 前端构建通过；dashboard 模型页签手工核对——全局开关已移除、卡片开关显隐价格区、新增行预填默认模型名、单价仅可输入金额、2×2 标题栏布局、保存后 `.fenix/config.yaml` 为内嵌结构
