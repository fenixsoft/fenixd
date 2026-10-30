# proposal：verifier 进程级基础设施死亡分流

## 问题

verifier agent 进程在启动期即死（0 assistant 轮、0 token、单 attempt 存活 3-10 秒）时，失败结果仍流入裁决消费：core/pm_engine/verification/legacy.py:760-826 进程失败分支把 error 交 enrich_failure_class（core/pm_engine/verification/infra_classify.py:91-139），既有 infra 词表（provider 熔断/switch 类/conn 类/_INFRA_DEGRADE_MARKERS）均不命中 ENOENT 类启动期错误 → unknown → 按 product 保守处置 → bug-found → 原地打回。2026-10-14 add-harness-brand-projection 实测：dsh 补丁 ENOENT 秒死 3+3 试全灭，04:40:00Z 判 bug-found、04:40:01 原地打回，烧掉一轮 468.851s/97,790 token 零产出复核 run（唯一 commit 仅改 tasks.md 3 行），墙钟 18m44s。该消费缺口已确证第 2 次发生：2026-09-28 evo-fix-codefix-rollup-archive-read 的 worktree 形态（210.3s/0 轮/0 token → bug-found）后经词表宽匹配（ae6ea013，09-29）覆盖，但 ENOENT 新形态 10-14 首现即穿透，当前 HEAD 逐字复核仍不匹配任何 infra 判定——形态级词表追不上新错误，消费路径缺口才是根。metrics 时代 verifier 0 轮死亡 → bug-found 转化率 2/2。已落地的 evo-verify-infra-retry-lane 其 proposal Out-of-Scope 原文明确「只收口 prepare/fail-fast 短路路径、不触后置分类」，本路径是其覆盖面外残余缺口，且其台账与决议函数（resolve_infra_retry_decision，infra_classify.py:142-198）可直接复用。

## 目标

1. runner 层死亡形态在进入裁决消费前分流：verifier run 终局失败且满足进程级死亡特征（终局结果 assistant 轮数为 0，或全部 attempt 存活低于秒挂判定阈值 60 秒）时，不判 bug-found、不原地打回、不消耗实现尝试预算，改走 infra 台账限次重派（复用 _verify_infra_retry_streak/resolve_infra_retry_decision，缺省 2 次，不计 env 冻结轮、不呼叫 admin）。
2. 超限置验证暂挂：freeze_for_human → blocked+frozen+admin 信号（对齐 _escalate_env_blocked 既有形态），保留 reclassify_infra_rounds 回拨兜底，而非 bug-found。
3. 判别素材补齐：_exhausted_result 回填真实累计 assistant 轮数（现恒缺省 0）；把 evo-add-review-failure-attribution 已落地的 stderr_tail/exit_code 结构化回填从 spec-review 车道推广到 verifier 车道。

## 非目标

- 不动场景执行期 env 阻塞分类（env_gate/engine 探针车道）与 evo-verify-infra-retry-lane 的 prepare 短路车道；
- 不动 verified 方向防伪闸门（_verified_gate_refuses、verdict 证据校验、_verifier_result_is_stale）；
- 不改新流程 planner 死亡 raise → 降级 legacy 的既有重试语义；
- 不做错误词表扩列（词表天然追不上新错误形态，分流以进程级死亡特征为主判据、指纹仅辅助标注）。