## Why

`tests/test_cancel_holdstate_recovery.py` 的六处取消收尾「写点」断言与 `core/pm_engine/dispatch.py`、`verification.py` 的**绝对行号**耦合：`WRITE_POINTS` 以行号为中心取窗口断言 `_cancelled_hold`/`error` 键存在。fenixd 高频并行分支合并（窗口 91 commits/24h）不断在被测文件插入行，写点行号随之漂移。已发生三次手工重钉（14380774、2e98e052、762b4aee），每次重钉 3-4 个行号并固化溯源注释；2e98e052 还带出 4/6 子用例红灯。当前（2026-09-12）verification.py 三处写点已从 1451/1781/2611 漂移到 1629/2003/2836，测试 3/6 红灯且无人发现——失配无自动发现机制，是系统性缺口。

## What Changes

- 把 `WRITE_POINTS` 的绝对行号改为**语义锚点**（函数名 / 最近唯一模式串 + 相对偏移），定位函数在测试运行时**动态重算**写点位置，漂移自动跟随。
- 定位函数失配即抛明确的红测试（含锚点标签、锚点串、当前实际命中位置），**自检内化**，无需 daemon / hook 层改造。
- 复用 `test_no_new_holdstate_write_point_missed` 的全库扫描作为锚点**唯一性自证**（断言恰好六处写点，防止锚点串误命中）。
- 清除三次溯源留下的行号考古注释，改以锚点串描述每条写点。

## Capabilities

### New Capabilities

- `writepoint-semantic-anchor`: 测试对被测代码「写点」的断言定位，从绝对行号改为语义锚点动态定位（函数名 / 最近唯一模式串 + 相对偏移），实现对行号漂移免疫、失配即红。

### Modified Capabilities

<!-- 无既有能力 requirement 变化 -->

## Impact

- `tests/test_cancel_holdstate_recovery.py`（modify）：WRITE_POINTS 数据、定位函数、失配报错、唯一性自证。
- 被测文件 `core/pm_engine/dispatch.py`、`core/pm_engine/verification.py` 运行时逻辑**不改**，仅作为锚点串引用来源。
- 无 UI、无数据迁移、无外部依赖。