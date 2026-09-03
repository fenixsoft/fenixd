# Design: fix-repair-lane-dedup

## Context

bug-found 的 fix spec 存在两条合法但互不知情的修复通道：
- 通道 A（重实现）：full_scan recovery 见 bug-found → 重置 ready → 重派实现器（上下文 = spec 文档 + verification-report.md）
- 通道 B（派生子 fix）：judge 判定验证报告 bug-found → 派生深度+1 子 fix（上下文 = 靶向 12 缺陷报告）

两条由不同触发源激活（扫描节拍 vs judge 节拍），时序交错不可预测。当日实证三连：fix#1 重实现与 fix#2 派生先后就绪（双 ready）；fix#1 重实现器 81 turns 通读零提交；更早的 fix#1/fix#2 并行实现直接 merge 冲突。

## Goals / Non-Goals

**Goals:**
- 任一时刻，同根缺陷最多一条修复通道处于 actionable（ready/implementing）
- 先到先得：不杀在飞工作，抑制后到者
- 零配置、对无子无在飞的正常路径零行为差异

**Non-Goals:**
- 不改族谱深度/宽度治理（独立正交）
- 不做跨根去重（不同父的 fix 各自独立合法）
- 不改 push 卫生与验收闭环

## Decisions

- **D1 三级守卫，覆盖全部时序**。同根缺陷的双通道激活只可能发生在三个边界：reset 路径（守卫一）、spawn 路径（守卫二）、dispatch 路径（守卫三）。三处各自判定"同根对面通道是否 actionable"，是则抑制自己。判定依据复用族谱度量（同根 = 去一层 fix- 前缀同根；非终态 = 非 done/pushed/blocked）。
- **D2 先到先得，证据互链。** 被抑制方在 error/evidence 写明"修复由 <对方 spec>（通道 X）承载"，dashboard 可见、审计可溯。不做"谁上下文更好"的主观裁决——两通道上下文都足以修复（A 有 spec+report、B 有靶向 report），重复才是成本。
- **D3 派发守卫的活跃定义。** 同根兄弟 status ∈ {ready(其队列含实现器条目), implementing} 或存在活跃 impl/verify agent（worktree 进程判定，复用孤儿白名单的存活探测）→ 视为 actionable。仅 ready 无队列条目不算 actionable（防僵死 ready 永久阻塞）。
- **D4 子终态解封。** 守卫判定只在"存在非终态子 fix"时生效；子 done/pushed 后守卫自动失效，"Fix done — re-verifying original" 父级重验路径畅通，不误伤。

## Risks / Trade-offs

- [两通道都被外部因素卡死（如同时 blocked）→ 无人修复] → blocked 有 blocked_stuck 巡检兜底唤起 Administrator，非静默
- [同根判定对特殊命名误判] → 复用族谱度量的 fix- 前缀规则（已被 family governor 验证）
- [守卫三的队列条目检查依赖内部结构] → 只读 _run_queue 不改结构，单测覆盖

## Migration Plan

随 daemon 重启生效，回滚 revert。无配置无数据迁移。

## Open Questions

- 无
