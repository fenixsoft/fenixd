# Design: improve-failover-model-mapping-ui

## Context

add-provider-failover 的模型解析存在设计落地偏差：spec 要求"provider 项自身 model 兜底"，但 `_validate_agent_models` 强制角色级 model 非空，使兜底分支不可达；链条目仅支持字符串。跨供应商场景（同能力不同模型名）因此无法成链。UI 侧 models 表单为单值 select，`config_patch` 保存路径会把表单单选序列化回写，存在覆写链的风险。

## Goals / Non-Goals

**Goals:**
- 链元素携带自己的模型名；角色级 model 变为可选缺省
- 校验保证"链上每项都可解析出模型名"而非"角色级 model 非空"
- UI 可完整编辑链（含对象形态）且保存不丢链

**Non-Goals:**
- 不做请求级/流中切换；不改冷却与熔断语义
- 不做模型能力/上下文长度预检（跨模型 resume 的上下文兼容由配置者负责，日志留痕）

## Decisions

- **D1 链元素形态：`str | {provider: str, model?: str}`。** str 元素模型 = 角色级 model（若缺省）→ 不可解析则该项校验失败；对象元素 model 缺省时同样回退角色级 → provider.model 字段 → 仍无则校验失败（ERROR 指明元素下标）。yaml 加载层把对象统一规范化为 (provider, model|None) 二元组列表再进入校验与分配。
- **D2 校验规则替换。** 删除"角色级 model 必须非空"；新增"链上每个元素解析结果非空"。解析顺序：元素自带 model > 角色级 model > llm.providers 条目的 model 字段。三者皆空 → 校验 ERROR（不阻塞加载，与未知名字同哲学：运行期跳过该元素并打 ERROR）。完全无可用元素的链返回 None 走默认网关（保持现状）。
- **D3 failover 集成保持元素整体切换。** 候选链类型从 list[(provider_dict, model)] 不变（逐元素模型在分配层解析），切换即取下一元素的 (provider, model) 二元组注入 env；`--resume` 照常携带（会话历史本地，跨模型续跑由配置者担责）。provider_marker 增加 model 字段（本就有 model_used，补充 marker 行含模型），switch 日志当 model 变化时附加 `model_changed: <old>→<new>`。
- **D4 UI 数据流。** GET 配置接口对 agents.models.<role>.provider 输出规范化链 JSON（对象形态数组，含解析后的 model 以便回显）；前端每角色渲染可排序行列表（上移/下移/删除 + 添加行：provider 下拉取 llm.providers + model 输入框占位显示角色级缺省）；保存时把行列表序列化：单行且无元素级 model → str（向后兼容）；否则对象数组。
- **D5 防覆写。** config_patch 组装时 agents.models 段以"表单当前状态"为准整体替换该角色条目（不允许只传部分字段造成 list/str 混拼）；后端 patch 应用前用 _validate_agent_models 校验失败则拒绝该次保存并返回错误信息（400），前端 toast 展示——保证脏配置进不了 config.yaml。

## Risks / Trade-offs

- [对象形态增加配置复杂度] → UI 提供可视化编辑；文档注释给出三种形态示例；str 单元素路径保持最简
- [跨模型 resume 上下文失配] → 不预检（无法可靠预判），switch 日志留痕供事后归因
- [UI 保存与手工 YAML 编辑竞争] → 保存走整体校验 + 原子写（既有 config 保存路径），失败不落盘

## Migration Plan

纯增量，str/list 旧形态逐字节兼容。随 daemon 重启生效；回滚 revert。

## Open Questions

- 无
