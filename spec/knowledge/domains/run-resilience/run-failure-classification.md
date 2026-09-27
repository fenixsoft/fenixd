<!-- knowledge: capability=run-failure-classification rev=1 sources=spec/archive/2026-09-21-evo-run-failure-classification-circuitbreaker -->

# run 失败三级分类与熔断

run 执行失败按 infra / 内容 / 判别三级分流处置：基础设施故障触发链路熔断冷却，内容失败走机械重试，判别失败按产物消费。

## 现行规则

- infra 失败识别：失败原因匹配 infra 指纹（403/402/429/quota/budget/余额/insufficient balance/rate limit）、provider 熔断信号（"provider circuit open" / "provider chain exhausted"，供侧熔断同属 infra）、CLI 进程级崩溃（error 含 "Exit code:" 且无内容语义——"Exit code: 1" 不得一律判 infra，评审器内容失败同样 exit 1）或 probe 标记（`model_chain_preflight_failed`）。
- infra 熔断：同一链路连续 infra 失败 ≥3 次即熔断该链路——停止派发、落 kind=escalation、signal_type=`run_infra_failure`、severity=critical 告警（evidence 含链路、指纹、次数、时间窗）；进入冷却窗口（缺省 30 分钟），窗口结束自动恢复重试。告警不唤起 Administrator（评审链路 infra 对 admin 无杠杆）。熔断接驳范围 v1 仅 spec-review 链路，verify/impl 链路留后续 SPEC；分类函数保持链路无关。
- infra 失败的 STATE 副作用：清 `reviewer_run`、不递增 `_review_attempts`（熔断前与冷却期均不计入）——否则冷却到期后 dispatch 见锚点非空拒派、spec 永久卡 reviewing，且第 3 次 infra 同时触 `MAX_REVIEW_ATTEMPTS` 冻结破坏自动恢复。
- 内容失败（含空白轮次）：维持既有语义——`_review_attempts` 机械重试至上限 3 后 `freeze_for_human`。
- 判别失败（产物已落盘）：按产物消费（run-failure-judgment 承接），不重试；产物合法性判定复用 `_artifact_landed_valid`，该依赖未实现时 artifact 分支回退 content。
- 边界：不改评审内容质量硬门（approved/repairs 一致性等）、不改 verifier 结果读取单源、不做派发前探活（`model-chain-preflight` 承接）。

## 溯源

- 史前复原 — 迁移期基线：verifier/judge 的基础设施类失败不流转 bug-found，守护原状态等待重排；伪失败与产品失败分流处置
- 2026-09-21 evo-run-failure-classification-circuitbreaker — 确立 infra 指纹识别、连续失败链路熔断与 30 分钟冷却、infra 失败清锚点不计内容重试的 STATE 副作用
