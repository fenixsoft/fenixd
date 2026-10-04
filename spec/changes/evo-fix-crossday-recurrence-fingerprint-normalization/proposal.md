# fix-crossday-recurrence-fingerprint-normalization

## Why

上游 bigmodel.cn 瞬态窗口已连续 6 夜在本地 04:31 前后击杀在跑 code-fix 批。框架其实已有跨日聚合观测——evo-add-codefix-conn-error-cooldown 任务 3.1 落地的 _detect_crossday_recurrence（core/admin_monitor.py:3081，同指纹失败终态跨日差 24h±5 分钟即升级 escalation）——但它对这类夜间死亡签名一次都未命中，原因有二：① 错误指纹归一化（_STANDALONE_NUMBER_RE，admin_monitor.py:561）不归一「小数+单位后缀」形态（"23.4s"→"#.4s"、"5.3s"→"#.3s"），实测 10-02 与 10-03 两夜死亡 ERROR 行指纹不等（dbd8dc91f1530046 vs 2770ed6f532f254c），同形夜间死亡几乎必然判为不同事件；② 跨日记忆是实例内存（_daemon_fp_last_failure），daemon 重启（如 10-02 22:48:40Z）后回退对账只读日志尾 256KB（_TAIL_ERROR_READ_BYTES），高频日志下回不到 24 小时前。结果：连续 6 夜同刻复发在告警层面完全不可见，只能靠每日自进化复核人肉发现；窗口消失后也将失去「复核冷却/salvage 是否可退场」的数据支撑。

## What Changes

1. 指纹归一化补缺陷：_normalize_error_message/_error_fingerprint 补「数字.数字+单位字母」形态（延迟秒数等），使同形错误行在延迟数值不同时指纹一致；或对 api_timeout 类死亡改用结构化签名（api_timeout 布尔 + stderr_tail 骨架）替代含延迟小数的整行。
2. 跨日记忆跨重启可用：_detect_crossday_recurrence 的指纹记忆持久化到状态文件（仿 fix-progress.json 形态），daemon 重启后可对账；日志回退窗从 256KB 尾读扩大为可回溯 24h 的定向检索。

## Impact

- Affected specs: 无（对 evo-add-codefix-conn-error-cooldown 已落地能力的缺陷修复，非新能力面）
- Affected code:
  - core/admin_monitor.py（指纹归一化 + 记忆持久化/回退检索）
  - tests/test_crossday_recurrence_fingerprint.py（新增测试）

纯只读观测增强：不新增告警类型、不改变熔断/冷却/salvage 行为、不影响 daemon_errors 既有第一维度（≥2 次/10 分钟）判定。