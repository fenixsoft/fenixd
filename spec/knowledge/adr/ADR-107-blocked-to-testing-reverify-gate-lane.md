# ADR-107：blocked→testing 重验直通道走逃生门，git 事实守卫

date: 2026-09-18
status: accepted

## Context

env 阻塞复位原样必走全量重实现（BLOCKED 在主状态机里只能回 ready），且复位路径清零让冻结计数永不可达；admin 被迫手动旁路状态机复位。状态机已有「白名单 + 专用守卫 + 人工路径受限」的逃生门先例（VERIFIED→TESTING）。

## Decision

- BLOCKED→TESTING 以逃生门模式接入（GATE_TRANSITIONS 白名单 + 专用 gate 转换），不进主转换表——人工路径不得自由直达 testing，直通道只在守卫条件满足时由调用方放行。
- 守卫以 git 事实为准：分支非空且 merge commit 已在主树历史（merge-base --is-ancestor，统一在主树执行；subprocess 异常按「未合并」处理回退 ready 通道——宁可多重实现不可错误直达）。
- 复位判定内建在 admin 处置收尾消费点（disposition 为 resolved / partially-resolved 且属 env 族信号）：已合并 → 直达 testing 清 error 入重验；未合并 / 无分支 → 既有 ready 通道。admin 提示词多处同步声明「勿手动 reset，框架收尾自动触发重验」；手动复位路径保留但同样不清计数。
- 阻塞轮数生命周期累计、清零点收敛（verified 落定与人工解冻两处）：连续第 2 次阻塞必冻结转人工，止损窗口收敛为「一次 admin 修复机会」。

## Consequences

- 实现已合并时 env 阻塞复位零实现轮直达重验（秒级），admin 处置闭环不再依赖手动状态操作；环境修复不彻底时重验更早再阻塞——比烧一轮 implementer 更早暴露、成本更低。
- daemon 重启丢失一次秒级重验为接受代价（testing 回退 ready 的既有语义不动）。
