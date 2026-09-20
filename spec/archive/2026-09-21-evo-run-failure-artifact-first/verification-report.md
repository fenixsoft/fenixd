# 验证报告：evo-run-failure-artifact-first

> ⚠️ 本报告由框架于 2026-09-15T09:33:46Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-15T09:33:46.917679+00:00

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.49M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| review-artifact-first-suite-green | 运行 tests/test_review_artifact_first.py 全部测试通过（2.1 产物优先消费/2.2 回退语义/2.3 事故回放/1.3 infra 识别，单测级验证） | pass | 0/3 | - |
| spec-review-agent-regression-green | 运行 tests/test_spec_review_agent.py 全量回归通过（含 TestArtifactFirstNoReentry 防回退：不重派、不重复消费；锚点/消费/写入边界既有语义不回归） | pass | 0/3 | - |
| artifact-landed-valid-five-conditions | 直接驱动 _artifact_landed_valid 判定五条件真值表：approved/repaired→合法 True；文件缺失/非法JSON/status=failed/mtime 陈旧/快照不一致→False（spec 产物合法判定充分条件全覆盖） | pass | 0/2 | - |
| artifact-first-consumption-end-to-end | 端到端产物优先消费（exit code 1 + approved 产物已落盘）：dispatch_review 返回 True、状态推进 ready、_review_attempts 不递增、run 仅执行 1 次（不重派）、_on_spec_ready 恰一次 | pass | 0/2 | - |
| artifact-first-retry-fallback-paths | 三种回退路径维持既有重试语义：产物缺失 / status=failed / 快照不一致 → 均走 _handle_review_failure、_review_attempts 递增 1、状态保持 reviewing、dispatch_review 返回 False | pass | 0/2 | - |
| classify-run-failure-infra-fingerprints | 直接驱动 _classify_run_failure 指纹表：402/403/429/quota/budget/余额/insufficient balance/rate limit（大小写不敏感）→ infra+正确指纹；None/空/内容类失败 → content | pass | 0/2 | - |
| artifact-first-replay-402-incident | 回放 2026-09-14 事故 run 1789368468：exit code 1 + error='API Error: 402 余额不足' + approved 产物已落盘 → 结论被消费而非作废（状态 ready、attempt 不递增、_on_spec_ready 恰一次） | pass | 0/2 | - |
| infra-marking-suffix-and-evidence | infra 标记透出（D2）：_handle_review_failure 达上限冻结时 error 保留用户指令冻结前缀 + 含 [infra: 402] 后缀、告警 evidence 含 infra_fingerprint=402；content 失败 error 无 [infra: 后缀且保留 spec-review-incomplete: 前缀 | pass | 0/2 | - |
| artifact-first-consume-idempotent-no-redispatch | 防回退（D3）：产物优先消费后不重派（run 仅 1 次、状态 ready、_on_spec_ready 恰一次）；reviewer_run 清空后重复 consume 返回 False 幂等不再动作（状态不变） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

