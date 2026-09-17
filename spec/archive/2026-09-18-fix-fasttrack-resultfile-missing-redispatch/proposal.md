## Why

两起 fast-track run 因「结果文件未产出」被整体作废重派，合计直接损失约 $5.4 + 2 次状态回退：add-turn-limit-anchor-c run1（$8.83，181 turns / 19 次 Edit，无提交无结果文件）与 add-main-tree-deps-provision run1（$8.91，已全量提交 5 个 commit 仍判死亡）。复发敞口 ≈ $8.8/次（run1 实测成本）。根因：fast-track 死亡判定只看结果文件是否存在、不查分支是否已有提交——分支已提交的成果被当「run 死亡」discard 后从零重派。与 35706f95（零变更哨交付物守卫：有交付成果不得按空转重派）同族。

## What Changes

- **fast-track「结果文件缺失」收口语义升级**：`_run_fast_track_flow` 在结果文件缺失时不再一律判「死亡重派」，先查实现分支相对 main 是否已有提交（`git rev-list --count main..<branch>`）：
  - 分支有提交 → 不判死亡、不回退预算、不 reset ready；merge 分支（复用 `_reconcile_and_merge`）+ 改写 `mode=full` + enqueue 完整模式 verifier 补齐缺失的 verdict（复用 `_escalate_to_full_mode` 升级语义，触发因不同），随后走既有 verified→done 门。
  - 分支零提交或无 branch 字段 → 维持现有死亡豁免 + reset ready + 自动重派（不变）。
- **共享结果文件残留治理**：`.`fenix/.fenix-run-result.json`（主树共享单文件）读取收紧为 fail-closed——stamp 必须严格等于当前 spec（缺失/空/不符一律 ignore），关闭「无 stamp 残留被误采信」的 fail-open 洞；并在消费（stamp 匹配采信）后即时删除共享文件，消除跨 spec 残留误拦与读侧噪声。

## Capabilities

### New Capabilities

- `shared-result-file-integrity`: 主树共享结果文件 `.fenix/.fenix-run-result.json` 的 stamp 严格校验（fail-closed）与消费后清理的生命周期契约，消除跨 spec 残留对死亡判定/读侧的误拦。

### Modified Capabilities

- `fast-track-mode`: 修改「统一结果文件驱动状态推进」中「结果文件缺失或不合法则不推进」的语义——结果文件缺失时新增「分支已提交 → merge + 升级补验证」分支，不再无差别按失败重派。仅 fast-track 车道变更；full 车道 implementer 成功路径已由零变更哨的 rev-list 判定覆盖，不在本变更范围。

## Impact

- `core/pm_engine/dispatch.py`: `_run_fast_track_flow`（约 1944-1954）死亡判定分支新增 rev-list 提交检查与「merge + 升级补验证」路径；`_escalate_to_full_mode`（2726）需要支持「缺结果文件」触发因（或新增变体方法）。
- `core/pm_engine/engine.py`: `_read_implementer_result`（724）stamp 守卫从「不符才 ignore」收紧为「非严格匹配即 ignore（fail-closed）」。
- `core/pm_engine/verification.py`: `_implementer_zero_change`（2508）内联的 rev-list 判定提取为可复用 helper（`_branch_has_commits` 或同语义），供死亡路径复用。
- 无数据迁移、无 UI、无外部 API 变更。