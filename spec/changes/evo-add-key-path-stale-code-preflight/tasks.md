## Deliverables

```yaml
- path: core/code_stale_flag.py
  kind: new
- path: fenixd.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/knowledge.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_key_path_stale_preflight.py
  kind: new
```

## 1. 陈旧旗标共享通道

- [ ] 1.1 core/code_stale_flag.py：新增模块级注册表——register(is_stale 回调) / is_stale() 查询；未注册时 is_stale() fail-open 返回 False；线程安全（daemon 检测线程写、车道线程读）；不产生任何 IO。
- [ ] 1.2 fenixd.py：daemon 启动初始化与 _update_stale_code_state 每 30 秒检测点把 self._code_stale 同步进注册表（只做旗标转发，不改任何既有判定逻辑）。

## 2. 关键路径执行前预检

- [ ] 2.1 core/pm_engine/engine.py 收尾提交路径：verification-report 入库的 git commit 执行前查询 is_stale()；陈旧则记一条 WARNING（含「代码陈旧，已请求重启」语义）并确保 .fenix/restart_request 存在（已存在不重复写、不刷 mtime），随后照常完成提交，不改变返回值与产物。
- [ ] 2.2 core/knowledge.py 蒸馏派发路径：dispatch 入队前同款预检（WARNING + restart_request 防重 + 照常派发）。
- [ ] 2.3 core/admin_monitor.py choice 执行路径：_apply_choice_execution 调 execute_adjudication_choice 前同款预检（WARNING + restart_request 防重 + 照常执行）。

## 3. 测试

- [ ] 3.1 tests/test_key_path_stale_preflight.py：覆盖注册/查询/未注册 fail-open 三态；三个关键路径在旗标置位时各产生 WARNING、restart_request 被创建且动作返回值与产物和 不预检时一致；restart_request 已存在时不重复写；旗标未置位时零新增副作用。
- [ ] 3.2 回归确认 tests/test_stale_code_selfheal.py 全量通过（自愈触发、空闲阈值、悬空超时、告警分级行为不变）。
