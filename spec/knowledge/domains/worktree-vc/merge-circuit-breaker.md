<!-- knowledge: capability=merge-circuit-breaker rev=2 sources=spec/archive/2026-09-02-fix-fenix-token-waste,spec/archive/2026-09-09-add-merge-back-repair-lane -->

# merge 熔断（失败指纹）

merge-back 反复以相同原因失败时的熔断器：按稳定失败指纹计数，达阈值即停自动重试转人工，防止无产出重试烧预算。

## 现行规则

- 失败指纹：对 implementer merge-back 失败的错误信息做归一化哈希，得到稳定失败指纹。
- 熔断触发：同一 spec 的同一指纹连续失败达到阈值（默认 2 次）→ spec 置为 `blocked` 状态并停止自动重试，等待人工介入；错误信息记录指纹。
- 人工恢复：人工确认根因消除并将状态重置为 `ready` 后，恢复对该 spec 的正常调度。
- 不同指纹不熔断：首次以指纹 F1 失败、重试后以不同指纹 F2 失败 → 按既有重试逻辑处理（`_retry_count` 递增），不进入 blocked。
- repair 轮不重置计数：repair 通道（mergeback-inplace-repair）轮次不重置连续计数——repair 失败后 fallback 重派引发的 merge-back 失败与前序失败连续累计；repair 中插轮后仍以相同指纹失败即达阈值进入 blocked。
- blocked 后 repair 一并停止：spec 因 merge 失败熔断进入 blocked 且实现分支仍存活时，不再派发 repair agent，等待人工介入。
- 派发前的主树健康检查（autostash 收纳与恢复）现行语义由 merge-back 闸门链承载，见 merge-back 能力页。

## 溯源

- 2026-09-02 fix-fenix-token-waste（spec/archive/2026-09-02-fix-fenix-token-waste） — 新增 merge 失败指纹熔断（同指纹连续 2 次 blocked、人工重置恢复）与派发前主树 autostash 健康检查（该检查现行语义已并入 merge-back 闸门链）
- 2026-09-09 add-merge-back-repair-lane（spec/archive/2026-09-09-add-merge-back-repair-lane） — 熔断与 repair 通道记账打通：repair 轮不重置连续计数、blocked 后 repair 一并停止
