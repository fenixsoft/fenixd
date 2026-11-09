# 工作树与版本控制
> 最后更新：2026-11-09 17:58 UTC+8

实现工作树（worktree）的隔离、播种、回读与卫生与 spec 锁终态释放/陈锁清扫，已合并实现/验证分支随清扫的宽限期自动回收，分支基线解析与提交数判定的单源口径，实现分支合回主树与推送的完整生命周期纪律（推送 git 子进程环境与凭证双腿确定性、done 态推送退避的周期扫描自动续推），主树 WIP 占用归因单源（在飞车道与活交互会话只读探测），主树流水线外未提交改动的周期盘点与滞留升级，主树 untracked 散件的滞留超限升级与自动认领、盘点时钟持久化、越阈会话归因豁免、目录 ignore 前置免疫与首现预防提示，主树白名单文件脱落的独立巡检告警。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [worktree-isolation](worktree-isolation.md) | worktree 隔离与路径锚定（Popen cwd 隔离、路径锚定防线、跨树操作纪律、脚本项目根定位、dist 回退假象判别） | 2026-11-04 16:30 |
| [worktree-spec-seeding](worktree-spec-seeding.md) | worktree SPEC 播种 | 2026-10-03 04:59 |
| [worktree-result-readback](worktree-result-readback.md) | worktree 结果回读 | 2026-10-03 04:59 |
| [worktree-hygiene](worktree-hygiene.md) | worktree 卫生与复用（启动期孤儿清扫、冻结保全现场清理豁免） | 2026-11-09 17:36 |
| [run-isolation](run-isolation.md) | run 工作树隔离与冲突恢复（锁归属诊断；锁冲突告警=重复派发判读、归属禁 glob 前缀） | 2026-11-04 15:55 |
| [worktree-acquire](worktree-acquire.md) | worktree 获取退避等待与降级计数（自适应预算封顶 + 竞争类降级分流留痕） | 2026-10-11 01:47 |
| [merge-back](merge-back.md) | merge-back 合并回主树（闸门链与自愈链、自愈覆盖边界、上游 spec 目录自动提交夹带面、hunk 手术分拣提交与跨进程手工合回收尾配方、dist 不入库自动重建） | 2026-11-04 17:07 |
| [merge-back-precheck](merge-back-precheck.md) | merge-back 预检（WIP 交集升级拦截） | 2026-10-03 04:59 |
| [wip-defer-merge-retry](wip-defer-merge-retry.md) | WIP 阻断延迟合回（等待标志 + 周期自动合回；语义冲突形态接线缺口与人工 SOP） | 2026-11-06 18:06 |
| [mergeback-wip-active-coordination](mergeback-wip-active-coordination.md) | 合回 WIP 占用者识别与事件驱动重试（无主宽限升级） | 2026-10-09 03:24 |
| [maintree-stray-wip-sweep](maintree-stray-wip-sweep.md) | 主树散件 WIP 周期只读盘点与滞留升级（内容指纹计时 + 无主宽限一次性 major 告警带复发计数与裁决选项 + 会话归因留痕状态收敛） | 2026-10-31 16:23 |
| [stray-untracked-escalation](stray-untracked-escalation.md) | 主树 untracked 散件滞留超限升档 major 自动唤起认领（24h/体积双路升级 + 归档/ignore/删除三裁决） | 2026-10-30 19:51 |
| [stray-escalation-clock-persistence](stray-escalation-clock-persistence.md) | untracked 散件盘点注册表持久化（时钟跨重启连续、同指纹一次性跨重启去重、损坏 fail-open、惰性清理） | 2026-10-30 21:11 |
| [untracked-stray-session-attribution](untracked-stray-session-attribution.md) | untracked 散件越阈会话归因豁免（三态处置复位宽限计时、升级 evidence 归因注记分档、keep 单键回退） | 2026-10-30 21:11 |
| [whitelist-tracked-patrol](whitelist-tracked-patrol.md) | 主树白名单文件脱落巡检（negation 放行未跟踪＝脱落，major 告警 + 指纹去重复位 + 四处登记唤起） | 2026-10-30 20:56 |
| [maintree-wip-attribution](maintree-wip-attribution.md) | 主树 WIP 占用归因单源（在飞车道求交 + 活交互会话只读探测 + 采信回退单键） | 2026-10-09 03:24 |
| [spec-amendment-watch](spec-amendment-watch.md) | 主树 spec 目录在飞修订探测与预警（merge-back + 周期扫描双入口） | 2026-10-08 02:46 |
| [merge-circuit-breaker](merge-circuit-breaker.md) | merge 熔断（失败指纹） | 2026-10-03 04:59 |
| [merge-rehearsal](merge-rehearsal.md) | 合并预演与语义冲突直通修复（接线仅实现主路径站点） | 2026-11-06 18:06 |
| [merge-untracked-guard](merge-untracked-guard.md) | 未跟踪文件合并守卫 | 2026-10-03 04:59 |
| [mergeback-inplace-repair](mergeback-inplace-repair.md) | merge-back 原位修复（repair 车道） | 2026-10-03 04:59 |
| [mergeback-stashpop-self-heal](mergeback-stashpop-self-heal.md) | stash pop 自愈（含悬空 autostash 人工找回配方：fsck 筛选与 --3way 静默跳过陷阱） | 2026-11-04 16:30 |
| [mergeback-archive-residue-selfheal](mergeback-archive-residue-selfheal.md) | merge-back 归档残留自愈（熔断出口前置只读评估 + 自动收尾重放）与顺延链周期消费者 | 2026-10-13 18:00 |
| [stashpop-conflict-treatment](stashpop-conflict-treatment.md) | stash pop 冲突处置 | 2026-10-03 04:59 |
| [push-ref-hygiene](push-ref-hygiene.md) | 推送引用生命周期卫生 | 2026-10-03 04:59 |
| [push-credential-environment](push-credential-environment.md) | 推送 git 子进程环境与凭证确定性（HOME 三级解析单源显式注入、凭证 URL+文件双腿、承载层 HOME 基线、启动凭证自检） | 2026-11-09 17:58 |
| [push-retry-recovery](push-retry-recovery.md) | done 态推送退避续推（周期扫描消费通道跨重启存活、四重门与耗尽收敛、executor 非阻塞投递） | 2026-11-09 17:58 |
| [恢复续做基线分支可移植解析](resume-base-branch-portability.md) | 分支相对基线提交数判定单源经共享解析器（origin/HEAD → main → master → 回退 main） | 2026-10-08 04:02 |
| [receiver-debug-artifact-ignore](receiver-debug-artifact-ignore.md) | 调试产物目录 ignore 豁免（.debug/ 目录级条目、check-ignore 命中即全链免疫、现场零扰动） | 2026-10-30 23:11 |
| [stray-first-sight-prevention](stray-first-sight-prevention.md) | 散件首现预防提示（目录集合首现一次 info 提示带 ignore 草案、不升级不唤起、复位后再现重提示）+ 交付落盘覆盖检查点 | 2026-10-30 23:11 |
| [worktree-lock-terminal-release](worktree-lock-terminal-release.md) | worktree spec 锁终态释放与陈锁清扫（owner 归属、失败终态即释、superseded 不释防双派发、acquire 死亡判据清扫含弃置件） | 2026-10-30 23:11 |
| [merged-branch-gc](merged-branch-gc.md) | 已合并 fenix 分支自动回收（stale_sweep 内四条件判定、`-d` 语义硬边界、活跃豁免两守卫并集、宽限期与开关配置） | 2026-10-31 16:31 |
