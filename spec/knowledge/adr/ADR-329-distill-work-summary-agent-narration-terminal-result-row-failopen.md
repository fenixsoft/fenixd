# ADR-329：蒸馏工作总结为 agent 自述、经终态 result 行承载、标记行剥离锚 fail-open

date: 2026-11-06
status: accepted

## Context

蒸馏批 run 产物是合成事件流（started/heartbeat/round/result），SPEC 详情时间轴 run 节点总结盒的数据源是终态 result 事件的 `result` 字符串字段；蒸馏 spawn 为裸文本 `claude -p`，成功路径 stdout（即 agent 最终消息）在返回值中被丢弃，prompt 要求的 `KNOWLEDGE_DISTILL_DONE` 标记行无 daemon 消费方——蒸馏批在时间轴上零内容呈现，长批次观感「什么都没输出」。总结从哪来、放在哪、标记行算什么，需要一次定调。

## Decision

蒸馏工作总结必须是主蒸馏 agent 的自述（daemon 侧 git show --stat 合成摘要被否：非 agent 自陈、无规则语义）；载体复用既有终态 result 行，新增 `result` 字符串字段（新增 summary 事件类型被否：读侧不解析未知键、需读侧+前端双端改动），字段名由读侧契约钉死，执行器内部 dict 键名用 `summary`。文本取 spawn 成功路径 stdout，剥离尾部 `KNOWLEDGE_DISTILL_DONE` 后整段装配、2000 字符截断兜底。标记行从无消费方的提示词契约转正为剥离锚点，但不作为成功判据——成功判据仍是退出码 + validate_knowledge，标记缺失或 stdout 为空 fail-open 不写字段；折叠子 run 不进总结（folded 计数已承载其语义），失败路径诊断形态不变。

## Consequences

读侧 `_run_tail_insights` 与前端总结盒零改动自动生效；历史蒸馏产物无 result 字段按缺失不渲染（与 origin_request 同口径）；spawn 返回值扩为三元组 `(ok, err, stdout)`，全仓解包点一次适配。代价：总结质量只受 prompt 完成契约与截断常量约束、无格式校验（与真相源散文语义同款取舍：机械校验拦格式不拦内容）；后续给蒸馏产物扩充结构化内容（如改动文件清单）不得塞进 `result` 字符串，须走字段扩展并同步读侧契约。
