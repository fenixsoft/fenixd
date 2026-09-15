# run-failure-classification — run 执行失败三级分类与熔断

## 场景：infra 失败（403/402/预算耗尽/CLI 进程级）

- 识别：失败原因匹配 infra 指纹（403/402/429/quota/budget/余额/insufficient balance/
  rate limit）、既有 provider 熔断信号（"provider circuit open" / "provider chain
  exhausted"，runner.py:2458/2473——供侧熔断同属 infra）或 CLI 进程级崩溃（error 含
  "Exit code:" 且无内容语义——"Exit code: 1" 不得一律判 infra，评审器内容失败同样 exit 1），
  或 probe 标记（model_chain_preflight_failed）。
- 行为：同一链路连续 infra 失败 ≥3 次 → 熔断该链路（**v1 仅接驳 spec-review 链路**，
  verify/impl 链路留后续 SPEC）：停止派发、落 kind=escalation、signal_type=run_infra_failure、
  severity=critical 告警（evidence 含链路、指纹、次数、时间窗）；进入冷却窗口（默认 30
  分钟）；窗口结束自动恢复重试。告警不唤起 Administrator（评审链路 infra 对 admin 无杠杆）。
- **STATE 副作用**：infra 失败清 reviewer_run、不递增 _review_attempts（熔断前与冷却期
  均不计入）；否则冷却到期后 dispatch_review 见锚点非空拒派、spec 永久卡 reviewing，
  且第 3 次 infra 同时触 MAX_REVIEW_ATTEMPTS=3 freeze 破坏自动恢复。
- **依赖**：产物判定复用 evo-run-failure-artifact-first 的 `_artifact_landed_valid`（该
  SPEC 须先实现；未实现时 artifact 分支回退 content）。

## 场景：内容失败（含空白轮次）

- 行为：维持既有语义（_review_attempts 机械重试至上限 3 → freeze_for_human，spec_review.py:26）。

## 场景：判别失败（产物已落盘）

- 行为：按产物消费（run-failure-artifact-first 承接），不重试。

## 非目标

- 不改评审内容质量硬门（approved/repairs 一致性等）。
- 不改 verifier 结果读取单源（evo-verifier-result-single-source）。
- 不做派发前探活（model-chain-preflight 承接）。
- verify/impl 链路的熔断接驳不在 v1 范围（分类函数保持链路无关，接驳留后续 SPEC）。