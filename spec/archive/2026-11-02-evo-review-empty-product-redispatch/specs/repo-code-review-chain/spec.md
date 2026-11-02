# repo-code-review-chain：零产物止损与工具自救指引

## ADDED Requirements

### Requirement: 零有效行拦截后限次重派与升级

周期审查 run 的产物硬门判定为零有效行（或产物缺失）时，系统 SHALL 自动重派审查 run 至多 1 次（限次为 monitor 生命周期合计，与既有 429 重派通道同款语义；两通道 MUST NOT 对同一 run 链叠加调度）；重派产物仍为零有效行时，系统 SHALL 发出 admin 升级信号并停止自动重派。

#### Scenario: 首次零产物自动重派

- WHEN 周期审查 run 完成且产物硬门判零有效行
- THEN 自动重派 1 次审查 run 并记录重派事件

#### Scenario: 重派仍失败升级信号

- WHEN 重派 run 的产物仍为零有效行
- THEN 发出 admin 升级信号，不再自动重派

### Requirement: 拦截失败面外露

产物硬门拦截时，系统 SHALL 在完成行与升级告警中携带失败面摘要：run id、manifest 计数、命中变体（零有效行/产物缺失），供止损判定与事后取证入口（完整查询原文以档案 jsonl 为准）。

#### Scenario: 完成行携带失败面

- WHEN 硬门拦截发生
- THEN 完成行与告警字段含 run id、manifest 计数与变体标注

### Requirement: 审查提示词工具自救指引

审查 run 提示词 SHALL 预注工具自救指引：ToolSearch 仅索引延迟加载工具，对 Bash/Read/Write/Grep 等基础工具返回 No matches 属按设计，agent SHALL 直接调用基础工具，MUST NOT 凭检索空推断工具缺失并终止审查。

#### Scenario: 提示词含自救指引

- WHEN 构造周期审查 run 的提示词
- THEN 提示词包含「No matches 属按设计、直接调用基础工具」的自救指引段

### Requirement: 工具面预检留痕与终局结论行抢救

spawn 装配后系统 SHALL 执行一次工具面预检并留痕，run_metrics 收尾行 SHALL 携带工具面字段；审查 run 以 error 收场时，系统 SHALL 在既有分片/主产物抢救之外尝试抢救终局消息中的结论行，且 MUST NOT 触发全仓快照核销与 code-fix 检查点（红线与既有 error 收场抢救一致）。

#### Scenario: error 收场抢救终局结论行

- WHEN 审查 run 以 error 收场且终局消息携带结论行
- THEN 结论行被抢救留痕，且不触发全仓快照核销与 code-fix 检查点

#### Scenario: 工具面预检留痕

- WHEN 审查 run spawn 装配完成并进入收尾
- THEN 工具面预检结果作为 run_metrics 收尾行字段留痕