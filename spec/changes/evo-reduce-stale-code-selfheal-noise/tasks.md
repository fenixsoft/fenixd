## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: tests/test_stale_selfheal_idle.py
  kind: modify
- path: tests/test_stale_code_selfheal.py
  kind: modify
```

## 1. 重启合并

- [ ] 1.1 core/config.py：将 STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT（core/config.py:1488）由 120 改为 600，并同步 get_stale_code_selfheal_config 的 docstring（:1552 起）中的缺省值说明；项目级 stale_code_selfheal.idle_confirm_seconds 覆盖路径（:1572）与热更新语义不变。
- [ ] 1.2 fenixd.py：核对 _maybe_stale_selfheal_tick（fenixd.py:1735，空闲累计与判定 :1958-1975）在新缺省下的行为——确认空闲确认窗内新代码落地会重置空闲计时、把密集批次合并为一轮重启；不改动 cooldown 五键（core/config.py:1492-1496）与 60 秒 drain（core/config.py:1317）语义。

## 2. 告警降噪

- [ ] 2.1 core/admin_store.py：在 :28 附近新增 info 级 kind 常量（如 INFO = info）；确认 mark_handled 仅匹配 ESCALATION 的闭环锚点口径（core/admin_store.py:380/:388/:400/:444）不受新 kind 影响。
- [ ] 2.2 fenixd.py：改造 _update_stale_code_state 的告警写入块（fenixd.py:1192-1216）——selfheal enabled 且健康时以 info 级 kind、severity info 写入 admin_alerts.json 并附当日累计计数日志，跳过自动 mark_handled（info 级无处理生命周期），「无需人工干预」文案（:1208-1212）随级别同步改写；60 分钟去重（fenixd.py:158、:1177）对 info 级继续生效。
- [ ] 2.3 fenixd.py：保留 escalation 分流反面——selfheal disabled、自愈动作失败、悬空超 max_dangling_seconds（core/config.py:1500）时仍以 escalation 写入，与 evo-add-stale-code-dangling-deadline 升级口径对齐，不双重升级。

## 3. 测试

- [ ] 3.1 tests/test_stale_selfheal_idle.py：覆盖缺省 idle_confirm_seconds=600 的解析、项目显式覆盖优先级、缺省下密集批次（空闲窗内反复落地）仅触发一轮自愈重启。
- [ ] 3.2 tests/test_stale_code_selfheal.py：更新锚定旧缺省 120 与 escalation 的既有断言；新增覆盖 selfheal enabled 且健康时写 info 级加日计数日志且去重生效、selfheal disabled 或失败或悬空超限时仍 escalation、info 级记录不进 pending_escalations 同口径清单。