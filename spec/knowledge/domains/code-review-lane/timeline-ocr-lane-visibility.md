# 时间轴 ocr 车道可见性

<!-- knowledge: capability=timeline-ocr-lane-visibility rev=1
     sources=spec/archive/2026-09-27-add-timeline-ocr-lane-visibility -->

项目时间轴上 ocr 审查车道 run 节点的身份标签、审查对象摘要与 testing 停等注记：用户可从时间轴直接看出车道在审哪个分支哪段区间、spec 为何停等。

## 规则

- run 节点身份标签：`impl-ocr` 车道的 run 节点显示「代码审查 Agent」（无论运行中或已终态），双路命中——agent_type 识别（`impl-ocr`）与 run_id 前缀兜底（`impl-ocr-`，MUST 排在 `impl-` 兜底之前，长前缀优先）；既有 `impl-` 前缀（implementer / fast-track）run 节点的「开发 Agent」标签保持不变。
- 节点审查对象摘要：时间轴后端透出车道 run 转录 start 事件的 message（分支名与 `from..to` 审查区间，如 `8f17..a917`），前端在节点内容行展示；message 缺失或为空时不渲染内容行（容错降级，不报错），节点仅显示标签与状态。
- testing 停等注记：时间轴「最新的状态转移节点 to 为 testing」时，按质量门禁 ocr 门（gate id `code-review`）的**当前**状态决定是否附注记：
  - 状态为 `running` 时附「ocr 审查车道进行中，完成自动推进」语义注记，与质量门禁 Card 中 ocr 门的「进行中」标识一致；
  - 其余状态（pending / skipped / completed / unknown / 无记录）或该节点非最新状态节点时不附注记。
- 注记数据与质量门禁 Card 同一合成源（quality_gates.py 的 ocr 门三态合成），不另起第二套判定；注记表达当前时刻状态，非历史转移时刻状态——历史状态节点不携带与当前无关的进行时语义，避免噪音。

## 溯源

- 2026-09-27 add-timeline-ocr-lane-visibility — 新建车道时间轴可见性：run 节点「代码审查 Agent」身份双路识别（长前缀优先）、start message 审查区间摘要与缺省容错、testing 停等节点的 ocr 门当前态注记（与质量门禁 Card 同源、非历史时刻语义）。
