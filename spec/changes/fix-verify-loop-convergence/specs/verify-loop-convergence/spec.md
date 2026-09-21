## ADDED Requirements

### Requirement: 无进展循环闸门（打回前）

系统 SHALL 在 bug-found 打回实现者之前，机械判定「本次失败是否为无进展循环」，命中时
MUST NOT 重派实现者，改走验证复核通道。

判据 MUST 同时满足（缺一不触发）：

- **重复性**：本 SPEC 的失败历史（`fail_history.json`）尾部连续 `repeat` 轮数 ≥ 阈值
  （`verify_engine.loop_convergence_repeat_threshold`，缺省 2）；`repeat` 语义 = 该轮
  `failed_scenarios` 与上一轮完全相同（复用 `_classify_fail_history` 既有判定）。
- **零实质变更**：本轮实现者分支在本 SPEC `## Deliverables` 声明路径上**无任何 diff**。

任一判据不可得（`fail_history` 缺失 / 声明段缺失 / git 失败）MUST fail-open 放行（按
「非循环」处理），MUST NOT 因此拦下真·产品缺陷打回。

#### Scenario: 连续同失败集 + 零实质变更 → 拒绝重派，转复核

- **WHEN** 某 SPEC 已连续 2 轮失败场景集完全相同，且本轮实现者分支在声明路径上零 diff
- **THEN** 框架 MUST NOT 重派 implementer，MUST 转而触发验证复核（见「验证复核通道」）

#### Scenario: 有实质变更 → 门不放行

- **WHEN** 失败场景集与上轮相同，但本轮实现者在声明路径上有 diff
- **THEN** 闸门 MUST 返回「非循环」，MUST 按既有 bug-found 路由重派 implementer

#### Scenario: 声明段缺失 → fail-open 放行

- **WHEN** 无法提取 `## Deliverables` 声明路径
- **THEN** 闸门 MUST 判「有实质变更」（fail-open），MUST NOT 触发循环拦截

#### Scenario: repeat 未达阈值 → 门不放行

- **WHEN** 仅 1 轮失败（无 repeat）
- **THEN** 闸门 MUST NOT 触发，按既有流程处理

### Requirement: 实质变更按声明路径度量

系统 SHALL 提供「实现者本轮是否有实质代码变更」判定，diff MUST 限定在本 SPEC
`## Deliverables` 声明的路径集上。

- 声明路径全无 diff（含「只改 tasks.md / `.fenix-run-result.json`」等元数据场景）→ 判
  「无实质变更」。
- 声明段缺失 / 提取失败 / 分支不可得 / git 失败 → fail-open 判「有实质变更」。

#### Scenario: 仅勾选任务书不算进展

- **WHEN** 实现者本轮只改 `tasks.md` 勾选与结果文件，声明路径上的交付物零 diff
- **THEN** 判定 MUST 为「无实质变更」

#### Scenario: 声明路径有改动即算进展

- **WHEN** 实现者在任一声明路径上产生 diff
- **THEN** 判定 MUST 为「有实质变更」

### Requirement: 验证复核通道

循环闸门触发后，系统 SHALL 执行一次验证复核而非重派实现者：

- 清除本 SPEC 的跨轮裁决缓存（`verdict_cache.json`）；
- 置状态回 `implemented`（`tester_run` 置空）并入队 verifier；
- 复核次数计数（`_loop_gate_attempts`）递增，预算取
  `verify_engine.loop_convergence_max_retries`（缺省 1）。

预算耗尽后仍触发循环 → MUST 置 `blocked` 并发人工升级告警（不得继续自动重验）。

#### Scenario: 首次触发清缓存并重验

- **WHEN** 循环闸门首次触发
- **THEN** 裁决缓存 MUST 被清空，状态 MUST 回 `implemented` 且 MUST 入队 verifier

#### Scenario: 预算耗尽转人工

- **WHEN** 复核预算已耗尽且循环闸门再次触发
- **THEN** MUST 置 `blocked` + 发人工升级告警，MUST NOT 继续自动重验

### Requirement: 跨轮缓存不得加固失败结论

跨轮裁决缓存命中 `product-bug` 时，若本轮实现者无实质变更，该缓存结论 MUST NOT 直接驱动
bug-found 打回：

- 该场景的归因等级 MUST 被降级为 `speculative`（复用既有降级机制），从而被投机门禁吸收。

#### Scenario: 缓存命中 + 零实质变更 → 降级

- **WHEN** 缓存指纹命中 `product-bug` 且本轮声明路径零 diff
- **THEN** 该场景归因等级 MUST 降为 `speculative`

#### Scenario: 缓存命中 + 有实质变更 → 现状不变

- **WHEN** 缓存指纹命中且本轮有实质变更
- **THEN** 归因等级 MUST 维持现状（不降级）

### Requirement: 硬上限冻结诊断贯通

三条硬上限（judge 重跑 / 验证失败轮数 / 实现预算）触发冻结时，`error` 与升级告警 evidence
MUST 携带循环诊断结论（连续同失败集轮数 + 是否零实质变更），使人工一眼区分「死循环」与
「缺修复」。

#### Scenario: judge 重跑上限冻结带诊断

- **WHEN** judge 重跑硬上限触发冻结
- **THEN** `error` MUST 含循环诊断（repeat 轮数 / 零变更结论），MUST NOT 只写「重跑超上限」

#### Scenario: 验证失败轮数上限带诊断

- **WHEN** `_verify_fail_rounds` 达上限冻结
- **THEN** 升级告警 evidence MUST 含 `repeat` / 零变更诊断

### Requirement: 升级通道失败降级

Administrator run 失败（异常或 CLI 非零退出）时，系统 MUST NOT 静默——MUST 落一条直接
人工可见的升级告警。

#### Scenario: admin run 失败落人工告警

- **WHEN** Administrator run 以异常或非零退出结束
- **THEN** MUST 落一条人工升级告警（含 run_id 与失败原因），MUST NOT 仅记 WARNING 日志