# Proposal: improve-hot-reload-robustness

## Why

2026-09-04 02:35–03:00Z 实证两处 daemon 健壮性缺陷叠加成一次 25 分钟故障：dashboard（新代码）写盘 `agents.models.fast-track` 后，daemon（旧代码，白名单仅 5 角色）配置热重载对未知键**整段拒绝**且失败后快照不更新，每 30 秒重试重报，25 分钟连发 50 条 ERROR、模型分配热更新全程不可用；同一错误串因告警升级口径缺陷，直到 02:45:23Z（第 6 条物理连续 ERROR）才产生 critical 告警，无人介入窗口 9.5 分钟。两个缺陷均未治理，复发敞口敞开。

## What Changes

- **热重载未知键逐键降级**：`core/config.py` `_validate_agent_models` 对未知 agent 类型键从 `raise ValueError`（整段拒绝）改为告警 + 跳过该键校验 + 其余配置照常应用，告警文案内嵌重启处方（`touch .fenix/restart_request`）。跳过 = 不校验、不从配置剔除，键保留在有效配置中。
- **校验分类线固化**：键集不匹配（代码演进产物）→ 逐键降级；值/类型非法（配置真坏，如 `llm.providers` 非 list）→ 维持整段拒绝 + 旧配置原子保留。该分类线以 Scenario 固化，防未来回归成两极。
- **代码陈旧检测**：daemon `initialize()` 记录代码 mtime 指纹 baseline，热重载时检测磁盘代码较启动时更新 → 每进程生命周期一次 WARNING 提示进程内校验规则可能为旧版、建议重启。
- **daemon_errors 告警口径重写**：`core/admin_monitor.py` `_detect_daemon_errors` 从「日志尾部物理连续 ERROR ≥3」（遇 INFO 即断，与错误复现率脱钩：活跃期永不触发、触发时机看日志安静度运气）改为「10 分钟窗口内同指纹复现 ≥2 次且相邻两次间隔 ≤5 分钟」。错误指纹 = component + 归一化 message 的 hash（归一化时间戳/UUID/hex/纯数字，保守集不过度聚合）。无状态每轮巡检重算，不持久化。
- **明确不做**：不新增配置键（阈值保持模块常量，规避配置项须带 Dashboard UI 的约束）；不改 15 分钟 cooldown 节流、`HUMAN_SEVERITIES` 降噪分级、合成兜底静默化路径；不做 1s 粒度快速通道（二期可选增强）。

## Capabilities

### New Capabilities

- `hot-reload-unknown-key-tolerance`: 配置热重载对未知 agent 类型键的逐键降级行为——降级告警格式与重启处方、键保留语义、值类错误整段拒绝边界、启动/热重载统一行为、旧配置原子保留。
- `daemon-error-escalation`: daemon 错误告警的升级语义——错误指纹归一化算法、复现窗口/间隔升级条件、防抖边界（单次不触发、异类不聚合、孤立抖动不触发）、cooldown 节流兼容。

### Modified Capabilities

（无——`spec/specs/` 当前无活跃能力，相关归档能力 `worktree-hygiene`、`human-escalation-alerts` 的需求不受本变更影响）

## Impact

- **代码**：`core/config.py`（`_validate_agent_models` 降级、可选清理死代码二次校验）、`core/admin_monitor.py`（`_detect_daemon_errors` 重写 + 指纹辅助函数 + 常量调整）、`fenixd.py`（陈旧检测挂 `_maybe_reload_config`、baseline 记录挂 `initialize`）。
- **行为变更**：daemon 启动期配置校验对未知 agent 类型键从 FATAL 退出变为告警后继续启动（启动与热重载共用同一校验路径）。
- **测试**：`tests/test_config.py`、`tests/test_admin.py` 新增 ~15 用例（降级矩阵、指纹归一化、窗口/间隔边界、原子性回归锁、cooldown 兼容）。
- **不受影响**：Dashboard 设置页、`AgentModelPanel.tsx` 角色表、config.yaml 格式、admin 告警存储结构。
