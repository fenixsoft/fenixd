## 背景

2026-10-05 potplayer-base 项目 pack2-official-encoder 实现者首轮 run（impl-…-1791177321-a1）把最后约两小时（约 300+ 轮）耗在救模拟器相机链路上：给宿主 v4l2loopback 打内核补丁、降级 emulator、换镜像，全部失败后于 07:19Z 被 600 轮上限击杀，成本未入账；二轮同 session 58 轮/$3.22 即收尾。同型形态当日二连（neutralize-pack-static-fingerprints 首轮 12600s 烧穿+二轮 876s 收尾）。design.md 早已预设「相机桥不可用即收口回退」条款且在开局首读上下文中，但无强制力。

## 问题

1. 实现者提示词（agents/implementer.md）对环境阻塞类任务无止损硬规则，实现者把环境问题当可修复问题深挖，且弃 design 已有 fallback 条款于不顾。
2. 框架对「长时间无任务完成」无观测预警：kill_early（缺省关闭）只在末位扩容判定点一次性消费任务进度（remaining_tasks ≥阈值且零进度才杀），latency 停滞预算（未配置）只看往返时长与产物 mtime——两者都不提供「自最近任务完成起 N 轮」的连续观测维度。

## 方案

- 提示词硬规则：同一环境依赖连续 ≥3 次失败尝试（按尝试计数，不按错误签名——本案错误码一路 ENODEV→ENOSYS→ENODEV 变化）即冻结该任务，design 有 fallback 条款先走 fallback，否则登记 unfinished 转 partial 继续其余任务；禁止在 run 内为救单个验证场景对宿主做内核级/镜像级不可逆改造。
- 框架观测面：对 impl run 增加「自最近任务完成起 N 轮」计数，超阈 WARNING+注记（判据用 run 流内 TaskUpdate，不用主树 tasks.md 的 remaining_tasks——worktree run 期间后者恒静态）。

## 非目标

- 不改既有预算 sizing/kill_early/latency 停滞预算的判定语义；预警只做观测面，不驱动击杀。
- 不禁宿主的幂等环境预置（verify.yaml prepare 层），只禁 run 内为救单个场景的不可逆改造。