## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_drain_inflight_run_protection.py
  kind: new
- path: bin/fenixd_supervisor.py
  kind: reference
```

## 1. 排水窗扩容与一致性告警

- [x] 1.1 core/config.py：agents.run_drain_max_seconds 缺省 60→300（:2484 回退分支与 docstring :2424 一带）；shutdown≤0 的 SIGKILL 等待回退值按 :2488-2493 实际夹紧口径联动调整（config.py:2490 与 bin/fenixd_supervisor.py:160 DEFAULT_SIGKILL_WAIT_SECONDS 双侧同源），使缺省部署与 shutdown=0 部署的有效排水窗≥300；**该调整仅作用于 planned restart 收口路径，非规划性停机（stop flag）的 SIGKILL 等待语义不变**；在配置一致性校验段（:1378-1404 一带）追加分支：按同口径推导有效排水窗，低于申报值时输出含两个原始值与推导值的显式告警，不阻断启动。
- [x] 1.2 bin/fenixd_supervisor.py：核对 restart 收口路径的 SIGKILL 等待（shutdown+120 / shutdown≤0 回退，:160/:163 与 :415 一带）确实读取 admin.shutdown_drain_seconds 配置值——若读取则仅在 1.1 联动处对齐双侧同源建模；确认 stop 停止路径（:703-811）不受回退值调整影响并在 design 留对账说明。

## 2. code-review 车道响应重启旗标

- [x] 2.1 core/agent_runner/maintenance_runs.py：code-review run 无 Python 层波次循环（run_code_review :2858 为单次 _run_agent 派发、agent 自切批直写 batch_N.json 分片）——旗标响应以 prompt 注入实现：构建 prompt 时注入批边界自检指令（每批分片直写后读取 broadcast_restart_checkpoint（core/agent_runner/runner.py:10326）落位的旗标文件；置位则不再开启新批，完成已审分片与终态抢救文件写毕后退出）；旗标响应退出路径 MUST 写 writeoff-pending 锚（复用 error 收场抢救落账或显式写锚），使剩余清单进入锚即时续审链路（见 3.1）。
- [x] 2.2 core/agent_runner/runner.py：从 broadcast 侧导出旗标路径常量/读取 helper 单源，避免广播与读取两处字面路径漂移。

## 3. writeoff 锚即时续审

- [x] 3.1 core/admin_monitor.py：把 writeoff 锚检查（现嵌每日周期审查函数，:2323-2400）抽成独立可周期调用的方法，挂接到 AdminMonitor 既有巡检 tick（admin.interval_minutes 缺省 5 分钟）；命中未核销锚即派发剃余续审；绕过 last_run_date 同日闸（:2227-2229）的条件限定为「writeoff 锚在册」；保留夜窗顺延与既有单飞/except 复位闸（:2255-2262 骨架）。
- [x] 3.2 core/agent_runner/maintenance_runs.py：redispatch_of 在场时的档案注记 reason 由硬编码 429 ratelimit（:2953）改为 writeoff_resume，与 core/admin_monitor.py:2378-2400 对账键一致；runner.py:5230/5253 ratelimit 车道自身登记不在改动面。

## 4. 测试

- [x] 4.1 tests/test_drain_inflight_run_protection.py：覆盖①一致性门告警（shutdown=0 场景推导值告警留痕、不阻断；planned 有效窗推导含 shutdown≤0 回退联动）；②旗标置位时 prompt 含批边界自检指令、未置位时不含；③锚在册时周期扫描派发续审且绕过同日闸、锚核销后不再派发、夜窗顺延与单飞闸仍生效；④续审注记 reason=writeoff_resume；⑤旗标响应退出路径写 writeoff-pending 锚（success 收场亦落锚）。
