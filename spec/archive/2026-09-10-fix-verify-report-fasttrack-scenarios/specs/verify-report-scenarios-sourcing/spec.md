# verify-report-scenarios-sourcing 能力增量（fix-verify-report-fasttrack-scenarios）

> 验证报告合成场景明细的数据源契约：`report.json` 顶层 `scenarios` 优先；缺失时回退 fast-track 裁决结果文件的 `verification.scenarios` 嵌套键。保证 fast-track SPEC 的合成「验证报告」场景表与 Dashboard「场景结果」页签同源、完整。

## ADDED Requirements

### Requirement: 场景明细表数据源回退

验证报告合成器（`core/verify_report.py`）渲染场景明细表时，MUST 按以下优先级取场景列表：

1. `report.json`（`.fenix/verify-progress/<spec>/report.json`）的顶层 `scenarios` 非空列表 → 使用之（现状，full 模式 tester 路径不变）。
2. 顶层缺失/为空/非法时 → 回退读取裁决结果文件 `.fenix-run-result.json` 的 `verification.scenarios`（fast-track schema，`core/fast_track_result.py`）。结果文件查找顺序：`.fenix/verify-progress/<spec>/.fenix-run-result.json`（专属副本）→ `.fenix/.fenix-run-result.json`（主树共享文件，携带 spec 与当前 SPEC 不符时忽略——复用既有 `_load_run_result` 语义）。
3. 两者皆不可得 → 场景表留空，报告其余章节照常合成；MUST NOT 因场景数据缺失阻断报告合成（fail-closed 阻断仍由归档能力 verify-report-gate 的「结构化数据整体缺失」分支管辖，语义不变）。

数据读取 MUST 在 `synthesize_verification_report` 入口完成并作为参数传入纯函数渲染层，渲染函数保持无 IO。

#### Scenario: fast-track 结果文件嵌套场景渲染进场景表

- **WHEN** 某 fast-track SPEC 无 `report.json`，其 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 含 `verification.scenarios`（非空列表，元素含 `scenario_id`/`description`/`status`）
- **THEN** 合成的验证报告场景明细表逐行渲染这些场景（ID、描述、状态），与 Dashboard「场景结果」页签同源同量

#### Scenario: report.json 顶层场景优先不回归

- **WHEN** 某 full 模式 SPEC 的 `report.json` 含非空顶层 `scenarios`，同 SPEC 的 `.fenix-run-result.json` 亦存在
- **THEN** 场景明细表仍完全取自 `report.json` 顶层 `scenarios`，行为与修复前一致

#### Scenario: 两路数据皆缺时场景表留空不阻断

- **WHEN** `report.json` 缺失，`.fenix-run-result.json` 缺失/不可解析/`verification.scenarios` 为空或非法
- **THEN** 合成报告不含场景明细行但其余章节（结论、汇总表、Bug 章节）照常生成，合成整体不报错、不阻断
