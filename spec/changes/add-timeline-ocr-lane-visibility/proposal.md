## Why

ocr 并行审查车道运行期，项目详情页时间轴上只能看到一个标着「开发 Agent」的 run 节点（`impl-ocr-` 前缀落到 `impl-` 兜底标签，detail.tsx RUN_ID_PREFIX_LABEL），且 testing 停等（`_ocr_join_wait`）无任何表达——用户无法从时间轴分辨「这是代码审查车道在跑」还是「实现者又开工了」，也无法理解验证全绿后为何 spec 迟迟不推进（实证 2026-09-22 add-code-fix-manual-trigger 时间轴引发的用户疑惑）。质量门禁 Card 已有「ocr 并行审查进行中」（add-quality-gates-visibility），但时间轴与门禁两处不同源、互相不通告。

## What Changes

- **标签补正**：时间轴 run 节点的 agent 标签识别 `impl-ocr`（agent_type 真源与 `impl-ocr-` run_id 前缀兜底双路），显示「代码审查 Agent」，MUST NOT 再落 `impl-` 兜底的「开发 Agent」；既有 `impl-` 前缀（implementer/fast-track）节点标签不变。
- **车道 run 节点内容行**：车道运行中节点展示审查对象摘要（来自车道 run 转录 start 事件既有 message：分支与 `from..to` 审查区间），时间轴下拉透出，让用户直接看出「在审哪个分支哪段区间」。
- **testing 停等注记**：时间轴最新的「→ testing」状态转移节点，当质量门禁 ocr 门（gate id `code-review`）状态为 `running` 时附注记（如「ocr 审查车道进行中，完成自动推进」）；注记数据与质量门禁 Card **同一合成源**（quality_gates.py 的 ocr 门三态合成），非 running（pending/skipped/completed/unknown/无记录）MUST NOT 显示，避免历史节点噪音。

**非目标**：心跳进度实时内容展示（依赖 fix-ocr-lane-orphaned-state-misfire 的心跳事件落地后另案）；车道节点终止/取消操作（不属 run 形态，既有行为不变）。

## Capabilities

### New Capabilities

- `timeline-ocr-lane-visibility`: 时间轴对 ocr 车道的呈现契约——车道 run 节点的身份标签、内容行摘要、testing 停等注记的显示条件与同源要求。

### Modified Capabilities

（无——时间轴既有节点类型（state/admin/verify/run）的渲染行为对非 ocr 车道场景不变。）

## Impact

- `core/dashboard/static/src/pages/projects/detail.tsx`：agent 标签表补 `impl-ocr`；状态节点/run 节点渲染补注记与内容行。
- `core/dashboard/data/timeline.py`：run 节点透出车道 start 摘要；进入 testing 的最新状态节点附当前 ocr 门状态（复用 quality_gates 合成）。
- 纯展示层变更，无状态机/探针/派发链路改动；`npm run build` 产物刷新。
