# add-verify-lane-throughput 提案

## Why

全历史（08-24~09-22，277 个完成 spec）耗时调查显示：验证链在关键路径上占「验证工作 221h + 验证排队 110h」，且其中最大单块是**出题（planner-plan）中位 36m 几乎纯 LLM 生成、却串行排在 implemented 之后**——而出题只读 SPEC 文档与被测应用现有源码、不读实现 diff，与 impl 并行不存在输入依赖。同时 judge 存在无治理重裁决（add-quality-gates-visibility 单 spec 连跑 3 次 judge 共 25m），verdict 缓存（verdict_cache.json）已建但实测空置，bug-found 修复轮全场景重跑放大了 120 次 bug-found 环的成本。本 SPEC 目标：把验证链从关键路径压缩出去，并消灭其内部重复劳动。

## What Changes

- **出题前置并行派发**：spec 进入 ready（或 implementing 开始）时即派发 planner-plan，与 implementer 并行执行；测试进入（implemented→testing）时若场景集已就绪且指纹有效，直接跳过阶段 1 出题、进入场景执行。出题仍只读 SPEC 文档 + 被测应用现有源码；impl 新增路由/选择器导致的场景缺口由既有 REPLAN_FEEDBACK 回环与 scenario_gate 静态校验兜底。与既有「场景冻结复用（scenario-reuse-on-reenter）」共存：并行产出的场景集在首次验证后同样进入冻结通道。
- **验证车道槽位豁免**：planner-plan / planner-judge 的派发像 spec-review 一样不受 `max_concurrent` 实现槽钳制（附豁免并发上限，防 judge 风暴挤占网关带宽）。
- **judge 重裁决治理**：同一 spec 同一验证轮内 judge 重裁决（不稳定重派/失败重派）次数达到阈值（≥2）即停止第 3 轮派发，转为人工升级告警；判定低置信时优先走证据扩充（补 evidence）而非整轮重跑；judge fast-track 复用命中率落盘可观测（读侧 summary 字段，暂不加前端组件）。
- **verdict 缓存真正用于重验**：重验轮（bug-found 修复后、gate 重试）只跑「失败场景 + 受修复影响的场景」，通过场景直接采信缓存判定；缓存失效条件固化（场景定义变化 / 修复 diff 触碰场景出处关联文件 / 验证配置变化），存疑场景 fail-closed 照跑不采信。
- **场景分片出题（低优先级）**：场景集按功能组分片、多 run 并行生成、框架合并去重；置于任务组末位，允许实现期申报 unattainable 收敛。

## Capabilities

### New Capabilities

- `parallel-scenario-planning`: 出题与实现并行的派发时机、产物就绪判定（testing 进入时跳过出题）、与场景冻结复用/REPLAN 回环的共存契约。
- `verify-lane-slot-exemption`: planner-plan / planner-judge 派发的槽位豁免规则与豁免并发上限。
- `judge-rerun-governance`: judge 重裁决计数、阈值升级、证据扩充优先、fast-track 命中率可观测。
- `verdict-cache-reverify`: 重验范围缩小（失败场景+受影响场景）、缓存键与失效条件、fail-closed 条款。

### Modified Capabilities

（无——`spec/` 下活跃能力 `quality-gates-progress`、`task-progress-phase-display` 均不受影响；本 SPEC 不改 6 道门禁判定与进度展示语义。）

## Impact

- **验证管线**：`core/pm_engine/verification/pipeline.py`（阶段 1 出题的就绪短路、重验范围裁剪）、`core/pm_engine/verification/judge_gate.py`（重裁决计数/升级/证据扩充、fast-track 命中率落盘）。
- **调度**：`core/pm_engine/dispatch/queue.py`（planner 车道槽位豁免 + 豁免上限）、`core/pm_engine/engine.py`（ready 态触发出题并行派发）。
- **缓存与场景**：`.fenix/verify-progress/<spec>/verdict_cache.json` 的读写路径（框架侧，非交付物）；`test_scenarios.json` 契约不变。
- **可观测**：读侧 summary 新增 judge 重裁决计数与 fast-track 命中率字段（数据层，无前端改动）。
- **测试**：`tests/` 下验证管线与 judge_gate 相关用例扩展 + 新增并行派发/缓存失效用例。
- **风险面**：并行出题读 pre-impl 源码锚定的路由/选择器可能因 impl 改动 UI 而失准（由 REPLAN 回环兜底，Scenario 固化该行为）；槽位豁免需带上限防失控；缓存误采信是质量红线（fail-closed 条款兜底）。
