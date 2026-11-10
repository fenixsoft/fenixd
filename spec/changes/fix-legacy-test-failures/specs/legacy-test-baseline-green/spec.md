# MODIFIED Requirements

## Requirement: 主线全量测试零失败基线

主线全量测试（`python3 -m pytest tests/ -q`）SHALL 以 0 failed 收场，且每一个被修复的存量失败 SHALL 带有可追溯归因（真实违例修实现 / 过时断言修断言并注明 / 隔离问题修隔离）。

#### Scenario: 全量测试基线全绿

- **WHEN** 在干净实现分支上运行 `python3 -m pytest tests/ -q`
- **THEN** 结果为 0 failed（passed/skipped/xfail 均可接受）
- **AND** 每个修复对应的 tasks 任务说明记录了归因类别与证据

#### Scenario: 修复不掩盖真实缺陷

- **WHEN** 某失败通过修改断言而非实现修复
- **AND** 该断言的现行行为经复核为正确
- **THEN** 任务说明 SHALL 注明「断言脱节」归因与复核证据
- **AND** 不允许通过删除测试、放宽守卫或无归因改断言使套件变绿
