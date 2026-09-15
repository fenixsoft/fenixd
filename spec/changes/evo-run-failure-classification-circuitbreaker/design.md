# design — run-failure-classification-circuitbreaker

## 现状

- spec_review.py:427-466 _handle_review_failure 不分类、机械递增至 MAX_REVIEW_ATTEMPTS=3 → freeze_for_human。
- admin_alerts.json 事件窗口无评审失败类（103 条告警类型集合实证）。

## D1 失败分类

- core/pm_engine/spec_review.py（及 verify/impl 失败收口处）新增 _classify_failure(reason, exit_code) → "infra" | "content" | "artifact"：
  - artifact：产物已落盘合法（复用 run-failure-artifact-first 的 _artifact_landed_valid）；
  - infra：指纹匹配（403/402/429/quota/budget/余额/insufficient balance/rate limit）或 CLI 进程级崩溃；
  - content：其余（含空白轮次）。

## D2 熔断状态

- core/pm_engine/engine.py：链路级熔断器 {link: (count, until)}；连续 infra 失败 ≥3（admin.run_infra_breaker.threshold，默认 3）→ 熔断 until=now+cooldown（默认 30min）；熔断窗口内 run_spec_review 入口直接短路（不派发）。
- 状态持久化到 .fenix/admin_infra_breaker.json（daemon 重启后恢复，防止重启重置熔断）。

## D3 ADMIN 信号接入

- core/admin_monitor.py：新信号类型 run_infra_failure（severity=critical）登记 SIGNAL_SEVERITY/SIGNAL_RECOMMENDATION；熔断触发/恢复各落一条升级记录，evidence 含链路/指纹/次数/时间窗（汇总口径：把同型失败次数并入，供人工一眼看出「评审 API 批量失败」）。

## D4 恢复

- 冷却到期自动恢复（窗口滑动）；恢复后首次成功 run 清空计数。

## D5 配置

- core/config.py admin 段新增：admin.run_infra_breaker.threshold（默认 3）、admin.run_infra_breaker.cooldown_minutes（默认 30）。