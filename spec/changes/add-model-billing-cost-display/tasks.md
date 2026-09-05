# Tasks: add-model-billing-cost-display

实现依据（实施 agent 必读）：
- 能力定义 `specs/model-billing-config/spec.md`（配置侧）与 `specs/cost-observability/spec.md`（展示侧，MODIFIED「金额展示不伪造」口径）；设计决策 design.md D1-D5
- 成本数据源：`.fenix/runs/*.jsonl` 尾部 result 事件 `usage` + provider_marker（`data.py::_run_tail_insights` 已有解析骨架，扩展而非新建）
- 配置链路：`core/dashboard/data.py::write_config` 前置校验（同 `verify.*` patch 模式）+ `read_config` llm 段透传；新配置键必须带界面（llm.billing → LlmProviderPanel）
- 真实夹具：`.fenix/runs/impl-v2-config-page-*.jsonl`（usage 结构样本，add-cost-observability 4.2 已验证）
- 口径铁律：只认本地计算；未计价显示「成本不可用」，绝不回退网关回传金额，绝不显示 $0.00

## Deliverables

```yaml
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/LlmProviderPanel.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: tests/test_model_billing.py
  kind: new
```

## 1. 配置层：llm.billing 校验与回显

- [ ] 1.1 `write_config` 增 billing patch 前置校验：`enabled` 布尔；每行 provider 引用必须存在于 `llm.providers`；`model` 非空；四项单价（input/output/cache_read/cache_creation_per_million）为非负数值；provider+model 不重复。任一非法拒绝写入并返回明确错误（不静默忽略），错误信息列出违规行
- [ ] 1.2 回显验证：`read_config`（user/project 两 scope）与 `read_effective_config` 对 `llm.billing` 的透传/合并符合预期（llm 段整体透传应天然覆盖，确认项目级覆盖用户级行为）
- [ ] 1.3 单测（tests/test_model_billing.py）：校验拒绝矩阵（负数/非数值/缺项/重复/未知 provider/enabled 非布尔）、合法写入落盘、读侧回显

## 2. 成本计算核心

- [ ] 2.1 `_run_tail_insights` 的 parse_chunk 增解析 result 事件 `usage` 四分项，返回结构增 `usage` 字段（无 result 事件 → None；既有 summary/llm 行为不变）
- [ ] 2.2 新增纯函数 `compute_run_cost(usage, model_used, provider_used, billing) -> float | None`：按 provider+model 精确匹配 `billing.prices`，四分项求和；开关关/未匹配/usage 缺失 → None（design D3，单一计算入口）
- [ ] 2.3 单测：usage 提取（真实 jsonl 夹具回归 + 无 result 尾窗 + 归档 run）、成本计算（精确匹配/未匹配/开关关/四分项数值核对）

## 3. 时间轴与 SPEC 详情接线

- [ ] 3.1 `get_spec_timeline` run 节点附 `cost_usd`（经 compute_run_cost 现算；None 不下发；计费开关关闭时整条时间轴不下发成本字段）
- [ ] 3.2 `get_spec_detail` 增 `cost_summary: {computed_usd, priced_runs, unpriced_runs}`（timeline 内 run 汇总；全部不可计价 → computed_usd=None）
- [ ] 3.3 单测：时间轴节点成本字段（可计价/未计价/开关关）、detail 汇总（混合计价附注/全未计价）

## 4. 前端

- [ ] 4.1 `services/dashboard.ts` 类型：`llm.billing`（enabled/prices 行）、timeline run 节点 `cost_usd`、detail `cost_summary`
- [ ] 4.2 `LlmProviderPanel`：页签顶部「启用计费信息」Switch + 开启后每 Provider 卡价格行编辑区（provider 用 Select 选项取自 llm.providers 防拼错、模型名必填、四项全填前端校验、重复行前端拦截）；随既有「保存」一并提交 `{llm: {providers, billing}}`
- [ ] 4.3 `detail.tsx`：项目信息区增「成本」行（$x.xx 合计 + 「含 N 个未计价 run」附注 / 全未计价「成本不可用」）；时间轴可计价 run 节点头部成本 Tag（样式同 llm Tag，不可计价不渲染）

## 5. 构建与验证

- [ ] 5.1 前端构建通过（npm run build），后端 pytest 全绿（含新增 tests/test_model_billing.py）
- [ ] 5.2 Dashboard 冒烟：设置页开启开关→填价格→保存→刷新回显；SPEC 详情成本行；时间轴可计价节点成本 Tag；关开关后三处全部消失
