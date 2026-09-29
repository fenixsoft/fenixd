<!-- knowledge: capability=verdict-result-integrity rev=1 sources=spec/archive/2026-09-15-fix-verdict-read-failclosed -->

# 裁决结果完整性（fail-closed 读取）

裁决结果文件（`.fenix-run-result.json`）产生、门检与消费全链的完整性：不可读的裁决永远不得等价于「验证通过」。

## 现行规则

- 硬门校验本轮实际产出：planner-judge 产物硬门在 worktree verify-progress 拷回主树**之后**执行（拷回保持既有 mtime 守卫：主树缺失或 worktree 版本较新才覆盖）；上一轮残留的旧合法文件不能替本轮产物放行。
- 新鲜度约束：结果文件 mtime 不早于本轮 attempt 启动时刻；早于启动时刻按「本轮零产物」处理，走瞬态退避重试通道。
- status 白名单：结果文件顶层 `status` ∈ `{verified, bug-found, plan-ready, scenario-repaired}`（与读侧共用同一白名单常量）；白名单外取值按产物缺失处理，不再流入读侧被「unknown status 视为 verified」。
- 读侧裁决 fail-closed：三阶段验证裁决采纳处，结果文件缺失 / 非法 JSON / status 白名单外 MUST NOT 晋级 verified——系统重派 judge 一次后复读；二次仍不可读则 spec blocked + critical 告警 `verdict_result_unreadable`（正文含解析错误原文与结果文件完整路径），不推进 bug-found、不派生 fix。重试产物合法时按其 status 正常路由（bug-found → fix 链；verified → done）。
- legacy 验证路径同门：旧版单体 verifier 路径的结果文件不可读（缺失/非法 JSON/白名单外）MUST NOT 晋级 verified——spec blocked + 同款 `verdict_result_unreadable` 告警，不自动重派整轮 verifier。
- planner-judge 结果文件写入契约：必须以合法 JSON 写入（字符串内换行/引号/控制字符须转义），建议用代码生成而非手工拼接。

## 溯源

- [2026-09-15 fix-verdict-read-failclosed](spec/archive/2026-09-15-fix-verdict-read-failclosed/) — 确立硬门时序（拷回后校验）与 mtime 新鲜度、status 白名单、读侧三态 fail-closed（重派一次后 blocked+告警）、legacy 路径同门与 judge 写入契约加固
