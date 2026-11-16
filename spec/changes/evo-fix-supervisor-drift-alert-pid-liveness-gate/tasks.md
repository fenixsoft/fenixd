## Deliverables

```yaml
- path: fenixd.py
  kind: modify
- path: tests/test_daemon_lifecycle_races.py
  kind: modify
```

## 1. drift 判定补 pid 存活门控

- [ ] 1.1 fenixd.py：在 supervisor_runtime_drift 判定成条前（现 6542-6567 行段）读取 runtime 文件 pid 与 project_root 字段，按判定矩阵分支：pid 缺失或不可解析则维持现行为；os.kill 抛 ESRCH 则 warning「残留」；pid 存活且 /proc 下该 pid 的 cmdline 含 fenixd_supervisor 或 project_root 字样则降级 info；pid 存活但 cmdline 可读且两者均不含（pid 复用）则按残留走 warning；pid 存活但 cmdline 不可读则按存活降级 info。
- [ ] 1.2 fenixd.py：存活降级分支的 evidence 文案改为「长寿 supervisor 伴生（daemon 多代重启所致），无需处置」并移除「建议重启 supervisor」指引；pid 消失分支保留现「疑似 runtime 文件残留」叙事不变。
- [ ] 1.3 fenixd.py：修正 120-125 行设计假设注释——把「漂移超限必然是残留」的旧常态假设改为「supervisor 长寿、daemon 多代重启为本机常态，pid 门控区分伴生与残留」。

## 2. 测试

- [ ] 2.1 tests/test_daemon_lifecycle_races.py：新增用例覆盖存活 pid（os.getpid()）成条为 info 且文案不含「残留」「建议重启」；死亡 pid（已退出并回收的子进程 pid）成条为 warning 且保留「残留」叙事；pid 复用（cmdline 不匹配）按残留处理；runtime 文件缺 pid 字段时行为与现版本一致。
- [ ] 2.2 回归既有用例：test_stale_started_at_drift_warns 与 tests/test_supervisor_drift_log_dedup.py 全部通过，确认去重窗与 PROJECT_LOG 留痕行为未回归。