# verification-completion-gate 能力增量（add-inplace-bug-repair）

> 本变更修改 improve-verify-adjudication 交付的「失败场景噪音与缺陷分流」：真实产品缺陷的处置由「派生 fix SPEC」改为「原地打回父 SPEC」（见 inplace-bug-repair 能力）。噪音分流与 fail-closed 语义保持不变。

## MODIFIED Requirements

### Requirement: 失败场景噪音与缺陷分流

对质量闸门拦截到的失败场景，框架 MUST 区分工具噪音与真实产品缺陷后再决定处置路径：

- **工具噪音**判定标准：场景的 step_results 中存在 `success: false`（如步骤缺失 target 选择器而中断）、或 assertion_results 为空（断言从未执行）。此类失败不能证明产品行为错误，MUST NOT 触发原地打回，MUST 写入人工升级告警（复用 human-escalation-alerts 能力），交 Administrator 按 administrator-agent 能力修正 `test_scenarios.json` 后重跑验证。
- **真实产品缺陷**判定标准：assertion_results 中存在实际执行的失败断言。此类 MUST 执行 inplace-bug-repair 能力定义的原地打回处置（递增失败轮数、重置 implementing、追加修复任务），修复依据为父 SPEC 的 verification-report.md 及其携带的失败断言证据；MUST NOT 创建 fix-* 子 SPEC。

#### Scenario: 步骤中断类失败不触发打回

- **WHEN** 某 SPEC 的 report 中场景 X 失败，其 step_results 显示在断言执行前因 `no_click_interception` 缺少 target 选择器中断，assertion_results 为空
- **THEN** 框架不触发原地打回、不修改父 SPEC 状态；产生一条指向场景 X 的基础设施类告警，SPEC 滞留 verified 等待场景修正后重跑

#### Scenario: 断言实败触发原地打回

- **WHEN** 某 SPEC 的 report 中场景 Y 失败，其 assertion_results 包含至少一条实际执行且结果为 false 的断言
- **THEN** 框架将该失败归为产品缺陷，执行原地打回处置，父 SPEC 的「验证修复」任务段引用的 verification-report.md 包含该断言的证据信息
