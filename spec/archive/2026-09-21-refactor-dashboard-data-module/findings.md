# Findings — refactor-dashboard-data-module

> 疑点清单：拆分中发现的 bug/死代码/循环依赖，**只记录不修**（spec 约束：拆分零行为变化）。
> 条目格式：`[状态] 编号：描述（位置/证据，发现阶段）`

## BUG（代码缺陷，纯记录）

- [ ] **BUG-1** `_timeline_sort_key` 无效时间戳分支抛 `TypeError`：`data.py:3634` 的
  `_dt.max.replace(tzinfo=_tz)` 中 `_tz` 是 `timezone` **类**而非实例，
  `datetime.max.replace(tzinfo=类)` 直接抛 `TypeError`。事件 `time` 缺失/非法
  时该分支必然崩溃（characterization 测试已锁定该抛错行为，见
  `tests/test_characterization_dashboard_data.py::test_timeline_sort_key_invalid_time_sorts_later`）。
  修正应为 `timezone.utc`。属于 timeline 组，搬移时携行为原样迁入。

## 死代码 / 冗余（只记录）

- [ ] **DEAD-1** `_should_overlay` 语义疑点：`done/pushed` 且 `has_uncompleted=True`
  才叠加 live 覆盖。README 语境下无 `tasks.md` 未勾选任务时，`done` 不叠加——
  可能是历史变迁残留的分支，非死代码（测试覆盖中），暂记。

## 循环依赖（本变更不消除）

- [ ] **CYC-1** `core/pm_engine/` 有 3 处反向 import `core.dashboard.data`
  （design Context 已声明既有分层倒置，本变更不处理，只保持兼容）。

## 结构性观察（不修）

- [ ] **OBS-1** `read_config` 与 `read_effective_config` 均含缓存键
  `_config_file_sig(USER_CONFIG_PATH)`，patch `USER_CONFIG_PATH` 时缓存键随之变化，
  属 D8 语义保持范围内（搬移 config_admin 组时注意缓存键引用须随函数走）。