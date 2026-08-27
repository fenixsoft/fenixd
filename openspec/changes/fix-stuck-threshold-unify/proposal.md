# Proposal: fix-stuck-threshold-unify

## Why

`schedule.stuck_threshold_minutes`（默认 60）与 `agents.run_timeout_seconds` 是两个独立旋钮，2026-08-27 实证二者漂移必然产生事故：超时放宽到 9000s 后，健康运行必然超过 60 分钟，BLOCKER CHECK 的 auto-recovery 连续把存活的 implementer 误判卡死并重置（当日 improve-scheduling-noise-governance 与 improve-run-lifecycle-governance 均中招），随后重派又撞存活 worktree 锁形成打摆。阈值本不该由人脑维护同步——它只应派生自超时本身。

## What Changes

- **单源派生**：check_blockers 的 stuck 判定阈值改为 `agents.run_timeout_seconds + 内部宽限常量`（宽限 10 分钟，非配置项，见 design D1），`schedule.stuck_threshold_minutes` 与 `admin.stuck_threshold_minutes` 不再作为生效输入。
- **旧键弃用告警**：配置中若仍存在旧键，启动/热更新时打一次 WARNING 提示已由超时派生，值不再生效（不阻塞、不报错）。
- **语义校正**：派生后阈值恒大于 run 墙钟上限，恢复判定只可能命中"运行已死但记账残留"的孤儿，永不早于 agent_runner 自身的超时终止；admin_monitor 的 stuck 检测复用同一派生助手。
- **absolute_max 联动护栏**：timeout_supervision.absolute_max_seconds 若配置值低于超时+续期上限，启动打 ERROR 并按 run_timeout_seconds + 7200 兜底；默认值对齐 14400。

## Capabilities

### New Capabilities
- `stuck-timeout-single-source`: stuck 阈值从 run 超时单源派生、旧键弃用与 absolute_max 联动护栏

### Modified Capabilities

<!-- 无 -->

## Impact

- **代码**：`.fenix/core/pm_engine.py`（check_blockers 阈值来源）、`.fenix/core/config.py`（get_admin_config 回退链调整 + 弃用告警 + 派生助手 + absolute_max 校验）、`core/agent_runner.py`（supervision 激活路径读取兜底值）
- **配置**：`.fenix/config.yaml` 移除 schedule.stuck_threshold_minutes 行并留注释说明派生关系；absolute_max_seconds 已对齐 14400
- **测试**：tests/test_core.py 阈值派生用例、旧键弃用告警用例、上限护栏用例
