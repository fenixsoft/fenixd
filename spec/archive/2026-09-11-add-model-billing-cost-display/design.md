# Design — add-model-billing-cost-display

## Context

- 现状：`add-cost-observability` 已落地 per-spec token 累计（STATE `_tokens_in`（含 cache 合并）/`_tokens_out`/`_cache_read_tokens`/`_cache_creation_tokens`）与「网关回传 `cost_usd` 才展示金额」口径；实际网关（inferaiapi/bigmodel/aliyun）均不回传，金额展示长期「成本不可用」。
- 每 run 的 usage 已存在于 run 产物（`.fenix/runs/*.jsonl` 尾部 result 事件的 `usage` 字段），实际模型已有留痕（provider_marker 事件 `model@provider`）；`data.py::_run_tail_insights` 已在读尾窗解析这两类事件——**成本计算无需 runner 侧任何改动与新增持久化**。
- 设置页「模型」页签（tab key `llm`）由 `LlmProviderPanel` 管理 `llm.providers`；`read_config` 对 `llm` 段整体透传、`write_config` 走 `_deep_merge_managed` + 局部校验，新增 `llm.billing` 子键天然随链路读写。
- 配置热更新（30s mtime 检测）使价格改动即时生效，无需重启 daemon。

## Goals / Non-Goals

**Goals**
- 设置页配置按 provider+model 的四项单价（可选，总开关）
- run 级成本本地计算（含历史 run，零迁移、零新持久化）
- SPEC 详情成本合计 + 时间轴 run 节点成本标注
- 展示口径统一切换为「只认本地计算」

**Non-Goals**
- 不改 `core/agent_runner/`（usage/模型留痕已就位）
- 不动预算告警、token 累计与 STATE `_cost_usd` 内部累计（仅退出展示）
- 不改概览页治理区（`_token_usage_view` 的 `cost_usd/cost_available` 字段语义保持；口径统一留待后续 spec）
- 不做缓存写 1.25× 业界倍率自动推导——价格由用户显式配置
- 不做多币种（统一 $，与 `cost_usd` 既有量纲一致）

## Decisions

### D1 价格配置结构与存放位置：`llm.billing`
```yaml
llm:
  billing:
    enabled: false
    prices:
      - provider: inferaiapi.com
        model: deepseek-v4-flash
        input_per_million: 0.27
        output_per_million: 1.10
        cache_read_per_million: 0.07
        cache_creation_per_million: 0.28
```
- 放 `llm` 段内：`read_config` 对 llm 整体透传、`write_config` 的 `_deep_merge_managed` 已覆盖，前端 `ConfigData.llm` 增可选字段即可；备选「providers[].pricing 嵌套」会改变 providers 结构并波及 `_validate_llm`，弃。
- 四项全填才有效（spec 已定）：缺项会导致成本静默低估，「只认本地计算」口径下不可接受。
- 校验挂 `write_config`（同 `verify.*` patch 前置校验模式）：enabled 布尔、provider ∈ llm.providers、model 非空、四价非负数值、provider+model 去重；非法返回 400 不落盘。

### D2 成本计算数据源：扩展 `_run_tail_insights`，零新持久化
- `parse_chunk` 增解析 result 事件的 `usage`（四分项）——result 事件是流终态、必在 64KB 尾窗内；provider_marker 回扫逻辑已有。
- 返回结构增 `usage`（缺省 None）与既有 `llm`（`model@provider`）配套；**历史 run 立即可算，归档 run 经 `include_archive` 同样覆盖**。
- 备选「run 收工时写 usage 侧车文件」：需改 runner、且历史 run 永久缺失，弃。

### D3 单价匹配：provider+model 精确匹配，计算入口单一
- `data.py` 新增纯函数 `compute_run_cost(usage: dict, model_used: str, provider_used: str, billing: dict) -> float | None`：按 `billing.prices` 中 provider+model 精确匹配，四分项求和；未匹配/开关关/usage 缺失 → None。
- 匹配键以 run 产物 marker 为准（failover 实际生效的网关与模型），非配置首选——failover 后成本归属仍精确。
- 单一入口便于测试与未来复用（如治理区切换口径）。

### D4 展示层接线
- **时间轴**：`get_spec_timeline` 的 run 节点由 `_run_tail_insights` 结果附 `cost_usd`（None 不下发），前端 `detail.tsx` 运行节点头部加成本 Tag（可计价才渲染，样式同 llm Tag）。
- **SPEC 详情**：`get_spec_detail` 汇总 timeline 内可计价 run → `cost_summary: {computed_usd: float, unpriced_runs: int, priced_runs: int}`；全不可计价时 `computed_usd=None`。前端「项目信息」Descriptions 增「成本」行：显示合计 + 「含 N 个未计价 run」附注，或「成本不可用」。
- **口径切换**：`_token_usage_view` 保留字段不动（Non-Goal，治理区不变）；spec 详情既有 token 行不动，成本为新增行。
- 计费开关关闭时 detail/timeline 不下发成本字段（前端自然不渲染），非靠前端二次判断。

### D5 金额精度与格式
- 后端保留 float 原值，前端统一 `$<x.xx>`（< $0.01 显示 `$0.001` 三位，避免小额全零）；不做四舍五入入账——成本仅为展示口径。

## Risks / Trade-offs

- [尾窗 64KB 内 result 事件被超大单条输出挤出] → result 事件是流终态且结构固定（不含全部对话内容），实测远小于尾窗；`_run_tail_insights` 既有 summary 提取同依赖此假设，风险一致。
- [provider_marker 回扫上限内未命中 → llm 为空] → 该 run 判为不可计价（None），不猜模型不误算；与既有「llm Tag 留空」行为一致。
- [价格行拼写错误（provider/model 打错）→ 静默全部不可计价] → spec 详情「含 N 个未计价 run」附注让规模可见；前端价格行 provider 用 Select（选项来自 llm.providers）从源头防拼错。
- [用户在 run 进行中改价 → 同 spec 前后 run 单价不一致] → 每次渲染按当前配置现算，语义为「按现价重估」而非「历史成交价」；design 明示此口径，不做快照。
- [STATE `_cost_usd`（网关回传）与本地计算并存造成口径困惑] → 展示层全面切换本地计算；STATE 内部累计不动（预算/审计仍可用），治理区切换留待后续 spec。
- [四项全填的严格校验提高配置门槛] → 单价缺项会静默低估成本，与「金额展示不伪造」精神冲突；宁严勿错。

## Migration Plan

无数据迁移：配置段新增（缺省关闭）、run 成本读时现算。回滚 = 还原前端与 data.py 改动；`llm.billing` 残留配置无副作用（无人消费）。

## Open Questions

（无——四个口径决策已由用户确认：provider+model 粒度 / 总开关+价格区 / 只认本地计算 / 增加缓存写价字段。）
