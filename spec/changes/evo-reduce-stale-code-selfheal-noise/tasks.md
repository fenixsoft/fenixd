## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/StaleCodeSelfhealPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: tests/test_stale_selfheal_idle.py
  kind: modify
- path: tests/test_stale_code_selfheal.py
  kind: modify
```

## 1. 重启合并

- [ ] 1.1 core/config.py：将 STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT（core/config.py:1488）由 120 改为 600，并同步 get_stale_code_selfheal_config 的 docstring（:1552 起）中的缺省值说明；项目级 stale_code_selfheal.idle_confirm_seconds 覆盖路径（:1572）与热更新语义不变。
- [ ] 1.2 fenixd.py：核对 _maybe_stale_selfheal_tick（fenixd.py:1735，空闲累计与判定 :1958-1975）在新缺省下的行为——空闲计时复位仅由非空闲信号（活跃 run / 在飞评审 run / admin 在途）与陈旧解除触发（原稿「新代码落地重置计时」不成立，见 design R1 评审修正），合批来自 600 秒窗内落地批次被同一轮重启收编，按此口径覆盖密集批次仅一轮重启；不改动 cooldown 五键（core/config.py:1492-1496）与 60 秒 drain（core/config.py:1317）语义。

## 2. 告警降噪

- [ ] 2.1 core/admin_store.py：在 :28 附近新增 info 级 kind 常量（如 INFO = info），并把 INFO 加入 latest_signal 的 kind 白名单（:542，否则 60 分钟去重对 info 级失效）；确认 mark_handled 仅匹配 ESCALATION 的闭环锚点口径（core/admin_store.py:380/:388/:400/:444）不受新 kind 影响。
- [ ] 2.2 fenixd.py：改造 _update_stale_code_state 的告警写入块（fenixd.py:1192-1216）——selfheal enabled 且未悬空超限时（写入时点可判定谓词，见 design R2）以 info 级 kind、severity info 写入 admin_alerts.json，附当日累计计数日志（以存储当日同信号记录数计，跨重启存活）；写入记录自带 handled=true + handled_at（不经 mark_handled 接口），「无需人工干预」文案（:1208-1212）随级别同步改写；60 分钟去重（fenixd.py:158、:1177）对 info 级继续生效（依赖 2.1 白名单）。
- [ ] 2.3 fenixd.py：escalation 分流反面——selfheal disabled 沿用既有写入块 escalation 分支、悬空超 max_dangling_seconds（core/config.py:1500）由既有 _alert_dangling_timeout（fenixd.py:1555）承接，均不改；自愈动作失败（restart_request 写失败，fenixd.py:1984-1986 OSError 分支）为**新增** escalation 写入点（append + latest_signal 去重范式，signal_type=stale_code）；不双重升级。
- [ ] 2.4 core/dashboard/data/config_admin.py：生效配置缺省 seeds（:450-451）与注释同步 idle_confirm_seconds 缺省 120→600。
- [ ] 2.5 core/dashboard/static：StaleCodeSelfhealPanel.tsx DEFAULT_IDLE_SECONDS（:9-10）与 services/dashboard.ts 注释（:1263-1269）同步缺省 600，并按仓库既有 dashboard 前端构建流程重建 dist——防止设置页以 120 回填表单、用户保存即把 120 显式写回项目配置、静默覆盖新缺省。

## 3. 测试

- [ ] 3.1 tests/test_stale_selfheal_idle.py：覆盖缺省 idle_confirm_seconds=600 的解析、项目显式覆盖优先级、缺省下密集批次（空闲窗内反复落地）仅触发一轮自愈重启。
- [ ] 3.2 tests/test_stale_code_selfheal.py：更新锚定旧缺省 120 与 escalation 的既有断言；新增覆盖 selfheal enabled 且健康时写 info 级加日计数日志且去重生效、selfheal disabled 或失败或悬空超限时仍 escalation、info 级记录不进 pending_escalations 同口径清单。
- [ ] 3.3 core/dashboard：验证未知 kind=info 告警记录不致前端告警列表/历史/SPEC 时间轴渲染报错，且不出现在 pending_escalations 同口径清单（kind 过滤消费方清单见 design「兼容与风险」）。