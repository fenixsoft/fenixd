# Proposal: add-distill-run-work-summary

## Why

蒸馏批 run 在 SPEC 详情运行时间轴上没有工作总结：用户看到 42 分钟的 run 只有心跳行，不知道蒸馏 agent 干了什么（实证 2026-11-05 redesign-dashboard-v2-ui-mobile 蒸馏批，主提交 25737d58d 实际新增了 ADR 与能力页更新，但时间轴零呈现）。其他 agent（implementer 等）的时间轴 run 节点都有「Agent 输出总结盒」——数据源是 run 产物末行 `result` 事件的 `result` 字符串字段（`core/dashboard/data/runs.py::_run_tail_insights`）。蒸馏批的终态 result 行只有 `names/commit/rounds/folded` 结构字段、没有总结文本，读侧拿不到 summary，总结盒零渲染。

根因：蒸馏 spawn 是裸文本 `claude -p`（无 stream-json），stdout 最终消息被捕获但成功路径直接丢弃；prompt 里要求的 `KNOWLEDGE_DISTILL_DONE` 标记行也无任何 daemon 侧消费方。

## What Changes

- 蒸馏 prompt 主蒸馏完成契约升级：自查通过后输出一段结构化工作总结（蒸馏了哪些能力页/ADR、规则要点），以 `KNOWLEDGE_DISTILL_DONE` 行收尾（标记从无消费方转正为剥离锚点）
- `core/knowledge.py` 蒸馏执行器：主蒸馏 spawn 成功路径带回 stdout 文本，剥标记行、截断后装配进批次 result
- 批次终态 `result` 行新增 `"result"` 字段携带总结文本——读侧 `_run_tail_insights` 与前端时间轴总结盒**零改动**自动渲染
- 范围限定：仅主蒸馏总结；折叠子 run 不进总结（folded 计数语义不变）；失败路径不变（error 行已有 error 字段）

## Capabilities

- `knowledge-distill-run-summary`（ADDED）：蒸馏批时间轴工作总结

## Impact

- 改动面：`core/knowledge.py`（spawn 返回值扩展 + summary 提取 + 产物 close 字段）、`agents/knowledge-distill.md`（完成契约段）、`tests/test_knowledge_distill_run_artifacts.py`、`tests/test_harness_one_shot_forms.py`（`_spawn_and_wait` 三元组解包适配）
- 读侧/前端零改动（`_run_tail_insights` 既有 `result` 字段读取自动拾取；SpecTimeline 总结盒既有渲染分支自动生效）
- 归档蒸馏历史 run 的产物无此字段，时间轴按现状渲染（字段缺失不渲染，与 origin_request 同口径）
- 用户价值：蒸馏批次在时间轴上可直接读到「蒸馏了什么」，42 分钟无输出观感消除
