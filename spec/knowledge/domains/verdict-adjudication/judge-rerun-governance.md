<!-- knowledge: capability=judge-rerun-governance rev=1 sources=spec/archive/2026-09-27-add-verify-lane-throughput -->

# judge 重跑治理

同一 spec 同一验证轮内的 judge 重裁决治理：轮内派发计数达阈值即停派转人工，低置信优先证据扩充，fast-track 命中率可观测。

## 现行规则

- 重裁决计数与阈值升级：验证管线按（spec, 验证轮）维度维护 judge 派发计数，真实派发（非 fast-track 复用命中）每次递增，计数随验证轮重置（bug-found 修复进入新一轮验证时从零计）。
- 本轮真实派发次数达到 2 且仍需再次派发 judge 时，MUST NOT 发起第 3 次派发：① 发送人工升级告警（复用既有 human-escalation-alert 通道，内容含 spec、验证轮、历次 judge 结论摘要）；② spec 保持可重试状态（不冻结、不销毁产物），人工处置后重入 testing 按正常路径执行。
- 与既有机制并存：`_judge_dispatch_gate` 的 spec 级重跑硬上限（`_MAX_JUDGE_RERUNS=5`）与 verdict 稳定复用快道保持不变；轮内阈值（2）先于全局硬上限（5）触发；稳定复用命中（gate 返回合成结果）即 fast-track 命中，MUST NOT 计入真实派发。
- 低置信优先证据扩充：judge 产物被判定低置信（缺 evidence、evidence 截断等可补类型）时，管线优先触发证据扩充路径（对该判定项补齐证据后局部重判），MUST NOT 直接整轮重派 judge；证据扩充每轮至多 1 次，扩充后仍低置信的按重裁决计数处理（扩充非重派，不递增真实派发计数）；不可补类型（结论冲突、产物损坏）直接按重裁决计数处理。
- fast-track 命中率可观测：读侧数据层在 spec 级 summary 字段中暴露 `judge_fasttrack_hits`（快道复用次数）与 `judge_real_dispatches`（真实派发次数），按验证轮累计；统计来源为既有 fast-track 复用门的判定记录；字段缺失（历史 spec 无记录）时读侧 fail-open 呈现空值，不抛异常。前端组件展示非本能力要求。

## 溯源

- 2026-09-27 add-verify-lane-throughput — 确立（spec, 验证轮）重裁决计数与阈值 2 停派升级、低置信证据扩充优先（每轮至多 1 次）与 judge fast-track 命中率 summary 字段
