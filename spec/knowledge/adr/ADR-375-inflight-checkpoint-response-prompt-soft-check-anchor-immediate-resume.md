# ADR-375：在飞车道旗标响应走 prompt 批边界软自检、退出必落锚、锚即时续审

date: 2026-11-17
status: accepted

## Context

restart checkpoint 广播（broadcast_restart_checkpoint）落旗标后全仓零读取方，code-review 车道不响应：其 run 无 Python 层波次循环（单次 `_run_agent` 派发、agent 进程内自切批直写分片），drain-preserve 按 worktree→spec 保全集操作、code-review 无 worktree 结构性不在保全集；writeoff 锚消费嵌在每日周期函数内、被 last_run_date 同日防重闸挡住——被杀当日只能等次日调度节拍，形成 22 小时覆盖空窗。

## Decision

1. 旗标响应以 prompt 注入批边界自检实现（软约束、尽力而为）：每批分片直写后读旗标，置位则完成当前批收尾（分片落盘 + 终态抢救写毕）即退出、不开启新批；不把 code-review 改造成 Python 层波次循环。旗标路径与广播侧单源（run_files 常量/helper，经 runner re-export），杜绝广播与读取两处字面路径漂移。
2. 旗标响应退出路径 MUST 落 writeoff-pending 锚——success 收场亦落锚；不落锚则剩余清单退回次日节拍，与锚即时续审目标脱节。
3. writeoff 锚消费从每日周期函数抽为独立周期扫描，挂 AdminMonitor 巡检 tick（缺省 5 分钟）；绕过同日防重闸的判据 =「锚在册」（同日闸语义是当日已完成一轮，锚在场恰证明当日未完成）；夜窗顺延与单飞闸保留。
4. 后续无 spec 绑定、无波次循环的新维护车道响应重启旗标，沿同一形态：prompt 批边界自检 + 退出落既有锚链路，不各造旗标协议。

## Consequences

- 覆盖空窗从次日调度节拍压缩到分钟级；agent 不遵从自检时退化为既有排水窗等待 / SIGTERM + 抢救落账行为，无新增风险面。
- 自检是软约束，单批超窗仍可能被 SIGTERM，排水保护不承诺全保；批粒度是「等收尾」的下限。
- 锚即时续审的重试环由巡检周期天然承担（续审失败锚保持或抢救重写、下一 tick 重入），不引入独立重试预算。
