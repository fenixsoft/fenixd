## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: tests/test_daemon_errors_selfheal_exemption.py
  kind: new
```

## 1. 自愈签名豁免注册表

- [ ] 1.1 core/admin_monitor.py：新增模块级「自愈签名注册表」常量（条目含 component 匹配、message 前缀、自愈消费者说明；首两条：worktree_manager×Merge-back blocked by WIP overlap precheck (policy=escalate)、pm_engine×Promotion lint failed）；在 _detect_daemon_errors 升级 append 前（:5143 一带，与既有冷却窗/孪生/跨日压制分支同层）加签名匹配跳过分支；命中留可审计计数。
- [ ] 1.2 core/admin_monitor.py：豁免只压制升级告警与重启建议文案，不删除/不改写 daemon 日志 ERROR 行，不影响既有三条压制路径的行为。

## 2. 源头聚合

- [ ] 2.1 core/worktree_manager/mergeback.py：precheck escalate 拦截出口（:746-764 一带）在同一次合回的重试窗口内聚合——首条拦截保持 ERROR（首阻取证），重试序号>0 的重复拦截降级为聚合 INFO 行（含 retry 序号与间隔），不重复落 ERROR 行。

## 3. 测试

- [ ] 3.1 tests/test_daemon_errors_selfheal_exemption.py：覆盖①WIP 重叠签名重复 ERROR 不产生 critical 且日志行保留；②非豁免签名（构造新错误形态）仍正常升级；③merge-back 重试 3 次仅 1 条 ERROR+2 条聚合 INFO；④豁免命中计数可读。