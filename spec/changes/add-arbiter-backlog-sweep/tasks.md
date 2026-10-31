## Deliverables

```yaml
- path: core/pm_engine/arbiter.py
  kind: new
- path: tests/test_arbiter_backlog_sweep.py
  kind: new
```

设计真相源：`docs/superpowers/specs/2026-10-31-arbiter-lane-design.md` + 本 SPEC design.md。依赖 add-arbiter-lane（派发时 arbiter.py 已在 main，故 modify）。

## 1. 存量回扫

- [x] 1.1 core/pm_engine/arbiter.py：启动回扫入口——daemon 启动后（arbiter.enabled=true）与 config 热更新 disabled→enabled 跃迁时各执行一次（每进程每条跃迁至多一次）；扫描 STATE 中 frozen=true 且 admin_alerts 存在同 spec 未处理（pending）机器升级告警的存量 spec，frozen_until 非空排除；命中者经既有 dedup/单飞/预算管线入队派发，幂等由同签名 dedup 兜底（回扫与事件触发竞写同签名不重复派发）
- [x] 1.2 restart_request 信号落位（仓库根，JSON：reason/origin/date，reason 注明「arbiter 存量回扫需 daemon 重启加载」）+ 消费预演（全新进程 import 链 + 回扫入口注册自检断言），实际重启由 supervisor 消费信号完成

## 2. 测试

- [x] 2.1 tests/test_arbiter_backlog_sweep.py：存量冻结回扫派发（evo-refine 型现场：frozen=true+同 spec pending 机器升级告警→入队派发）；回扫排除语义三态（frozen_until 非空定时冻结 / frozen 但无成对 pending 告警的人工冻结形态 / enabled=false）；幂等（二次回扫与事件触发先后命中同签名不重复派发）；回扫入口每进程每跃迁至多一次
