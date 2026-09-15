# verdict-result-integrity 增量规格

## ADDED Requirements

### Requirement: 硬门校验本轮实际产出
planner-judge 产物硬门 MUST 在 worktree verify-progress 拷回主树**之后**执行，使门检对象为本轮 run 真实写出的结果文件；拷回逻辑保持既有 mtime 守卫（主树缺失或 worktree 版本较新才覆盖）。

#### Scenario: worktree 侧写入不再绕过门检
- **GIVEN** judge 以相对路径把结果文件写入 worktree `.fenix/verify-progress/<spec>/.fenix-run-result.json`，且该文件为非法 JSON
- **WHEN** run 以 exit 0 结束
- **THEN** 拷回先行、门检随后校验主树路径上的该文件
- **AND** 非法 JSON 被门检拦截，走瞬态退避重试通道
- **AND** 上一轮残留的旧合法文件不再能替本轮产物放行

### Requirement: 硬门新鲜度约束
planner-judge 产物硬门 MUST 校验结果文件 mtime 不早于本轮 attempt 启动时刻；早于启动时刻的文件按「本轮零产物」处理。

#### Scenario: 陈旧残留文件被新鲜度拦截
- **GIVEN** 主树存在上一轮写入的合法结果文件，本轮 judge 未产出任何结果文件
- **WHEN** 门检执行
- **THEN** 门检因 mtime 早于本轮 attempt 启动时刻而失败
- **AND** 走瞬态退避重试通道，run 不被判为 success

### Requirement: 硬门 status 白名单
planner-judge 产物硬门 MUST 校验结果文件顶层 `status` ∈ `{verified, bug-found, plan-ready, scenario-repaired}`（与读侧共用同一白名单常量）；白名单外取值按产物缺失处理。

#### Scenario: 语义错位 status 被门检拦截
- **GIVEN** judge 把顶层 status 写成 `success`（verdict 语义错位）
- **WHEN** 门检执行
- **THEN** 门检失败并附实际 status 值，走瞬态退避重试
- **AND** 该文件不再流入读侧被「unknown status 视为 verified」

### Requirement: 读侧裁决 fail-closed
三阶段验证的裁决采纳处，结果文件**缺失 / 非法 JSON / status 白名单外** MUST NOT 晋级 verified：系统重派 judge 一次后复读；二次仍不可读 → spec blocked + critical 告警 `verdict_result_unreadable`（正文含解析错误原文与结果文件完整路径），不推进 bug-found、不派生 fix。

#### Scenario: 裸换行破坏裁决文件（add-verify-contract-autodraft 同款）
- **GIVEN** judge 判 bug-found 但结果文件 summary 字符串含未转义换行，json.loads 抛 Invalid control character
- **WHEN** 裁决采纳处读取结果
- **THEN** 不晋级 verified；重派 judge 一次并复读
- **AND** 二次仍不可读 → spec blocked、发送 critical 告警（含 `Invalid control character at: line 25 column 402` 原文）
- **AND** 重试产物合法时按其 status 正常路由（bug-found → fix 链；verified → done）

#### Scenario: 合法裁决路由不回归
- **WHEN** 结果文件合法且 status=verified / bug-found / scenario-repaired
- **THEN** 既有路由行为不变（含全绿快道机械写回后的 verified 采纳）

### Requirement: legacy 验证路径同门
旧版单体 verifier 路径的结果文件不可读（缺失/非法 JSON/白名单外）MUST NOT 晋级 verified：spec blocked + 同款 `verdict_result_unreadable` 告警；不自动重派整轮 verifier。

#### Scenario: legacy 不可读结果不洗白
- **GIVEN** legacy verifier run 成功返回但结果文件非法 JSON
- **WHEN** legacy 采纳处读取
- **THEN** spec blocked、发送 critical 告警（含错误原文）
- **AND** 不发生 implemented/blocked → verified 的任何转换
