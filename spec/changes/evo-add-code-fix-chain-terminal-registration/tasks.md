## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix_disabled_terminal_registration.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/code_fix.py：checkpoint() 的 disabled 终态分支（write_progress(phase="blocked", reason="disabled") 所在路径，现 5008-5053 行附近）在写终态进度的同时落 admin 告警与 todo 待办登记，文案含终态原因、剩余未修复条数（total-done）与 dashboard 修复链重新触发入口提示
- [ ] 1.2 core/code_fix.py：同一 disabled 期去重——登记前检查现存进度已是 disabled 终态则跳过；override_enabled 重新触发路径翻回 live 后去重窗口自然重置，链再次 disabled 时落新登记

## 2. 测试

- [ ] 2.1 tests/test_code_fix_disabled_terminal_registration.py：覆盖三形态——首收口落双登记（告警+todo 各一条且含剩余量与触发提示）、disabled 后重复 checkpoint 零新增登记、重新触发后再次 disabled 落新登记