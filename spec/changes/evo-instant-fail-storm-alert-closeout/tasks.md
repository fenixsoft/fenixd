## Deliverables

```yaml
- path: core/alert_lifecycle.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/self_review.py
  kind: modify
- path: tests/test_alert_lifecycle.py
  kind: modify
```

## 1. 注册表登记与写入点埋点

- [ ] 1.1 core/alert_lifecycle.py：_SIGNAL_CONDITIONS（:112-125）登记 instant_fail_storm→CONDITION_SPEC_DELIVERED_ADJUDICATED（terminal-only：仅 pushed/done/archived 收口），:393-411 收口注记按 signal_type 中性泛化（现 :404-407 硬编码 spec_delivered_no_content 文案）
- [ ] 1.2 core/agent_runner/runner.py：_alert_instant_fail_storm（:8438-8478）写入点对 entry 调 attach_trigger（:144-154）埋点
- [ ] 1.3 存量收口路径：盘点 admin 台账全部未 handled 的 instant_fail_storm 条目（评审实测：87f72c680499 已于 2026-10-28T02:12:34Z 人工 handled，当前台账无悬置条目；盘点结论留痕）。若存在悬置条目，按「一次性补写 terminal-only trigger 后走既有自动盘点」或「人工 handled（留痕）」收口；MUST NOT 把 instant_fail_storm 加入 BACKFILL_SIGNAL_TYPES（core/alert_lifecycle.py:66）——回填路径复用「非 blocked 即解除」语义（evaluate_alert :412-414），与 terminal-only 冲突；收口不得误伤在途合理待处理 escalation（如 a58c46957e35）

## 2. 龄期盘点与死亡取证

- [ ] 2.1 core/self_review.py：未处理 escalation 龄期盘点在全量未 handled 台账上计算登记龄期、超 24 小时标注提醒（MUST NOT 复用 :2227-2239 的创建窗口过滤集——调度窗口为 [last_run_at, now] 增量（:672），窗口内明细按构造不可能含超 24 小时条目；窗口内统计行口径不变；与 admin_monitor 节流兼容、同日幂等）
- [ ] 2.2 core/agent_runner/runner.py：_record_instant_fail（:8354-8436）秒挂死亡路径留存子进程启动 stderr 尾部与 worktree 状态快照（有界）

## 3. 测试

- [ ] 3.1 tests/test_alert_lifecycle.py：instant_fail_storm 告警在 spec pushed/done 后自动 resolved（留痕不删）、冷却中非终态不提前收口（负例回归锚）、存量无 trigger 条目按所选路径收口且不误伤在途条目
- [ ] 3.2 补齐目标 2/3 的测试交付：龄期盘点（全量台账口径、超 24 小时标注、窗口明细口径不回归）落 tests/test_daily_self_review.py；秒挂死亡取证快照（有界留存、失败路径不阻断计数）落 tests/test_agent_runner.py 或 tests/test_instant_fail_cooldown_gate.py，与功能同批验收