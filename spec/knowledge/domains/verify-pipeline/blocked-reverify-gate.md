# BLOCKED 重验直通道
<!-- knowledge: capability=blocked-reverify-gate rev=1 sources=spec/archive/2026-09-18-add-blocked-reverify-lane -->

环境阻塞类冻结的 spec 在 admin 处置完成后的复位路径裁定：实现分支已合并时直通重验（跳过全量重实现），否则回 ready 重派实现。

## 现行规则

- 适用范围：`_escalate_env_blocked` 写入的 blocked（`_env_block_rounds >= 1` 且非人工冻结）。product-bug 打回修复、实现阶段熔断、inconclusive 暂停、fast-track 车道不走本通道。
- 直通重验条件：admin 处置完成且结果为 resolved / partially-resolved，且实现分支已合并进主树（branch 字段非空且该分支的 merge commit 存在于主树历史）→ 框架调用 `transition_gate(spec, "testing")` 直通重验（`GATE_TRANSITIONS` 声明 `BLOCKED: [TESTING]`），清 error、保留 implementer_run/branch/`_env_block_rounds`，verifier 入队重验；全程不产生新 implementer run，`_impl_run_budget_used` 不变。
- 回退通道：branch 为空（实现阶段冻结）或分支未合并 → 处置完成复位走既有 blocked→ready，implementer 正常重派实现。
- 人工路径约束：对 blocked spec 直接调用 `transition(spec, "testing")` 一律拒绝（`VALID_TRANSITIONS` 中 BLOCKED 仅允许 READY）；仅 `transition_gate` 加专用守卫条件满足时放行，与 VERIFIED→TESTING 逃生门同款约束。
- 复位动作归框架：`verify_env_blocked` 自动呼叫 admin 的提示词把处置范围限定为环境修复（依赖/服务/端口/容器/验证产物），处置收尾由框架在消费 disposition result 的位置内建复位判定（branch 已合并→testing 直通，否则→ready）；Administrator 不手动写 spec 状态。人工手动复位（如 Dashboard unfreeze）保持兼容，不重复派发、不清零计数。
- `_env_block_rounds` 生命周期累计：清零点仅两处——验证通过（verified 落定）与人工 `unfreeze_spec`；处置复位（无论目标态）、daemon 恢复、fix 链打回等一切中间转换不清零。字段以显式常量（`ENV_BLOCK_ROUNDS_FIELD`）登记进 state_machine 字段名单。冻结阈值维持 `rounds >= 2`：spec 生命周期内第 2 次 env 阻塞即结构化冻结转人工，唯一出路为人工 `unfreeze_spec`（同时清零 rounds 与 error）。

## 溯源

- 2026-09-18 add-blocked-reverify-lane（spec/archive/2026-09-18-add-blocked-reverify-lane） — 新增 BLOCKED→TESTING 重验直通道、admin 处置复位收敛为框架机械动作、`_env_block_rounds` 改生命周期累计（此前 admin 复位清零架空冻结门，且 blocked→ready 复位必然触发全量重实现空跑）
