# ADR-019：同根缺陷修复通道先到先得，族谱繁衍硬上限

date: 2026-09-02
status: accepted

## Context

bug-found 缺陷存在两条合法修复通道：recovery 重实现（上下文 = spec 文档 + 验证报告）与 judge 派生子 fix（上下文 = 靶向缺陷报告）。两通道由不同节拍触发、互不知情，实证双 ready 并行实现直接 merge 冲突、数十轮空转。同时族谱自动繁衍把一次验证失败的修复成本乘上嵌套深度，无收敛边界。

## Decision

- 同根缺陷任一时刻至多一条修复通道 actionable（ready 含实现队列条目 / implementing / 存在活跃实现 agent）。重置、spawn、派发三个激活边界各设守卫，各自判定「同根对面通道是否 actionable」，是则抑制自己；不做「谁上下文更好」的主观裁决——重复才是成本。
- 先到先得、证据互链：被抑制方在 error/evidence 写明「修复由 <对方 spec>（通道 X）承载」，dashboard 可见、审计可溯。
- 仅 ready 而无队列条目不算 actionable（防僵死 ready 永久阻塞）；子 fix 全部终态后守卫自动失效，父级重验路径畅通。
- 族谱深度（名字中连续 fix- 前缀层数）与宽度（同父未完成子代数）设硬上限：超限在子 spec 创建前拦截，不发 spec_bug_found 副作用，改发族谱爆炸人工信号；Administrator 放行时设置单次豁免位，放行一轮后重归限制。

## Consequences

- 修复成本从「通道数 × 嵌套深度」收敛为单通道有界繁衍；极端场景仍有人工豁免出口。
- 双通道同时卡死的残局由 blocked 巡检兜底唤起人工，非静默；同根判定复用 fix- 前缀规则，与族谱度量共用一套命名语义。
