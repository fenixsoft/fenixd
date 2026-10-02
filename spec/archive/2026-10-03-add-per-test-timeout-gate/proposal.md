# 提案：add-per-test-timeout-gate

## Why

09-24 19:03 起 drain-window 测试替身真自旋（6 个用例各烧满 60s 替身超时）使单次全量回归从 ~250s 涨到 ~615s，此后 ~41 次回归累计多烧约 4.1 小时才被人工定位。当前对「新增测试用例过慢」没有任何机制性拦截，慢用例只会静默拖长每一次回归。

## What Changes

- pytest 全局单用例 10s 硬超时（pytest-timeout，signal 方法）：超时用例判失败，失败信息含可辨识的超时标识与阈值秒数
- 显式豁免清单机制：确需更久的用例必须在清单登记 `nodeid + timeout_seconds + reason`，由 conftest 按清单对命中用例覆盖超时值；清单条目缺理由或格式非法时校验用例判失败（防静默豁免）
- 存量套件一次性审计：10s 门下全量跑一遍，所有超时用例逐个处置（修复替身/测试，或登记豁免并写明理由）

## Capabilities

### New Capabilities
- `per-test-timeout`: 本仓 pytest 套件的单用例超时硬门、显式豁免清单与存量零隐性超时保障

### Modified Capabilities

（无——本改动不修改既有 capability 的需求）

## Impact

- 新建 `pytest.ini`（仓级单源配置：`timeout = 10`、`timeout_method = signal`）
- 修改 `tests/conftest.py`（豁免清单注入）
- 新建 `tests/timeout-allowlist.yaml`（豁免清单）与 `tests/test_timeout_gate.py`（门行为 + 清单 schema 校验用例）
- 依赖 `pytest-timeout`（2.4.0 已在运行环境）
- 生效范围：凡以本仓为根执行 pytest 的入口（回归车道、spec 验证链、开发者本地）自动生效，无需逐入口改命令
