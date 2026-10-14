## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/pm_engine/verification/infra_classify.py
  kind: modify
- path: core/pm_engine/verification/legacy.py
  kind: modify
- path: tests/test_verifier_infra_death_triage.py
  kind: new
```

## 1. 判别素材补齐

- [x] 1.1 core/agent_runner/runner.py：_exhausted_result（约 :5463-5470）回填真实累计 assistant 轮数（签名内 turns 变量现成），终局失败结果对象的 turns_used 与 context metrics 口径一致。
- [x] 1.2 core/agent_runner/result_gate.py：把 stderr_tail/exit_code 结构化回填（现 :191-204 仅 spec-review 车道消费）扩展到 verifier 车道结果对象。

## 2. 进程级死亡分流

- [x] 2.1 core/pm_engine/verification/infra_classify.py：新增进程级死亡判定——终局 turns_used==0 或全部 attempt 存活低于秒挂阈值（60s；存活口径取终局结果 duration_seconds——run 级总存活、全部 attempt 存活的严格上界，无需新增 attempt 明细回填）即命中；错误指纹（ENOENT/启动期即退）仅作台账辅助标注、不作命中条件；判定置于 enrich_failure_class 归因链上游。
- [x] 2.2 core/pm_engine/verification/legacy.py：进程失败分支（约 :760-826）消费分流决议——命中且台账未达阈值走既有 resolve_infra_retry_decision 廉价重派（不计 env 冻结轮、不呼叫 admin），超限走 freeze_for_human 暂挂（blocked+frozen+admin 信号，保留 reclassify_infra_rounds 回拨），两路均不 transition bug-found；infra 记账经 `_record_infra_failure(retry_gate=True)` 单点入账，escalate 决议后 MUST NOT 二次调用（防观测账/退款双计，infra_classify._record_infra_failure docstring 契约）；台账清零点与验证 PASS + unfreeze_spec 清单同点、不新增平行台账。
- [x] 2.3 core/pm_engine/verification/legacy.py：确认新流程 planner 死亡 raise → 降级 legacy 的既有语义与 core/verify_engine/engine.py:2825-2829 双路径失败守卫行为不回归。

## 3. 测试

- [x] 3.1 tests/test_verifier_infra_death_triage.py：覆盖 ENOENT/启动期秒死形态——0 轮 0 token 死亡不判 bug-found、限次内廉价重派且不计 env 冻结轮、超限转 blocked+frozen+admin、重派成功后台账清零、turns_used 回填后口径一致。
- [x] 3.2 tests/test_verifier_infra_death_triage.py：覆盖不回归——有 assistant 轮次且存活达秒挂阈值的真实验证失败仍走既有 bug-found/降级路径、verified 方向防伪闸门不受影响、env 阻塞后置分类语义不变。
- [x] 3.3 回归：verification 链既有套件（legacy、infra_classify、infra-retry 相关）全绿。