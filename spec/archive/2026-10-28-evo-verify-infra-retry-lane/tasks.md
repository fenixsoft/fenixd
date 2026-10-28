## Deliverables

```yaml
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/pm_engine/verification/escalation.py
  kind: modify
- path: core/pm_engine/verification/infra_classify.py
  kind: modify
- path: core/verify_contract_template.yaml
  kind: modify
- path: tests/test_verify_infra_retry_lane.py
  kind: new
- path: tests/test_inconclusive_loop_escalation.py
  kind: modify
```

## 1. infra-retry 车道

- [x] 1.1 core/pm_engine/verification/pipeline.py：可达性 fail-fast 分支（pipeline.py:2127-2138，prepare 失败与可达性失败同经 _ensure_app_reachable 汇入此短路）改判 infra-retry——保持调用 _escalate_env_blocked 并传 infra-retry 车道标记（仅此一处传标记，D6），保留 `not user_blocked` 守卫语义（D5）；不计 _env_block_rounds、不触发 admin 呼叫，经 escalation 内部咨询 infra_classify 决议后触发限次重派（重派经 dispatch/queue.py:2409 verifier 派发入口，D5）。
- [x] 1.2 core/pm_engine/verification/infra_classify.py：_record_infra_failure（:142）扩 infra-retry 判定与限次——限次台账为 infra-retry 专用连续重派计数（新字段，state_machine._bump_counter 机制；**不复用 _verify_infra_rounds**，见 design D2：该账被 escalation.py:584 每个全价 env 轮递增，历史轮会吃掉重试预算），未达阈值（缺省 2）返回「重派」决议，达阈值返回「升级」决议交 escalation 走既有全价路径；新计数清零点=验证 PASS（对齐 _verify_fail_rounds 归零点）+ 纳入 unfreeze_spec 清零清单（state_machine.py:2100-2112）；infra 轮与 env 冻结轮两本账互不递增。
- [x] 1.3 core/pm_engine/verification/escalation.py：_escalate_env_blocked（:550）消费侧接受 infra-retry 决议旁路——未达阈值时不递增 _env_block_rounds、不写 blocked/status、不呼叫 admin（:666/:681 写点不经过）、不落 verify_env_blocked 信号；决策点单点化（D6）：旁路判定收敛在该函数入口，调用点不绕开该函数另起入账路径。

## 2. 宿主预检模板样板

- [x] 2.1 core/verify_contract_template.yaml：prepare 段补宿主预检示例步骤（注释形态）——无主 qemu/emulator 进程扫描清理（只清理 ppid=1 且可归属到已完成 run 的进程，记录被杀 pid）、残留 AVD 锁清理、KVM/内存水位检查、场景特异冒烟探针（如 OpenCV init）添加指引；附「预检失败走 infra-retry 廉价重试」语义说明。

## 3. 测试

- [x] 3.1 tests/test_verify_infra_retry_lane.py（新建）：prepare/可达性失败→infra-retry（env 轮不递增、无 admin 呼叫、限内重派）；连败达阈值→恢复全价升级；infra 轮与 env 冻结轮/豁免语义互不污染；infra-retry 通道不增减 _redispatch_same_cause_streak/_redispatch_cause_fp（D5）；先有历史全价 env 阻塞轮（_verify_infra_rounds>0）再遇 prepare 失败时，首次仍获完整「缺省 2 次」重试预算（专用计数不受既有观测账污染，D2）；unfreeze_spec 后专用计数从零起算（D2）。
- [x] 3.2 tests/test_inconclusive_loop_escalation.py：回归——场景执行期 env 阻塞仍走既有 blocked→升级路径，infra-retry 车道不影响既有裁决。