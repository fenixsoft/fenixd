# 提案：reduce-stale-code-selfheal-noise

## 背景

fenix-desktop 项目 2026-09-26（框架开发日）实测：stale_code 自愈触发 16 次重启（.fenix/restart_history.jsonl 快照窗口 04:10:41~16:50:40Z 恰 16 条，04:10-04:20 三连），每次含 60 秒 drain，守护进程累计约 20 分钟不可用；告警流按 60 分钟去重（fenixd.py:158）仍产出 7 条 kind=escalation 的 stale_code 告警，全部自述「无需人工干预」，且写入约 16ms 即被自动标记已处理（fenixd.py:1215-1216）——纯噪声。9-17/18 已复发（两日合计 37 次、单日峰值 19），框架开发日必然复发。

## 问题

1. idle_confirm_seconds 缺省 120（core/config.py:1488），开发日密集落地的代码批次被逐个放大成多轮重启；项目可用 stale_code_selfheal.idle_confirm_seconds 覆盖，但缺省对小间隔批次无合并能力。
2. 自愈健康路径的告警仍以 kind=escalation 写入 admin_alerts.json（fenixd.py:1194）：2026-09-13 用户决策（fenixd.py:1189-1193）已降 severity=warning 并自动已处理、不进人工队列（core/admin_store.py:45-49），但 escalation 记录本身仍进告警流、历史与日审读数，与其「无需人工干预」的自我定位不符。

## 目标

- 开发日密集落地批次合并为一轮自愈重启：空闲确认缺省 120→600 秒，项目覆盖语义不变。
- 自愈启用且健康时，陈旧代码告警降为 info 级留痕＋日计数，不再进 escalation 流；仅自愈禁用、自愈失败或悬空超限才升级 escalation。

## 非目标

- 不改动 60 秒 drain（core/config.py:1317）与 supervisor 优雅重启链路。
- 不改动既有 cooldown 五键（core/config.py:1492-1496）与 60 分钟去重语义（fenixd.py:158）。
- 不重复 evo-add-stale-code-dangling-deadline 的悬空升级（max_dangling_seconds=14400，core/config.py:1500）与 evo-alert-noise-governance 的通用降噪治理。
- 不改 mark_handled 仅匹配 ESCALATION 的人工闭环锚点语义（core/admin_store.py:380/:388/:400/:444）。

## 方案概要

见 design.md。