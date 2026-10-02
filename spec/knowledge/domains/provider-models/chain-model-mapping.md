<!-- knowledge: capability=chain-model-mapping rev=1 sources=spec/archive/2026-09-03-improve-failover-model-mapping-ui -->

# 链模型映射（元素级模型解析）

候选链上每个元素可自带模型名，使 failover 切换 provider 的同时切换模型；解析顺序与校验口径由此能力统一约束。

## 规则

- `agents.models.<role>.provider` 列表元素支持 `str` 与 `{provider: str, model?: str}` 对象两种形态；对象元素按自身 model 请求，跨模型切换时新 attempt 携带目标元素解析出的模型名。
- 元素模型解析顺序：元素自带 `model` > 角色级 `model` > `llm.providers` 条目的 `model` 字段。条目字段仅在角色级缺省时生效；角色级已提供 model 时，无元素级 model 的链元素统一用角色级缺省。
- 角色级 `model` 非必填，语义为全链缺省；不存在「角色级 model 必须非空」的校验。
- 三者皆无法解析出模型名的元素在运行期被跳过并打 ERROR（含 `agents.models.<role>.provider[<下标>]` 与原因），不阻塞配置加载。
- 校验为逐元素模型可解析性检查：不可解析元素报 ERROR 但不阻塞加载；完全无可用元素的链校验通过——分配层返回 None，该角色走默认网关，行为与未配置一致。
- failover 链推进时以目标元素解析出的模型名注入 env；run jsonl 的 provider_marker 行含所用 model；切换导致模型名变化时 switch 日志附加 `model_changed: <old>→<new>`。

## 溯源

- 2026-09-03 improve-failover-model-mapping-ui（spec/archive/2026-09-03-improve-failover-model-mapping-ui） — 引入对象形态与元素级模型解析顺序，废除「角色级 model 强制且对全链生效」的解析与校验行为（str/list 旧形态逐字节兼容），并为切换留痕补 model_changed 语义
