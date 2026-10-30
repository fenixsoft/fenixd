# 新验证流程连续降级熔断

<!-- knowledge: capability=legacy-degrade-prerequisite-gate rev=1
     sources=spec/archive/2026-10-30-fix-worktree-lock-release-degrade-gate -->

新验证流程（三阶段）失败降级 legacy verifier 的熔断门：首次降级照旧，连续第 2 次降级转人工——一次性失败不再被放大为验证通道的无限静默劣化。

## 规则

- **连续降级熔断**：同一 spec 的新验证流程因失败降级到 legacy verifier 时维护连续降级计数——**首次**降级维持既有行为（降级派发 legacy verifier + WARNING 留痕）；**连续第 2 次**到达降级决策点时 MUST NOT 自动派发 legacy verifier，改 blocked + 升级告警，告警文案附两次降级的原因链；不产生第三轮静默降级。
- **计数持久化与清零**：连续降级计数为 spec 级、持久化于 spec STATE 条目（对齐既有验证计数字段先例），MUST NOT 落 PMEngine 实例属性或模块级变量（PMEngine 按 run 重建实例、模块级变量跨 spec 串扰）；计数随成功验证轮、admin 处置或人工解冻清零（与既有验证计数清零口径一致、复用 unfreeze_spec 清零集同一原子写）——熔断恢复后后续首次失败重新获得既有降级机会。
- **告警通道**：熔断告警走既有 human-escalation-alert 通道，文案含 spec、两次降级原因、建议动作（核对 worktree 状态后重验）。

## 关键行为

治理对象是降级链的放大效应：异常路径（如 worktree 陈锁秒败）令新验证流程反复失败 → 反复静默降级 legacy → legacy 通道 verdict 协议失配放大浪费。源头治理见 [worktree-lock-terminal-release](../worktree-vc/worktree-lock-terminal-release.md)（陈锁秒败不再发生）；本能力兜底「降级仍然连续发生」的场景，使劣化对人工可见。

## 溯源

- 2026-10-30 fix-worktree-lock-release-degrade-gate（spec/archive/2026-10-30-fix-worktree-lock-release-degrade-gate） — 新增本能力：连续降级计数（spec 级 STATE 持久）与第 2 次降级转人工熔断（动因实测：陈锁秒败 → 新验证流程静默降级 legacy → verdict 协议失配间接放大 39 分钟验证两轮作废）
