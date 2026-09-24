# Proposal: stale_code 告警跨重启窗口去重

## 问题背景

stale_code 升级告警在约 22 小时窗口（2026-09-22T19:46Z 至 09-23T17:51Z）同文重复 13 条，历史存量占 admin_alerts.json 150 条上限的 91 条（61%）——固定容量下写回自动裁剪最旧记录，其他告警的回查窗口被持续挤掉。现状写入侧已是假→真边沿触发、单 daemon 生命周期一条（fenixd.py:969-993），重复的真正来源是 daemon 生命周期本身在高频提交下快速轮换：主树约每 29 分钟一次提交，每次提交都让新进程再次「首次变陈旧」成条。

## 方案概述

在 _update_stale_code_state 的告警写入块前置持久化窗口判定：

1. append 前调 AdminStore.latest_signal(None, "stale_code", 60)——60 分钟窗口内已有同信号记录则跳过写入、降级为日志；admin_alerts.json 落盘持久，去重状态天然跨 daemon 重启存活，零新增状态文件。
2. 窗口常量取模块级常量风格（对齐 admin_monitor 的 DAEMON_ERROR_RESTART_COOLDOWN_MINUTES），不新增配置面。
3. 超窗新周期照常成条：窗口与自愈重启节奏（窗口内实测约 1-2 小时一次）同量级，真正的新陈旧周期不被吞。

## 影响范围

- 修改 fenixd.py：_update_stale_code_state 写入块窗口判定
- 修改 tests/test_stale_code_selfheal.py：窗口去重回归

## 非目标

- 不做历史条目折叠/聚合改写——kind=escalation 记录永不参与合并（core/admin_store.py:276-279 不变量，id 是闭环锚点）。
- 不改自愈重启机制与 evo-stale-selfheal-restart-cooldown 交付面（重启冷却五键、restart_history.jsonl 不动）。
- 「已排期重启状态变化再报」作为可选增强不列入本 SPEC 必选面（可用 restart_history.jsonl 边沿后续追加）。
