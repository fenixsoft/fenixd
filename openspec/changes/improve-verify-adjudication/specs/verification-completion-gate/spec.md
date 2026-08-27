# verification-completion-gate 能力增量（improve-verify-adjudication）

> 本 change 在 `fix-dashboard-duration-and-verify-gate` 已交付的进度门禁基础上，为同一能力追加场景级质量裁决。既有「验证完成度放行闸门」（done == total 进度比对）语义保持不变，本文件新增其上的第二层裁决。

## ADDED Requirements

### Requirement: 场景结论质量闸门

SPEC 在验证流程已启动的情况下推进到 `done` 或 `pushed` 之前，框架 MUST 在进度门禁（done == total）之外，额外解析 `.fenix/verify-progress/<spec>/report.json` 的场景级结论并参与裁决：

- report.json 存在且所有场景 status 为 `pass` → 该层放行（是否最终放行仍取决于其它门禁）。
- 存在场景 status 为 `fail` → MUST 阻止推进，并按下方分流规则归类处理。
- report.json 缺失或不可解析，而该 SPEC 验证流程确已启动 → MUST 阻止推进（fail-closed），不得仅凭进度计数放行。

#### Scenario: 全部场景通过则该层放行

- **WHEN** 某 SPEC 验证进度为 17/17，report.json 记录 17 个场景全部 `pass`
- **THEN** 场景结论质量闸门放行，状态继续按既定路径推进（其余门禁正常生效）

#### Scenario: 仅凭进度完成不再足以放行

- **WHEN** 某 SPEC 验证进度为 15/15（done == total），但其 report.json 显示 `{"total": 15, "passed": 4, "failed": 11}`
- **THEN** 状态推进被阻止，SPEC 保持 verified，error 字段记录「验证存在 N 个失败场景」；不得进入 done/pushed

### Requirement: 失败场景噪音与缺陷分流

对质量闸门拦截到的失败场景，框架 MUST 区分工具噪音与真实产品缺陷后再决定处置路径：

- **工具噪音**判定标准：场景的 step_results 中存在 `success: false`（如步骤缺失 target 选择器而中断）、或 assertion_results 为空（断言从未执行）。此类失败不能证明产品行为错误，MUST NOT 触发 bug-found 派生 fix SPEC，MUST 写入人工升级告警（复用 human-escalation-alerts 能力），交 Administrator 按 administrator-agent 能力修正 `test_scenarios.json` 后重跑验证。
- **真实产品缺陷**判定标准：assertion_results 中存在实际执行的失败断言。此类 MUST 维持现行 bug-found 流程派生 fix SPEC，并在派生材料中携带失败的断言证据。

#### Scenario: 步骤中断类失败不派生伪 fix

- **WHEN** 某 SPEC 的 report 中场景 X 失败，其 step_results 显示在断言执行前因 `no_click_interception` 缺少 target 选择器中断，assertion_results 为空
- **THEN** 框架不触发 bug-found、不创建 fix SPEC；产生一条指向场景 X 的基础设施类告警，SPEC 滞留 verified 等待场景修正后重跑

#### Scenario: 断言实败触发真实 fix 流程

- **WHEN** 某 SPEC 的 report 中场景 Y 失败，其 assertion_results 包含至少一条实际执行且结果为 false 的断言
- **THEN** 框架将该失败归为产品缺陷，走现行 bug-found 流程派生 fix SPEC，fix 材料包含该断言的证据信息

### Requirement: verifier 结果文件缺口 fail-closed

`.fenix-run-result.json` 承载 verifier Agent 的终局结论。当结果文件缺失、JSON 无法解析或 status 字段不在白名单（verified / bug-found / plan-ready）内时，框架 MUST NOT 将其视为 verified 放行；MUST 将该 SPEC 保留在原状态、写入异常原因到 error 字段，并发送人工升级告警交 Administrator 裁决。本要求取代既有实现中「解析失败视为 verified」的 fail-open 行为。

#### Scenario: 结果文件缺失不放行

- **WHEN** 某 SPEC 验证运行结束但 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 与项目根回退位置均不存在
- **THEN** 框架不放行，SPEC 滞留原验证状态，error 字段记录「verifier 结果缺失」，且产生人工升级告警

#### Scenario: 未知状态码不放行且不误读残留

- **WHEN** 结果文件 JSON 合法但 status 为白名单外的值（如 implementer 残留的 success）
- **THEN** 框架记录警告、维持现状不发起新验证轮、产生告警等待人工裁决；不以任何默认值代替结论

#### Scenario: 明确 verified 结论正常闭环

- **WHEN** 结果文件 status 为 verified 且进度、质量两层门禁均无拦截
- **THEN** 状态正常推进到 done，既有自动审批链路不受影响
