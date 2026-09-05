# 修复验证报告合成对 fast-track 场景明细的读取缺口（fix-verify-report-fasttrack-scenarios）

## Why

验证报告合成器（`core/verify_report.py`）的场景明细表只认 `report.json`（full 模式 tester 产物）。fast-track run 不产出 `report.json`，场景明细在其裁决结果文件 `.fenix-run-result.json` 的 `verification.scenarios` 嵌套键下（`core/fast_track_result.py` schema）。因此所有 fast-track SPEC 的合成「验证报告」文档场景表恒为空——数据在 `verify-progress/<spec>/` 专属副本中并不缺失，纯读取端格式兼容缺口。

同根因已在本日修复于 Dashboard 读侧（`core/dashboard/data.py` 的 `parse_run_result_scenarios`，顶层 `scenarios` 缺失时回退 `verification.scenarios`，commit 待提交）；本 change 将同一兼容契约补齐到验证报告合成路径，消除 fast-track 验证报告的最后一块盲区。

## What Changes

- `core/verify_report.py` 合成报告的场景明细表（`_render_scenarios_table`）数据源扩展：`report.json` 的顶层 `scenarios` 缺失/为空时，回退读取 `.fenix-run-result.json`（verify-progress 专属副本优先，主树共享文件回退且需 spec 匹配——复用既有 `_load_run_result`）中的 `verification.scenarios`。
- 渲染函数为纯函数（不 IO），回退数据读取在 `synthesize_verification_report` 入口完成、作为参数传入，保持既有分层。
- 无 UI 改动：验证报告文档前端渲染（react-markdown）不变。
- 非目标：不改 fast-track 结果文件 schema（写入端）、不改 Dashboard 读侧（已修复）、不改裁决/闸门逻辑。

## Capabilities

### New Capabilities

- `verify-report-scenarios-sourcing`: 验证报告合成场景明细的数据源契约——report.json 顶层 scenarios 优先；缺失时回退 fast-track 结果文件 verification.scenarios 嵌套键；两者皆缺则场景表留空（报告仍可合成，不阻断）。

### Modified Capabilities

（无——`verify-report-gate` 已归档且其需求（闸门时序/fail-closed）不变；本 change 仅扩展合成器的场景数据源。）

## Impact

- 代码：`core/verify_report.py`（场景表数据源回退，约 10 行）。
- 测试：追加到 `tests/test_verify_report_gate.py`（已有合成器渲染与闸门测试类）。
- 数据：零迁移——存量 fast-track SPEC 的专属副本 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 已在盘上（8/8 完好），修复后合成路径立即可读。
- 下游：验证报告文档（spec 详情「验证报告」页签）fast-track SPEC 场景表从恒空变为完整明细。
