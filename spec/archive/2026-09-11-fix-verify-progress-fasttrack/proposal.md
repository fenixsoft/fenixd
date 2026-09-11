# 修复 Dashboard 验证进度对 fast-track SPEC 的读取缺口（fix-verify-progress-fasttrack）

## Why

Dashboard spec 列表「验证」列对所有 fast-track SPEC 恒显示 `0/0`，详情页「验证进度」卡片恒显示「暂无验证进度」——即使 fast-track 验证已全部通过（如 task-track 11/11 全 pass）。根因：验证进度数据源 `.fenix/verify-progress/<spec>.json`（total/done 进度文件）唯一写入方是 full 模式的验证引擎（`core/verify_engine/engine.py` 的 `_write_progress`），fast-track 单 agent 全包不经过该引擎，全程无人写此文件，读侧 `parse_verify_progress` 恒返回 `{exists: False, total: 0, done: 0}`。

同根因家族的姊妹缺口（fast-track 结果只落在 `.fenix-run-result.json`，读侧多处只认 full 模式产物）已在本日早间修复两处——Dashboard「场景结果」页签（`parse_run_result_scenarios`）与验证报告合成器场景表（`verify_report.py`，fix-verify-report-fasttrack-scenarios）；本 change 将同一兼容契约补齐到「验证进度」通道，消除最后一块盲区。

## What Changes

- `core/dashboard/data.py` 的 `parse_verify_progress` 数据源扩展：进度文件不存在时，回退从裁决结果文件 `.fenix-run-result.json`（verify-progress 专属副本优先，主树共享文件回退且需 spec 匹配——复用既有候选路径与匹配规则）的 `verification.scenarios` 合成进度：`total` = 场景数，`done` = 已判定场景数，`current` = 对齐 full 模式终态文案「验证完成: N通过, M失败, K错误」，并标记 `source: "run-result"` 供展示层区分来源。
- 列表页展示兜底（`core/dashboard/static/src/pages/projects/list.tsx`）：验证列为 `0/0`（total 为 0，两模式下同语义=尚无验证数据）时显示 `—` 替代 `0/0`，消除「已验证完成却显示 0/0」的歧义残留场景。
- 详情页「验证进度」卡片无需改动：数据层修复后 fast-track 已验证 SPEC 自然获得 `exists: true` 的进度（ProgressBarTile + current 文案复用现有渲染）。
- 非目标：不改 fast-track 结果文件 schema（写入端）、不改 verify_engine 写入逻辑、不改裁决/闸门逻辑、不做场景推进的伪实时进度。

## Capabilities

### New Capabilities

- `verify-progress-sourcing`: 验证进度数据源契约——进度文件（`.fenix/verify-progress/<spec>.json`）优先；缺失时回退 fast-track 裁决结果文件 `verification.scenarios` 嵌套键合成（含 done/total/current 语义与 source 标记）；两者皆缺则维持 `exists: false`（前端空态不变）。

### Modified Capabilities

（无——场景明细与验证报告的数据源契约由 fix-verify-report-fasttrack-scenarios 独立承载，本 change 不触碰。）

## Impact

- 代码：`core/dashboard/data.py`（`parse_verify_progress` 回退合成，约 30 行）；`core/dashboard/static/src/pages/projects/list.tsx`（验证列兜底，约 5 行）。
- 测试：`tests/test_dashboard_data.py`（新增 `parse_verify_progress` 回退合成用例：run-result 合成/优先级回归/双缺省/非本 spec 残留忽略）。
- 数据：零迁移——存量 fast-track SPEC 的专属副本 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 已在盘上（抽查 5/5 完好，场景数 6/11/8/4/8），修复后列表立即显示 N/N。
- 下游：spec 列表「验证」列 fast-track SPEC 从 `0/0` 变 `N/N`；详情页「验证进度」卡片从恒空态变为进度条 + 终态文案；前端构建产物由框架 merge 后自动重建（dist 不入库）。
