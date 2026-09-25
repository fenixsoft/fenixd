# per-test-timeout 能力

## ADDED Requirements

### Requirement: 单用例超时硬门

本仓 pytest 套件的每个测试用例 SHALL 在 10 秒内完成。超时用例 MUST 被判失败（FAILED），且失败报告 MUST 包含可机读的超时标识（含超时阈值秒数），使回归读侧与人工均能一眼区分「超时失败」与「断言失败」。

#### Scenario: 慢用例被判超时失败
- **WHEN** 套件中存在一个执行超过 10 秒的用例（如 `time.sleep(15)`）
- **THEN** 该用例判 FAILED，失败信息包含超时标识与 `10` 秒阈值，且同会话其余用例继续执行

#### Scenario: 正常用例不受影响
- **WHEN** 用例在 10 秒内完成
- **THEN** 执行结果与未启用超时门时一致

### Requirement: 显式豁免清单

超时豁免 MUST 落盘到清单文件（每条含 `nodeid`、`timeout_seconds`、`reason` 三字段）。conftest SHALL 按清单对命中用例覆盖单用例超时值。清单条目 `reason` 缺失、`timeout_seconds ≤ 0` 或 YAML 格式非法 MUST 使校验用例失败——豁免必须显式留痕，禁止静默放宽。

#### Scenario: 清单内用例按登记时限放行
- **WHEN** 清单登记某用例 `timeout_seconds: 30` 且附理由
- **THEN** 该用例按 30 秒阈值判定，10 秒时不被判超时

#### Scenario: 清单条目缺理由即失败
- **WHEN** 清单中某条目 `reason` 为空或缺失
- **THEN** 清单 schema 校验用例判失败，指出违规条目

### Requirement: 存量套件零隐性超时

超时门启用后，存量全量套件 MUST 无因超时产生的新增失败（存量慢用例已在实现分支全部处置：修复或登记豁免）。

#### Scenario: 全量回归无超时失败
- **WHEN** 在启用 10s 门的分支上执行全量回归
- **THEN** 回归通过，且报告中不存在因超时判失败的用例
