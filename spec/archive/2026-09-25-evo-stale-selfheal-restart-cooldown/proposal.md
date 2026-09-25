# Proposal: Stale Selfheal 重启冷却机制

## 问题背景

stale_code_selfheal 机制在检测到代码陈旧且连续空闲后会触发 daemon 优雅重启，但缺少连续重启冷却保护。2026-09-20 UTC 06:19-07:06 期间，该机制形成「重启→检测→重启」正反馈循环，47 分钟内触发 27 次重启（全天共 93 次），杀死正在运行的评审 run，每次重启执行全量 270+ spec 扫描造成无意义 I/O。

## 方案概述

1. **滑动窗口重启计数**：在 `_maybe_stale_selfheal_tick` 中增加历史重启记录，30 分钟内重启 ≥3 次则进入冷却状态，暂停自愈触发 10 分钟并升级为 admin 告警。
2. **自触发型 stale 识别**：重启后 5 分钟内若再次检测到 stale，标记为 self-triggered，仅升告警不触发重启。
3. **_is_idle 补全**：将 agent_runner._running_agents 纳入空闲判定，避免杀死在飞评审 run。

## 影响范围

- 修改 `fenixd.py`（仓库根，非 `core/fenixd.py`）中 `_maybe_stale_selfheal_tick` 和 `_is_idle` 方法
- `core/config.py`：`get_stale_code_selfheal_config` 增加五个冷却/自触发键（经 `.fenix/config.yaml`
  配置、30s 热更新生效；本 SPEC 不扩展 Dashboard 面板）
- 新增 `.fenix/restart_history.jsonl` 持久化文件
- 同步更新 `docs/help/07-safeguards.md`（空闲判定口径含评审 run）与 `docs/help/09-config.md`（键表）
- 可能影响 `add-stale-code-selfheal` SPEC 的行为语义（向后兼容：enabled 默认行为不变）