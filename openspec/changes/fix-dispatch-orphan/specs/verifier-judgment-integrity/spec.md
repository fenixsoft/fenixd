# spec-verifier-judgment-integrity

## ADDED Requirements

### Requirement: Agent 终态语义校验
agent_runner 的 `_run_claude` 在进程以 rc==0 结束时 SHALL 解析 result 终止事件：`is_error` 为真或 `subtype` 属于错误类（如 `error_during_execution`）时 MUST 判定为失败并 raise；result 缺失时维持现行为（不收紧），保证向后兼容。

#### Scenario: API 错误包装的假成功被拒绝
- **WHEN** stream-json 产出 `{"type":"result","subtype":"success","is_error":true,"result":"API Error: 503..."}` 且退出码为 0
- **THEN** `_run_claude` 抛出 RuntimeError，run 文件末尾存在 error 行，agent 不会被判成功

#### Scenario: 正常完成不受影响
- **WHEN** result 终止事件无 is_error、subtype 非错误类且退出码为 0
- **THEN** 现有成功路径行为完全不变

### Requirement: verified 晋级前完整性核对
pm_engine 在 verifier 运行成功后、执行 testing→verified 转换前 SHALL 核对验证进度文件 `done >= total`；进度不完整、缺失或损坏时 MUST 按 verifier 失败处理（进入 attempt 重试或按既有失败语义流转）并将进度摘要写入 error 字段，禁止晋级为 verified。该核对仅在晋级路径 fail-closed，既有 done 放行门禁的 fail-open 语义保持不变。

#### Scenario: 半程死亡不再造成假 verified
- **WHEN** verifier 仅完成 5/17 后进程终止但被上层判为成功
- **THEN** 晋级被拦截，spec 保持 testing 并以失败处理进入重试，error 字段记录「验证未完成 5/17」

#### Scenario: 完整通过正常晋级
- **WHEN** verifier 完成 done=total 且运行成功
- **THEN** testing→verified 照常发生

### Requirement: VERIFIED 回退逃生门
状态机 SHALL 允许 VERIFIED→TESTING 的合法转换，仅限门禁拦截触发的自动回退路径调用；回退保留 implementer_run 与既有 progress 断点。

#### Scenario: 死锁逃逸
- **WHEN** 某 spec 处于 verified 但门禁检测到进度不完整
- **THEN** 自动回退到 testing 并重新派发验证器（断点续跑既有场景）

#### Scenario: 人工乱用被拦
- **WHEN** 直接对人工操作路径调用 VERIFIED→TESTING
- **THEN** 转换表校验仍拒绝（逃生门仅暴露给门禁自动路径）

### Requirement: run 产物生命周期持久性
attempt 运行产出的 `.fenix/runs/<run_id>.jsonl` SHALL 在该 attempt 结算（成功转 verified/implemented 或失败耗尽 retry）之前持续存在并可读；审计后若引入清理策略 MUST 记录日志。用于事故取证与 session resume 提取。

#### Scenario: 取证产物可用
- **WHEN** 某次 verifier 失败需要事后分析失败原因
- **THEN** 其对应 run jsonl 文件仍存在于 runs 目录且可解析

#### Scenario: 清理可观测
- **WHEN** 未来任何组件删除 runs 下产物
- **THEN** 删除动作以日志形式留痕
