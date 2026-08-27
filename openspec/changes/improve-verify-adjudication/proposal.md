# Proposal: improve-verify-adjudication

## Why

2026-08-27 的 add-dashboard-spec-doc-tabs-and-info-clear 事件实证了验证裁决链的三重漏洞：verify 报告 15 个场景仅通过 4 个（其中 `clear-button-clears-error-then-row-disappears` 恰好命中后来在生产环境复现的真实产品缺陷），spec 却照常推进到 pushed。根因有三：① 验证闸门只比对进度计数 `done == total`，report.json 的场景级 pass/fail 从不参与裁决；② `.fenix-run-result.json` 缺失或状态不在白名单时一律视为 verified（fail-open），Agent 可静默绕过验证；③ fix 链覆盖缩水——add(15 场景) → fix(17) → fix-fix(6) 每轮验证范围越缩越小，首轮暴露的回归场景没有任何机制要求在后续轮重跑。

## What Changes

- **报告质量裁决进闸门**：`verified → done` 在进度门禁之外新增场景级结论校验——解析 `.fenix/verify-progress/<spec>/report.json` 的场景状态；存在失败场景时区分两类：
  - **工具噪音**：步骤中断导致断言从未执行（如 `no_click_interception` 缺 target）、环境性不可达等基础设施缺陷 → 不判 bug-found，写入人工升级告警交 Administrator 修正 `test_scenarios.json` 后重跑验证；
  - **真实产品缺陷**：断言实际执行且失败 → 维持现行 bug-found 流程派生 fix SPEC。
- **result 文件 fail-closed**：`.fenix-run-result.json` 缺失、JSON 非法或 status 不在白名单时，不再默认视为 verified 放行，而是标记异常并升级 Administrator 裁决（复用 human-escalation-alerts 能力）；仅有明确 `verified` 结论时才推进。
- **fix 轮回归继承**：`pm_engine` 创建 fix SPEC 时把父 SPEC 报告中失败与未执行的回归场景注入该 fix SPEC 的验证任务集；fix SPEC 推进前必须证明这些场景已覆盖并闭环，杜绝后续轮次以更小的场景集「全绿」通关。

## Capabilities

### New Capabilities
- `fix-chain-regression-inheritance`: fix SPEC 创建时继承父 SPEC 失败/未执行回归场景为必测项，并在放行闸门处强制其闭环。

### Modified Capabilities
- `verification-completion-gate`: 从纯进度门禁（done==total）扩展为质量门禁——增加 report.json 场景结论校验、噪音/真缺陷分流规则、result 文件缺口的 fail-closed 升级语义。

## Impact

- **代码**：`core/pm_engine.py`（`_check_verification_gate`、`_read_verifier_result`、`_on_spec_verified`、`_do_spec_bug_found` / `_ensure_fix_spec_files`）；`core/dashboard/data.py` 的 report.json 解析逻辑复用；`core/agent_runner.py` 中 verifier 与 administrator prompt 的新产物路径约定。
- **流程行为**：验证有失败场景的 SPEC 将滞留 verified 并产生告警/fix，而非静默推 done/pushed——预计阻塞量上升，需要 Administrator 处置通道正常工作（依赖 administrator-agent 与 alerts 能力）。
- **兼容**：存量 pushed/done SPEC 不回溯；进度文件缺失的老路径行为不变。
