## Context

全价通道现状：prepare/可达性失败链 core/pm_engine/verification/serving.py:962（纯 cli 主树）/:155（worktree）→ _ensure_app_reachable False → core/pm_engine/verification/pipeline.py:2119-2130 fail-fast → escalation.py:550 _escalate_env_blocked（_env_block_rounds 递增，ENV_BLOCK_FREEZE_THRESHOLD=2 于 core/state_machine.py:288；admin 呼叫写点 :666/:681）；场景执行后分类 core/verify_engine/env_gate.py:151 finalize_scenario_status 与 engine.py:570 _post_classify_environment（:344 调用、每轮一次、memoize :163 重置）。infra 现状：infra_classify.py:142 _record_infra_failure 仅预算退款+_verify_infra_rounds 记账+失败台账，车道不变；「infra-retry」core/ 与 tests/ 零命中。预检能力：core/verify_contract.py:1158 run_prepare_steps 任意 shell+600s 单步超时（:139）+主机 fcntl 锁（.fenix/verify-prepare.lock）+killpg 收组；模板 core/verify_contract_template.yaml。实证：10-05 admin-pack2-official-encoder-1791196033（600 轮击杀）、10-06 四轮 judge $4.5999、cfc-injection-fallback 4 断言 flaky 豁免。

## Goals / Non-Goals

- Goals：宿主/环境准备失败从「烧整轮+升级」变为「短路+限次重试」；项目有可直接抄的预检样板；env 冻结/豁免语义零污染。
- Non-Goals：不做框架级无主进程清理执行器（项目 prepare 层自治，避开 evo-add-host-change-governance 非目标张力）；不改场景期 env 分类；不改 admin 升级阈值与豁免语义。

## Decisions

- D1 infra-retry 只收口「0 场景执行的短路路径」（prepare 失败/可达性失败）：此路径尚未执行任何场景，重派边际成本最低；场景执行中的 env 失败仍走既有后置分类，不做场景级重试（重派整轮代价高、收益存疑，先不做）。
- D2 限次依据 infra-retry 专用连续重派计数（新字段，复用 state_machine._bump_counter 既有机制，如 core/state_machine.py:1606 bump_verify_infra_rounds 同款），阈值缺省 2 次后恢复全价升级：与 ENV_BLOCK_FREEZE_THRESHOLD=2 同量级，防预检失败被无限重试烧预算；infra-retry 轮 MUST NOT 递增 _env_block_rounds、MUST NOT 触发 admin 呼叫。**不复用 _verify_infra_rounds 作重试预算**：该账被 _escalate_env_blocked 既有挂钩点（escalation.py:584 → _record_infra_failure）在每个全价 env 阻塞轮递增，历史 env 轮会吃掉重试预算、使「缺省 2 次」承诺不可达（评审实测：state_machine.py:529-531 该账唯一归零点为验证 PASS，spec 生命周期内跨验证周期累计）。_verify_infra_rounds 保持既有纯观测语义（两车道照常递增，归零点不变）。专用计数清零点：验证 PASS（对齐 _verify_fail_rounds 归零点）+ 纳入 unfreeze_spec 清零清单（state_machine.py:2100-2112 既有清零清单，否则达阈值冻结→人工解冻后首轮 prepare 失败即立即再升级，「2 次」预算不可再得）。
- D3 预检本体留在项目 prepare 层、框架只给模板样板：OpenCV 冒烟属场景特异，进框架词表会把模拟器细节耦合进框架；模板注释形态零学习成本，potplayer-base 试点先行。
- D4 被杀 pid 留痕沿 prepare 既有日志通道（样板步骤内自行记录），框架不为预检新增留痕结构。
- D5 重派机械路径与派发护栏约定：infra-retry 重派须经既有 verifier 派发入口（core/pm_engine/dispatch/queue.py:2409 `agent_type == "verifier"` → _run_verification_pipeline）重新入队，MUST NOT 绕过派发队列直调；infra-retry 通道 MUST NOT 增减 `_redispatch_same_cause_streak` / `_redispatch_cause_fp`（fix-redispatch-loop-governance 3.3b 作用域清单扩充：该 streak 仍只在 queue.py:2292-2407 通用失败重派分支记账，infra-retry 车道不经该分支）。pipeline.py:2127 的 `not user_blocked` 守卫语义保留：需用户参与的可达性失败（预留判定位）不得被 infra-retry 短路自动重派。
- D6 决策点单点化：fail-fast 调用点保持调用 _escalate_env_blocked（新增 infra-retry 车道标记参数，仅 pipeline.py:2133 可达性 fail-fast 一处传入，该分支已同时覆盖 prepare 失败与可达性失败两条汇入路径），由 escalation 内部先咨询 infra_classify 决议——未达阈值：不递增 env 轮、不写 blocked/error、不呼叫 admin（:666/:681 写点不经过）、返回「重派」决议由 pipeline 触发 D5 重派；达阈值：原样走既有全价路径（计冻结轮、按 ENV_BLOCK_FREEZE_THRESHOLD 升级）。MUST NOT 在调用点绕开该函数另起入账路径（双决策点会双重入账、口径漂移）。

## Risks / Trade-offs

- infra-retry 可能重试注定失败的环境（如磁盘满）：限次 2 次封顶，最坏多烧一次短路轮（无场景执行成本），远低于一次全价升级（$1.5+admin）。
- 两本账（infra/env）并存增加状态复杂度：infra 台账已有（_verify_infra_rounds），仅新增消费点；测试覆盖互不污染。
- 模板样板可能被项目抄错（如误杀他人 qemu）：样板步骤自带归属判定指引（只清理 ppid=1 且可归属到已完成 run 的进程），与 10-06 处置记录先例一致。