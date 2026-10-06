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

- [ ] 1.1 core/pm_engine/verification/pipeline.py：可达性 fail-fast 分支（:2119-2130）与 prepare 失败路径改判 infra-retry——不计 _env_block_rounds、不触发 _escalate_env_blocked，改为经 infra_classify 入账并触发限次重派验证。
- [ ] 1.2 core/pm_engine/verification/infra_classify.py：_record_infra_failure（:142）扩 infra-retry 判定与限次——复用 _verify_infra_rounds 台账，未达阈值（缺省 2）返回「重派」决议，达阈值返回「升级」决议交 escalation 走既有全价路径；infra 轮与 env 冻结轮两本账互不递增。
- [ ] 1.3 core/pm_engine/verification/escalation.py：_escalate_env_blocked（:550）消费侧接受 infra-retry 决议旁路——未达阈值时不呼叫 admin（:666/:681 写点不触发）、不落 verify_env_blocked 信号。

## 2. 宿主预检模板样板

- [ ] 2.1 core/verify_contract_template.yaml：prepare 段补宿主预检示例步骤（注释形态）——无主 qemu/emulator 进程扫描清理（只清理 ppid=1 且可归属到已完成 run 的进程，记录被杀 pid）、残留 AVD 锁清理、KVM/内存水位检查、场景特异冒烟探针（如 OpenCV init）添加指引；附「预检失败走 infra-retry 廉价重试」语义说明。

## 3. 测试

- [ ] 3.1 tests/test_verify_infra_retry_lane.py（新建）：prepare/可达性失败→infra-retry（env 轮不递增、无 admin 呼叫、限内重派）；连败达阈值→恢复全价升级；infra 轮与 env 冻结轮/豁免语义互不污染。
- [ ] 3.2 tests/test_inconclusive_loop_escalation.py：回归——场景执行期 env 阻塞仍走既有 blocked→升级路径，infra-retry 车道不影响既有裁决。