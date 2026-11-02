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

- [x] 1.1 fenixd.py：在 `_maybe_stale_selfheal_tick`（:2411）实现跨批次合流——合流期内首次陈旧边沿仍按 `stale_code_selfheal.idle_confirm_seconds`（缺省 600s）确认重启；此后在合流静止期届满前再检出的边沿，空闲确认闸改用 `stale_code_selfheal.coalesce_idle_seconds`（缺省 1800s）；合流态跨越重启存续：按闸重启导致的悬置消化不复位合流态，复位条件为「悬置消化（磁盘 mtime 不再超进程 baseline）且静止期届满（距最近一次陈旧边沿或最近一次按闸自愈重启达 coalesce_idle_seconds 无新边沿）」；重启后进程更替致内存状态丢失时，以 restart_history 最近自愈重启记录（该文件仅自愈路径写入）做幂等推导双向防错——记录在静止期内延续合流态，超窗/无记录按新周期基础闸。
- [x] 1.2 core/config.py：新增 `stale_code_selfheal.coalesce_idle_seconds` 配置键（缺省 1800，支持项目级覆盖，沿用既有 idle_confirm_seconds 的覆盖模式），并在配置注释写明动机（600s 收编窗盖不住 17-27 分钟批间隔连发，见 2026-10-18 五连重启窗）。
- [x] 1.3 fenixd.py：保持既有交互语义不变——关键路径 preflight 重启请求（core/code_stale_flag.py `request_restart`）不经合流闸；4h 悬空强转（max_dangling_seconds）优先级高于合流闸；防循环冷却滑窗仍按实际重启次数计数；合流等待期内每次边沿记 info 日志（第 N 次边沿、当前生效闸值），重启时记合流收敛结果。

## 2. 测试

- [x] 2.1 tests/test_stale_selfheal_coalescing.py：覆盖首启陈旧按 600s 基础闸重启、基础闸重启后静止期内第二批边沿按 1800s 合流闸（模拟 10-18 形态：批间隔 20-28 分钟、各批落于上批重启后 1800s 内）、末批后连续空闲达 1800s 收敛为一次重启、悬置消化且静止期届满后合流复位（下次陈旧重回基础闸）、preflight 请求通道不受合流闸延迟、悬空满 4h 强转兜底仍生效（含持续连发下合流闸不满足由强转收尾）。
- [x] 2.2 tests/test_stale_selfheal_coalescing.py：覆盖配置键项目级覆盖缺省值、合流等待日志留痕字段（边沿序号与闸值）、restart_history 幂等推导（模拟重启后内存状态丢失：记录在窗内延续合流态、超窗回退基础闸）。