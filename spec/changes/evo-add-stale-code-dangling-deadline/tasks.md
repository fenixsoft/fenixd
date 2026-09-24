## Deliverables

```yaml
- path: fenixd.py
  kind: modify
- path: core/config.py
  kind: modify
- path: tests/test_stale_code_selfheal.py
  kind: modify
```

## 1. 配置键

- [ ] 1.1 core/config.py：在 stale_code_selfheal 配置族新增 max_dangling_seconds 键（缺省 14400 秒，0 = 关闭升级），声明缺省常量并纳入 get_stale_code_selfheal_config（config.py:1396）返回结构，负值回退缺省

## 2. 悬空计量与超时重启

- [ ] 2.1 fenixd.py：_update_stale_code_state（fenixd.py:1011-1103）在 _code_stale 假→真边沿记录悬空起点 _code_stale_since（UTC），进程启动即陈旧时取启动时刻；真→假恢复时清零
- [ ] 2.2 fenixd.py：_maybe_stale_selfheal_tick（fenixd.py:1535-1724）新增悬空超时分支——_code_stale 为真且悬空超过 max_dangling_seconds 时不再等 _is_idle，直接写 .fenix/restart_request 并按既有路径记录 self_triggered；分支保持受既有 cooldown/self-triggered 闸门（fenixd.py:1645-1686）约束
- [ ] 2.3 fenixd.py：超时分支防重复写（restart_request 已在场或已置位标志则跳过），避免主循环 1s tick 每秒重复 touch

## 3. 升级告警

- [ ] 3.1 fenixd.py：超时分支首次触发时写 signal_type=stale_code_dangling_timeout、severity=warning 告警，不写入即 mark_handled（参照 stale_selfheal_cooldown 的写入模式 fenixd.py:1382-1422，勿复用写入即 handled 的 stale_code 类型），写入前经 latest_signal 60 分钟去重

## 4. 测试

- [ ] 4.1 tests/test_stale_code_selfheal.py：覆盖忙时悬空超时即 touch .fenix/restart_request（不等空闲）、未超时不触发、max_dangling_seconds=0 关闭、升级告警保持 unhandled 且 60 分钟去重、cooldown/self-triggered 闸门仍生效
- [ ] 4.2 tests/test_stale_code_selfheal.py：覆盖基线恢复新鲜后 _code_stale_since 清零、超时触发后置位防重复写