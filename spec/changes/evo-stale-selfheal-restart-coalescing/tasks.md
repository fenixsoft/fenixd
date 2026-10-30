## Deliverables

```yaml
- path: fenixd.py
  kind: modify
- path: core/config.py
  kind: modify
- path: tests/test_stale_selfheal_coalescing.py
  kind: new
```

## 1. 合流窗实现

- [ ] 1.1 fenixd.py：在 `_maybe_stale_selfheal_tick`（:2330 附近）实现跨批次合流——同一陈旧悬置周期内首次陈旧仍按 `stale_code_selfheal.idle_confirm_seconds`（缺省 600s）确认重启；该周期内后续陈旧边沿的空闲确认闸改用 `stale_code_selfheal.coalesce_idle_seconds`（缺省 1800s）；悬置消化（磁盘 mtime 不再超进程 baseline）后合流状态复位；重启后以 restart_history 最近自愈重启记录做幂等校验防状态丢失错乱。
- [ ] 1.2 core/config.py：新增 `stale_code_selfheal.coalesce_idle_seconds` 配置键（缺省 1800，支持项目级覆盖，沿用既有 idle_confirm_seconds 的覆盖模式），并在配置注释写明动机（600s 收编窗盖不住 17-27 分钟批间隔连发，见 2026-10-18 五连重启窗）。
- [ ] 1.3 fenixd.py：保持既有交互语义不变——关键路径 preflight 重启请求（core/code_stale_flag.py `request_restart`）不经合流闸；4h 悬空强转（max_dangling_seconds）优先级高于合流闸；防循环冷却滑窗仍按实际重启次数计数；合流等待期内每次边沿记 info 日志（第 N 次边沿、当前生效闸值），重启时记合流收敛结果。

## 2. 测试

- [ ] 2.1 tests/test_stale_selfheal_coalescing.py：覆盖首启陈旧按 600s 基础闸重启、合流期内第二次边沿按 1800s 合流闸、边沿消化后合流复位（下次陈旧重回基础闸）、preflight 请求通道不受合流闸延迟、悬空满 4h 强转兜底仍生效。
- [ ] 2.2 tests/test_stale_selfheal_coalescing.py：覆盖配置键项目级覆盖缺省值、合流等待日志留痕字段（边沿序号与闸值）、restart_history 幂等推导（模拟重启后内存状态丢失不误升闸）。