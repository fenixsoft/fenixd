# Design: supervision-timeout-config-consistency

## 背景与痛点

配置漂移：run_timeout_seconds=15000 vs absolute_max_seconds=14400，监督兜底 18600s 生效，5 条 ERROR 复现两日。config.py:1241 只告警返回兜底；liveness.py:777-789 兜底口径另一套（22200）。

## 目标

- 单一派生口径：下限 = run_timeout + max_extensions × extension_seconds。
- 启动/热更新不一致即阻断（或自动对齐）。
- 消除同文案 ERROR 复发。

## 非目标

- 不动监督运行时决策矩阵。
- 不强制改 run_timeout 值。

## 方案

1. core/config.py 新增/收敛派生函数（如 `supervision_floor(config)`），返回下限；`effective_supervision_absolute_max_seconds` 改为消费该函数，并增加 fail-fast 分支（配置校验阶段，不一致即 raise/返回失败，取代仅告警）。
2. core/agent_runner/liveness.py:777-789 兜底口径改为调用同一派生函数，删除手写 22200/18600 类常数。
3. 热更新路径（config reload）同享校验，失败即拒绝新配置回滚旧值。
4. .fenix/config.template.yaml 补齐注释与对齐示例值（absolute_max ≥ run_timeout + 续期总额）。

## 测试策略

- 新文件 tests/test_supervision_timeout_consistency.py：下限派生值、两处口径一致、不一致启动阻断、热更新拒绝回滚、自动对齐持久化五类。
- 既有 tests/test_config.py、test_system_settings_config.py、test_liveness_hang_discrimination.py 回归。