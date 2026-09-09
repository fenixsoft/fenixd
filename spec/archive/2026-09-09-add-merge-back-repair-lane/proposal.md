## Why

merge-back 因语义冲突失败时，框架只能 abort 后全新重派 implementer：add-dashboard-incremental-data 事故中第一个 implementer 烧掉 3.5 小时的工作全部作废，重派从零再来（"重派从零不做增量"早已是验证链浪费的确认根因之一）。产物类冲突自愈（be29a63）已兜住非语义冲突，语义冲突失败的全量重派是当前 merge-back 链路最大的 token 浪费点。

## What Changes

- merge-back 失败且产物自愈不适用（混入语义冲突）时，不再直接 abort+重派，进入 **repair 通道**：派 repair agent 基于实现分支原地修复
- 修复方向反转：repair agent 在实现分支一侧把 main merge 进分支并解决语义冲突，主树始终保持干净 abort 态，永不进入半合并态
- 以**分支**（而非 worktree 目录）为修复载体：原 worktree 存在则原地进入（保留 node_modules/构建缓存）；worktree 已清但分支在则在分支上开新 worktree；分支也不在则回退 fallback 正常重派
- repair agent 认领 `_legacy` 遗产时走与 fast-track 复用同款 take 动作（从 `_legacy` 摘出），防止 sweeper 宽限期竞态回收现场
- 预算与熔断协同：repair 轮计入该 spec 的实现预算；repair 失败回退 fallback 重派；merge 失败指纹熔断的连续计数贯穿 repair 与 fallback，repair 不绕过熔断
- repair prompt 精简为身份说明 + 冲突摘要 + spec 上下文，不再注入"原 worktree 地址"类间接情报（现场即所在，冲突状态 agent 自查）
- 边界不变：verify 失败的 fix 链（工作已并入主树，无可打捞）不走 repair；implementer 中途死亡的 takeover 复用（`_legacy`/`_active_reuse`）保持既有行为，统一收口留作后续 SPEC

## Capabilities

### New Capabilities
- `mergeback-inplace-repair`: merge-back 语义冲突失败后的原地修复通道——repair 触发条件、分支载体三态（原地/换壳/fallback）、方向反转约束、遗产认领竞态防护、预算与熔断协同、prompt 形态

### Modified Capabilities
- `merge-circuit-breaker`: 明确 repair 通道与熔断的协同——repair 轮失败计入同一 spec 的指纹连续计数，repair 重试不重置也不绕过熔断阈值；blocked 后 repair 通道一并停止
