# spec-verify-unreachable-failfast

## ADDED Requirements

### Requirement: 可达性自愈失败即本轮 fail-fast

验证阶段2.5 中，`_ensure_app_reachable` 返回 `(reachable=False, user_blocked=False)` 时，框架 SHALL 立即结束本轮验证：MUST NOT 重读场景文件、MUST NOT 创建/运行 `VerifyEngine`（场景执行数=0）、MUST NOT 退回 plan 重排；SHALL 调用 `_escalate_env_blocked` 落 blocked（自动呼叫 Administrator，连续 2 轮冻结转人工）并自本验证轮 return。升级的 violations/evidence MUST 使用 `reach_note`（其已由 `add-verify-preflight-gate` D3 内嵌 boot.log 尾部）。短路路径 MUST NOT 产生 verification-report.md / report.json（与消费期轻量自证短路 D2 同语义）。

#### Scenario: 就绪探针超时短路本轮

- **WHEN** `_ensure_app_reachable` 因就绪探针超时（如 `就绪探针超时（120s）: http://127.0.0.1:50555/api/projects — timed out`）返回 `(False, False, note)`
- **THEN** 不执行任何场景（场景执行数=0），不产生 verification-report.md，spec 落 blocked，`_escalate_env_blocked` 被调且 evidence 含该超时 note（含 boot.log 尾部），Administrator 收到自动呼叫

#### Scenario: prepare 失败同样短路

- **WHEN** 契约 prepare 步骤执行失败返回 `(False, False, "验证契约 prepare 失败: …")`
- **THEN** 与探针超时同款短路：0 场景、blocked、升级失败原因，绝不继续跑场景

#### Scenario: 契约缺失子案只补落态不重写信号

- **WHEN** 场景集含 web/api 但无 serve 配置（`_ensure_app_reachable` 内部已自写一条 `verify_contract_missing` 信号并返回 `(False, False, note)`）
- **THEN** 短路仅调用 `_escalate_env_blocked`，不追加第二条 `verify_contract_missing` 信号，告警 store 中该 spec 的该信号仍为一条

### Requirement: 可达时行为逐字节不变

`_ensure_app_reachable` 返回 `reachable=True`（或纯 cli 场景集/无 navigate 依赖等恒放行路径）时，短路点 MUST NOT 触发，验证流程与现状完全一致（照常重读场景、照常运行 `VerifyEngine`、照常走判定链）。

#### Scenario: 可达放行无副作用

- **WHEN** 应用可达（或纯 cli 场景集返回 `(True, False, …)`）
- **THEN** 场景照常执行，report 照常产出，判定链与既有逻辑逐字节一致，无新增失败类型

### Requirement: user_blocked 守卫（需用户参与不短路）

短路条件 SHALL 显式包含 `not user_blocked`。当 `_ensure_app_reachable` 返回 `user_blocked=True`（需用户参与而无法自动验证的预留判定位，当前实现恒 `False`）时，MUST NOT 进入短路分支，维持既有后续路径，为将来「收验证码/登录」类场景保留不误杀的通道。

#### Scenario: 预留判定位放行

- **WHEN** 将来实现返回 `(False, True, "需用户登录后重试")`
- **THEN** 不短路、不落 blocked（至少不因本守卫落 blocked），走既有后续处理路径