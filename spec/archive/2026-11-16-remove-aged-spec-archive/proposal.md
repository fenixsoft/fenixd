# Proposal: remove-aged-spec-archive

## Why

R2 时效归档（终态 + verification-report.md + 目录 mtime 滞留 ≥72h 自动归档）原是为「归档后触发知识蒸馏」设计的确定性收尾通道；蒸馏触发已迁至 push 状态（`move-distill-trigger-to-push`，蒸馏输入双态解析 changes/ 优先、archive/ 兜底），时效归档失去存在依据。它把活跃区水位持续压到远低于 `archive.auto_threshold`（当前 20 目录 / 18 终态），使阈值配置失去「活跃区水位管理」的本意——终态 SPEC 应当留在活跃区，由阈值水位统一驱动归档。

## What Changes

- **移除 R2 时效归档通道**：终态 SPEC（STATE 有条目、done/pushed）不再因「含 verification-report.md + 目录 mtime 滞留 ≥72h」被自动归档。终态积压仅在数量达到 `archive.auto_threshold`（默认 50，`>=` 触发）时经 R1 排水归档（排水至低于阈值，现行语义不变）。
- **保留 R3 孤儿目录接管**（用户已确认）：`spec/changes/` 下 STATE 无条目的孤儿目录仍按既有判据（verification-report.md + mtime ≥72h）经 `allow_unregistered=True` 归档（`archived_by=auto-orphan`）。孤儿不计入阈值水位、无其他自动清理通道，保留其为活跃区卫生兜底。
- **保留 R4 每日滞留盘点**（纯信号）并调整其清单语义：R2 移除后「终态+报告+滞留≥72h」从异常形态变为预期常态（等待 R1 阈值排水），原①项单目录清单会成为每日常态噪音；原③项（无报告终态死角）语义同步消失（R1 排水不以报告为前置）。①③合并为**终态水位观测**（终态未归档计数 + 最老终态目录滞留天数，24h 去重一条 INFO），契合告警降噪偏好。② 孤儿目录列示与存量回填（先回填后阈值归档）不变。
- **threshold=0 语义不变**：0 = 禁用全部自动归档动作（R1/R3）；设置页控件与文案无需改动。
- **存量行为**：已终态未归档的存量 SPEC（如当前 18 条 pushed）将滞留活跃区，直至终态积压 ≥ 阈值触发 R1 排水——这是预期行为，不迁移。
- **BREAKING**（行为语义）：终态 SPEC 不再有 3 天确定性归档保证；活跃区水位不再被时效规则主动压低。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `spec-archive-drain`: 移除 R2 时效归档要求（终态路径）；R3 孤儿路径、R1 阈值排水、R4 盘点、存量回填要求保持不变。归档触发模型从「阈值 + 时效双通道」收敛为「纯阈值水位驱动」。

## Impact

- `core/dashboard/data/spec_archive.py`：`_archive_aged_specs` 移除 R2 终态分支、保留 R3 孤儿分支；`_daily_stale_audit` ①③合并为终态水位观测；`run_auto_archive` 主流程与返回键相应调整；模块 docstring 与行内注释同步。
- `tests/test_spec_archive_drain.py`：R2 用例改造为「终态 + 满足时效判据 → 不归档」，R3 孤儿用例保留，R4 用例更新为水位观测语义，R1/回填用例回归。
- 知识页 `spec/knowledge/domains/spec-lifecycle/auto-spec-archive.md` 不在本 SPEC 交付物内——由归档蒸馏管线随本 SPEC 归档自动回填（真相源纪律）。
- 蒸馏管线无影响：触发在 `approve_push`（`distill-push-trigger`），归档输入双态解析已覆盖终态 SPEC 长期滞留活跃区的形态。
