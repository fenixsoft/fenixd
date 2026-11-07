# Proposal: fix-dashboard-verdict-fallback — Dashboard 验证裁决兜底读取 impl-result 快照

## Why

fast-track SPEC 收口时把验证结论快照落盘为 `.fenix/verify-progress/<spec>/impl-result.json` 并删除共享 `.fenix/.fenix-run-result.json`（`core/pm_engine/dispatch/fast_track.py` `_fast_track_snapshot_and_cleanup`），而 Dashboard 裁决兜底读取器 `core/dashboard/data/artifacts.py` `_load_run_result` 的候选只有两个 `.fenix-run-result.json` 路径，从未覆盖 `impl-result.json`——凡成功收口的 fast-track SPEC，列表「验证」列与详情页 VerdictPanel 恒为空态（`parse_verdict` 返回 `exists: False`）。2026-11-06 起连续 5 个 fast-track SPEC（add-spec-list-mobile-style / add-titlebar-subtitle-stacked / add-spec-title-promotion-gate / add-spec-subtitle-and-row-click / add-distill-run-work-summary）全部命中，验证实际已发生（快照内 `verification.verdict=verified`）但界面呈现「无验证记录」，用户据此误判验证缺失。

## What Changes

- `core/dashboard/data/artifacts.py` `_load_run_result` 候选链增加第三路：`.fenix/verify-progress/<spec>/impl-result.json`（fast-track per-spec 快照），携带 `spec` 字段归属校验（fail-closed，不匹配即忽略）。
- 候选优先级：私有 `.fenix-run-result.json`（full 模式机械裁决）＞ `impl-result.json`（fast-track 快照）＞ 共享 `.fenix/.fenix-run-result.json`——fast-track 升级 full 后新裁决必须压过旧快照。
- 裁决段解析复用既有 `_run_result_verdict_and_bugs`（已兼容 fast-track 的 `verification.verdict` 嵌套形态），不改裁决语义、不伪造结论（无裁决值仍 fail-closed 返回 `exists: False`）。

## Capabilities

### New Capabilities

- `verdict-run-result-fallback`: Dashboard 验证裁决兜底读取的三路候选契约（私有 run-result / impl-result 快照 / 共享 run-result），含归属校验与优先级语义。

### Modified Capabilities

无——既有能力页（verify-pipeline `verification-report`、verdict-adjudication `verdict-visibility`）的规则不变；本 SPEC 修复的是兜底读取器对 fast-track 快照形态的覆盖缺口，属既有「md 缺失时回退结果文件裁决段」设计的实现补齐。

## Impact

- 代码：`core/dashboard/data/artifacts.py`（单文件，读侧 only，不触碰验证/裁决写链）。
- 测试：`tests/test_dashboard_data.py` / `tests/test_verify_report_gate.py` 既有断言钉死两路径形态（str/int 三态契约），新增 fast-track 快照路径用例时不得单侧归一既有形态。
- 影响面：Dashboard SPEC 列表「验证」列 Popover 与详情页 VerdictPanel 对历史与未来 fast-track SPEC 恢复展示；无数据迁移、无配置变更、无 UI 结构改动。
