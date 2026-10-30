# design：verifier 进程级基础设施死亡分流

## 现状与改造点

- 消费路径：core/pm_engine/verification/legacy.py:760-826 进程失败分支——enrich_failure_class（infra_classify.py:91-139）词表未命中 → unknown → 按 product 处置 → :805-808 transition(bug-found)。本事件不经 verify_report._derive_status（其只服务合成报告/declared_verdict 比对），verify_report 侧无需改动。
- 判别素材缺口：_exhausted_result（core/agent_runner/runner.py:5463-5470）构造终局失败结果时未传 turns_used（恒缺省 0），签名内 turns 变量现成、回填一行级；结构化 stderr_tail/exit_code 回填机制已在 core/agent_runner/result_gate.py:191-204（spec-review 车道），verifier 车道为空。
- 可复用基建：infra 台账 _verify_infra_retry_streak + resolve_infra_retry_decision（infra_classify.py:142-198，缺省 2 次）；超限升级形态 _escalate_env_blocked（freeze_for_human → blocked+frozen+admin）；人工回拨 reclassify_infra_rounds；台账清零点=验证 PASS + unfreeze_spec 清单（legacy verified 分支 :710 已同点清零）。
- 旁证守卫：core/verify_engine/engine.py:2825-2829「双验证路径都抛异常=infra 不判 bug-found」只覆盖抛异常路径；legacy 内部消费失败不抛异常、绕开守卫——分流把 legacy 侧对齐到同一精神。

## 方案

1. 主判据用进程级死亡特征而非错误词表：终局结果 turns_used==0（回填后）或全部 attempt 存活时长 <60 秒（秒挂判定阈值，runner 逐 attempt 已记账——attempt 级 `_record_instant_fail` 侧账辅助标注；消费层存活口径取终局结果 duration_seconds，其为 run 级总存活、构成全部 attempt 存活的严格上界，无需新增 attempt 明细回填）即判进程级死亡；ENOENT/启动期即退等错误指纹仅作辅助标注（写入台账留痕），不作为命中条件——避免词表追新形态的循环补丁。
2. 分流挂点：legacy.py 进程失败分支在 enrich_failure_class 归因前先做进程级死亡判定；命中且台账未达阈值 → 复用 resolve_infra_retry_decision 走廉价重派（不计 env 冻结轮、不呼叫 admin、不 transition bug-found）；超限 → freeze_for_human 暂挂（blocked+frozen+admin 信号）。新流程 planner 死亡 raise → 降级 legacy 的既有语义不动。
3. 素材补齐：_exhausted_result 回填 turns_used；result_gate.py 的 stderr_tail/exit_code 回填扩展到 verifier 车道（同机制、只扩消费方）。
4. 防伪边界：verified 方向闸门（_verified_gate_refuses、verdict 证据校验、_verifier_result_is_stale）全部不动；分流出口只有「廉价重派」与「blocked 暂挂」两方向，结构上不产出假 verified。误判后果有界：最多 2 次零场景廉价重派 + 一次人工介入，远小于现状误判的一轮 9.8 万 token 复核 run。

## 测试策略

新文件 tests/test_verifier_infra_death_triage.py 进程内装配：ENOENT 形态（0 轮 0 token）分流→限次重派→超限暂挂→重派成功清零全链；不回归面——有轮次真实验证失败仍 bug-found、new-flow 降级语义不变、verified 防伪闸门不受影响。回归跑 legacy/infra_classify/infra-retry 既有套件。