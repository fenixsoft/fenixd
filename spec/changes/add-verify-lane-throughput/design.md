# add-verify-lane-throughput 设计

## Context

验证链三阶段（出题 planner-plan → 场景执行 → judge planner-judge）全部串行排在 implemented 之后。实测（09-22 归档 run 流）：出题中位 36m、几乎纯 LLM 生成（planner-plan 4 run 生成时间合计 102m / 工具仅 4m）；judge 单 spec 曾连跑 3 次（13m+7m+5m）；`.fenix/verify-progress/<spec>/verdict_cache.json` 机制已建但实测条目数为 0（空置）。全历史验证排队 110h + 验证工作 221h。

既有可复用机制：

- **槽位豁免先例**：`core/pm_engine/dispatch/queue.py` 中 `slots_full` 判定已对 `spec-review` 车道放行（两处），本 SPEC 的 planner 车道豁免沿用同一模式。
- **场景冻结复用（scenario-reuse-on-reenter）**：`pipeline.py` 阶段 1 已有 `test_scenarios.json` 存在且指纹有效即跳过出题的分支（含契约迁移、corrupt 回落出题）。并行出题的「就绪短路」本质是把同一分支的命中时机提前。
- **REPLAN_FEEDBACK 回环**：场景未通过验收时 planner 读 `REPLAN_FEEDBACK.md` 逐条修正后全量重出（`agents/planner-plan.md` 已定义）。
- **scenario_gate**：场景静态校验（空场景白洗门、非归因信号降 WARNING）已治理，为并行出题的产物质量提供既有闸门。
- **judge fast-track 复用门**：`pipeline.py` `_dispatch_judge_or_reuse` 已有快道未命中才真实派发 judge 的结构，重裁决治理在其上加计数与阈值。

## Goals / Non-Goals

**Goals:**

- spec ready 即出题，implemented→testing 零出题等待（场景集已就绪时阶段 1 直接短路）。
- planner-plan / planner-judge 派发不再挤占实现槽。
- judge 同轮重裁决有上限与人工升级出口，fast-track 命中率可观测。
- 修复轮重验只跑失败场景 + 受影响场景，缓存判定可采信且有失效条件。

**Non-Goals:**

- 不改 6 道质量门禁判定与 Dashboard 展示（另一 SPEC 管 impl 门禁）。
- 不改场景执行引擎（Playwright 断言逻辑）本身。
- 不做前端组件（judge 指标本期只落读侧数据层字段）。
- 不改出题 prompt 的场景覆盖规则与选择器规范。

## Decisions

1. **并行出题的派发时机挂在 ready 态进入**（而非 implementing 开始）：impl 有排队窗口（全历史实现排队 893h），ready 即出题能让出题在 impl 排队期间完成， implemented 时场景集必然就绪。派发主体是 pm_engine（spec 状态迁移到 ready 的事件钩子处注册 planner-plan 派发），产物仍写 `.fenix/verify-progress/<spec>/test_scenarios.json`（框架侧车道产物，随既有拷回机制落主树）。备选「implementing 开始时派」被否：出题与 impl 完全并行时才最大化收益，且出题占 LLM 生成、与 impl 的工具执行错峰，网关争用低于串行。

2. **阶段 1 就绪短路的判定 = 既有冻结复用分支直接命中**：testing 进入时 `test_scenarios.json` 存在且指纹/契约校验通过 → 走现有复用分支（零新逻辑）；产物损坏/契约不匹配 → 现有回落出题通道原样生效（此时并行产物作废、串行重出）。**不为并行产物新增独立校验路径**——同一文件、同一校验，避免双标准。

3. **并行出题读 pre-impl 源码是可接受偏差**：出题读被测应用现有源码锚定路由/选择器，impl 若改动 UI 结构则部分场景失准。兜底链：场景执行失败 → bug-found/REPLAN 既有回环修正；scenario_gate 静态校验拦截臆测选择器。备选「等 impl 完成再出题但移出关键路径预跑 dry-run」被否：复杂度高且仍串行。风险由 Scenario 固化（并行产物在 REPLAN 时全量修正）。

4. **槽位豁免带上限**：planner-plan / planner-judge 豁免 `max_concurrent` 钳制，但新增豁免车道并发上限（同时最多各 1 个 planner-plan 与 1 个 planner-judge 在飞），防 judge 风暴与出题分片（本 SPEC 低优先级任务）挤占网关。豁免实现复用 spec-review 先例的 `slots_full` 放行点，上限用独立计数器，不走 `max_concurrent`。

5. **judge 重裁决治理阈值 = 同 spec 同验证轮内 ≥2 次重裁决即停**：第 3 次派发前检查计数，达标则不发、转人工升级告警（复用既有 human-escalation-alert 通道）并保持 spec 可重试状态。低置信判定优先「证据扩充」：仅当 judge 产物缺 evidence 或 evidence 截断可补时触发补证重判（局部重跑），整轮重裁决是最后手段。计数器随验证轮重置（新一轮 bug-found 修复后从零计）。fast-track 命中率 = 快道复用次数 / (快道复用 + 真实派发)，落读侧 summary 字段（数据层），前端不做。

6. **verdict 缓存键 =（场景 id, 场景内容指纹, 被测构建指纹, 验证配置指纹）**：四元组全等才采信缓存。失效条件固化：①场景定义变化（内容指纹不匹配）；②修复 diff 触碰场景出处关联文件（场景 description 出处标注的文件:行号 所在文件与 fix diff 文件集求交）；③验证配置变化（配置指纹）。重验场景集 = 失败场景 ∪ 受影响场景 ∪ 其 depends_on 前置链；其余场景采信缓存判定写报告。**存疑即 fail-closed**：出处标注缺失/指纹不全的场景不采信缓存、照跑。缓存写入时机不变（验证引擎判定后），本 SPEC 只加读侧消费与失效判定。

7. **分片出题放任务组末位、允许 unattainable 申报**：按场景功能组（SPEC 功能点维度）切分为 N 个分片 run 并行生成、框架合并去重（id 冲突时后到者重编号并记 WARNING）。若实现期发现与并行派发编排冲突（如豁免上限挡住分片并发），可申报 unattainable 收敛，不构成打回理由。

## Risks / Trade-offs

- **并行出题产物失准**（pre-impl 源码锚定）→ REPLAN 回环 + scenario_gate 静态校验兜底；观测指标：REPLAN 触发率对比（上线后人工观察）。
- **豁免车道挤占网关带宽** → 上限 1+1；LLM 生成与 impl 工具执行天然错峰。
- **缓存误采信（质量红线）** → 四元组全等 + 出处关联文件交集 + fail-closed 三重防线；quality-gates 面板不受影响（门禁判定源不在本 SPEC 范围）。
- **judge 停派可能导致验证轮悬置** → 升级告警必发 + spec 保持可重试（人工处理后重入 testing 正常走）。
- **与 add-pipeline-throughput-governance 并行实现触碰同文件**（queue.py / judge_gate.py）→ 不同 hunk 区域，git 可自动合并；若冲突由人工按混合工作区手术式提交处方处理。
