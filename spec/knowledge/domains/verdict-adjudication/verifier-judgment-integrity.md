<!-- knowledge: capability=verifier-judgment-integrity rev=1 sources=spec/archive/2026-09-02-fix-dispatch-orphan -->

# verifier 判定完整性

agent run 终态与验证晋级口径的完整性护栏：进程假成功被拒、半程验证不得晋级、死锁可自动逃逸、取证产物在结算前留存。

## 现行规则

- agent_runner 对以 rc==0 结束的进程解析 result 终止事件：`is_error` 为真或 `subtype` 属错误类（如 `error_during_execution`）时判定为失败并 raise；result 缺失时维持既有行为不收紧（向后兼容）。API 错误包装的「假成功」（exit 0 + is_error）不会被判成功。
- pm_engine 在 verifier 运行成功后、执行 testing→verified 转换前核对验证进度 `done >= total`：进度不完整、缺失或损坏时按 verifier 失败处理（进入 attempt 重试或既有失败语义流转），进度摘要写入 error 字段，禁止晋级 verified。该核对仅在晋级路径 fail-closed，既有 done 放行门禁的 fail-open 语义保持不变。
- 状态机允许 VERIFIED→TESTING 合法转换，仅限门禁拦截触发的自动回退路径调用；回退保留 implementer_run 与既有 progress 断点，重派验证器按既有场景断点续跑。人工操作路径直接调用该转换仍被转换表校验拒绝。
- attempt 运行产出的 `.fenix/runs/<run_id>.jsonl` 在该 attempt 结算（成功转 verified/implemented，或失败耗尽 retry）之前持续存在并可读；任何组件删除 runs 下产物时，删除动作以日志形式留痕。

## 溯源

- 2026-09-02 fix-dispatch-orphan（spec/archive/2026-09-02-fix-dispatch-orphan） — 确立 agent 终态语义校验（is_error/subtype 判失败）、verified 晋级前完整性核对（fail-closed）、VERIFIED→TESTING 逃生门（仅门禁自动路径）与 run 产物生命周期持久性
