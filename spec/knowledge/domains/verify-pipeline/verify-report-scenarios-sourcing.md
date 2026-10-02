# 验证报告场景明细读取源
<!-- knowledge: capability=verify-report-scenarios-sourcing rev=1 sources=spec/archive/2026-09-10-fix-verify-report-fasttrack-scenarios -->

验证报告合成器场景明细表的数据源契约：report.json 优先，缺失时回退 fast-track 结果文件嵌套键。

## 现行规则

- 数据源优先级（`core/verify_report.py` 渲染场景明细表时）：① `report.json`（`.fenix/verify-progress/<spec>/report.json`）顶层 `scenarios` 为非空列表 → 使用之（full 模式 tester 路径）；② 顶层缺失/为空/非法 → 回退读裁决结果文件 `.fenix-run-result.json` 的 `verification.scenarios`（fast-track schema）；③ 两者皆不可得 → 场景表留空，报告其余章节（结论、汇总表、Bug 章节）照常合成，不因场景数据缺失阻断报告合成。
- 结果文件查找顺序：`.fenix/verify-progress/<spec>/.fenix-run-result.json`（专属副本）→ `.fenix/.fenix-run-result.json`（主树共享文件，携带 spec 与当前 SPEC 不符时忽略，复用既有 `_load_run_result` 语义）。
- 分层纪律：数据读取在 `synthesize_verification_report` 入口完成并作为参数传入纯函数渲染层，渲染函数保持无 IO。
- fail-closed 边界：报告整体缺失的结构化数据阻断仍由 verify-report-gate 的「结构化数据整体缺失」分支管辖，场景表回退不改变该语义。
- 同源性：fast-track SPEC 的合成报告场景明细表与 Dashboard「场景结果」页签同源同量（逐行渲染 ID、描述、状态）。

## 溯源

- 2026-09-10 fix-verify-report-fasttrack-scenarios（spec/archive/2026-09-10-fix-verify-report-fasttrack-scenarios） — 补齐合成器对 fast-track 结果文件 `verification.scenarios` 嵌套键的回退读取（fast-track 不产 report.json，合成报告场景表此前恒为空，纯读取端格式兼容缺口）
