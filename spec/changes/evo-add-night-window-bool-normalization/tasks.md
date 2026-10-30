## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/config.py
  kind: modify
- path: tests/test_code_fix_night_quiet_window.py
  kind: modify
- path: tests/test_code_review_night_defer.py
  kind: modify
```

## 1. 解析单源硬化

- [ ] 1.1 core/code_fix.py：_night_quiet_window_disabled/_parse_night_quiet_windows（:3350-3395）把布尔 false 与 off 同义处理、布尔 true 显式拒判，三消费点共享语义
- [ ] 1.2 core/config.py：沿用 _maybe_warn_deprecated_stuck_keys（:3002）既有模式，配置载入期对 night_quiet_window 非法值（含布尔）一次性 WARNING
- [ ] 1.3 core/admin_monitor.py：_code_review_night_window_defer（:2015/2056）与 _night_dispatch_block_reasons（:6299-6302）静默 fail-open 处补与 code-fix 车道同款告警对等（进程级去重）

## 2. 停用态提醒

- [ ] 2.1 core/code_fix.py：窗值停用（显式 off 或布尔）期间每日至多一条聚合提醒（复用 _write_night_quiet_window_alert 通道）

## 3. 测试

- [ ] 3.1 tests/test_code_fix_night_quiet_window.py：false→禁用语义、布尔 true 拒判、载入期 lint 触发、每日提醒节流断言
- [ ] 3.2 tests/test_code_review_night_defer.py：布尔入参下审查顺延守卫路径与告警对等断言