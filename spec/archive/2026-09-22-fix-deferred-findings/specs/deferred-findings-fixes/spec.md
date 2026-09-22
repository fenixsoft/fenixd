# deferred-findings-fixes

## ADDED Requirements

### Requirement: 无重叠遗留疑点逐条清算

前三条重构 spec 疑点清单中**未修复且在飞重构 spec 作业面之外**的条目 MUST 逐条处置，每条 MUST 显式标注为「零行为变化」或「有意修复行为」，并给出可验证的测试证据。

MUST 覆盖的条目（详细账目以 design D1 为准）：

1. `core/dashboard/data/timeline.py` 的 `_timeline_sort_key` 无效时间戳分支 `datetime.max.replace(tzinfo=_tz)` 类型错误（`_tz` 为 `timezone` 类非实例）——**P0 真 bug**。
2. verification `serving` 的 `_port_responds` 串行探测 51 端口（两处）导致的延迟尖峰。
3. verification 子包内 3 处重复 late-import `import re as _re`。
4. `_escalate_env_blocked` 的 evidence 截断无 `...` 标注。
5. `_record_verdict_adoption` 的 `_judge_token_baseline` JSON 解析失败静默 fallback。
6. `_run_legacy_verification` 与 `_read_verdict` 的共享文件 fallback 路径重复。
7. `_ensure_serving_worktree` 中 `_unregister_serving_instance` 先于 `stop()` 且 `stop()` 的 except 仅 `pass`。

对确认为「记录不修」的观察项（`_should_overlay` 语义、`shell=True` 注入面、config 缓存键、位移降档公式），MUST 在 design 中显式登记为「不修」并给出理由，MUST NOT 静默丢弃。

#### Scenario: 每条有处置

- **WHEN** 审阅 design 的逐条账目
- **THEN** 上述每条均有「目标状态 / 行为变化标记 / 测试证据」三项，无遗漏

### Requirement: 真 bug 修复带回归测试

`_timeline_sort_key` 的类型错误 MUST 被修复为不再抛 `TypeError`（无效时间戳事件排在末尾）。修复 MUST 同步更新当前把错误行为锁死的 characterization 测试（`test_timeline_sort_key_invalid_time_sorts_later` 现以「抛 `TypeError`」为预期），新的测试 MUST 断言排序结果而非异常。

#### Scenario: 无效时间戳不再崩溃

- **WHEN** 对含缺失 / 非法 `time` 字段的事件调用 `_timeline_sort_key`
- **THEN** 返回可比较的排序键（不再抛 `TypeError`），该事件排到末尾

#### Scenario: characterization 测试已同步

- **WHEN** 运行原锁定「抛 TypeError」的测试
- **THEN** 该测试已改为断言新行为（排序结果）且通过

### Requirement: 性能修复结果集不变

`_port_responds` 的端口探测改造（并发 / 超时收敛）MUST 保持产出的 `pre` 端口集合语义**逐元素一致**；MUST NOT 改变 `CommandVerifyServer(legacy_pre=...)` 的输入语义。

#### Scenario: pre 集一致

- **WHEN** 用同一端口占用场景对比改造前后的 `pre` 集合
- **THEN** 两个集合完全相等

### Requirement: 零行为变化的条目行为不变

标注为「零行为变化」的条目（重复 import、fallback 路径去重）修复后 MUST NOT 改变任何可观测行为；全量 `bin/run_full_suite.py` 失败集合相对基线 MUST NOT 新增失败。

#### Scenario: 整洁类改动可观测行为不变

- **WHEN** 完成整洁类条目修复并运行全量测试
- **THEN** 失败集合相对基线不新增失败

### Requirement: 与在飞重构 spec 的源文件隔离

本变更 MUST NOT 修改任何在飞重构 spec 的作业面文件：`core/worktree_manager.py`、`core/pm_engine/dispatch.py`、`core/dashboard/server.py`、`core/pm_engine/engine.py`、`core/pm_engine/verification/pipeline.py`、`core/agent_runner/runner.py`。

落在上述文件的疑点条目 MUST 显式登记为「转移清单」，由对应重构 spec 承接（见 design D3），MUST NOT 在本变更中修改。

#### Scenario: 隔离成立

- **WHEN** 检查本变更的 commit 改动文件集
- **THEN** 与 design D3 在飞文件清单无交集

### Requirement: 不使用绝对行号锚定

任务与交付物 MUST 以函数名 / 符号名锚定，MUST NOT 使用绝对行号。

#### Scenario: 任务锚点为符号名

- **WHEN** 审阅 tasks.md
- **THEN** 所有任务以符号名描述位置，无绝对行号
