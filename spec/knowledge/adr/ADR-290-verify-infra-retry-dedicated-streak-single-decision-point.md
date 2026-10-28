# ADR-290：infra-retry 预算专用计数与升级决策点单点化

date: 2026-10-28
status: accepted

## Context

模拟器类验证场景的环境性失败此前只有一条全价通道：prepare/可达性 fail-fast 汇入 `_escalate_env_blocked`（计 env 冻结轮 + Administrator 自动呼叫 + 连续 2 轮冻结转人工），infra 侧唯一让步是预算退款，车道不变。cfc 类场景两天内反复触发整轮空转与多轮 judge 烧费（600 轮诊断 run 击杀、豁免后四轮 $4.6）。廉价重试需要一本「连续短路失败」预算账，但既有 `_verify_infra_rounds` 不可复用——它被 `_escalate_env_blocked` 既有挂钩点在每个全价 env 阻塞轮递增、唯一归零点为验证 PASS，跨验证周期累计的历史轮会吃掉重试预算，使「缺省 2 次」承诺不可达（评审实测确认）。同时若在调用点绕开升级函数另起入账路径，双决策点会双重入账、口径漂移。

## Decision

1. infra-retry 廉价重试预算用专用连续重派计数 `_verify_infra_retry_streak`（复用 state_machine `_bump_counter` 机制），与 `_verify_infra_rounds` 观测账严格分离、互不递增对方判定；观测账保持既有语义（两车道照常递增、归零点不变）。
2. 清零点契约=验证 PASS（对齐 `_verify_fail_rounds` 唯一归零点）+ unfreeze_spec 清零清单（同一原子写）；其余中间转换一律不清零——否则达预算冻结→人工解冻后首轮短路失败即立即再升级，预算不可再得。
3. 决策点单点收敛：fail-fast 调用点保持调用 `_escalate_env_blocked`（infra_retry 标记全仓唯一传点，该分支同时覆盖 prepare 失败与可达性失败两条汇入路径），由升级通道入口先经 `_record_infra_failure(retry_gate=True)` 咨询限次决议；该调用兼任唯一入账点（退款/观测轮/失败台账照常），escalate 决议后禁二次记账，调用点禁另起入账路径。
4. 预算读 `verify_engine.infra_retry_max`（缺省 2）；None/非数字/bool/非正值一律回退缺省。决议不可得（计数/记账异常）保守按「达预算」落全价升级，不无限廉价重试。
5. 重派机械路径经既有 verifier 派发入口重新入队，不绕派发队列直调；infra-retry 车道不增减同因重派熔断记账（`_redispatch_same_cause_streak`/`_redispatch_cause_fp`），与既有各熔断/退避通道独立记账互不喂入。

## Consequences

- 两本账并存增加状态复杂度，须以测试锁定互不污染。
- 最坏多烧 N 次短路轮（0 场景执行成本），远低于一次全价升级（admin run + 冻结轮）。
- 短路轮旁路期间零全价写点（不写 blocked/status/error、不落 env 信号、不呼叫 admin），env 豁免/冻结语义零污染；场景执行期 env 阻塞分类不带该标记，车道只覆盖 0 场景执行的确定性短路轮。
- 后续触碰验证重试/升级记账的 SPEC 禁混用两账、禁绕开升级咽喉另设决策点；放宽车道覆盖面（如场景执行期场景级重试）须重新评估整轮重派成本并显式立项。
