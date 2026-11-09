# Tasks — arbiter 车道故障分级复位与前置自检

## 1. 调查归因

- [ ] 1.1 复核 `_on_run_failed`（core/pm_engine/arbiter.py:1290-1362）连败→dead-man 链、台账读侧（:383-388、:626-671、:671、:715）与 append-only 纪律（:180-184）；定位 0 rounds 判定的可复用口径（core/agent_runner/latency.py:235-247）与 MISSING_CREDENTIAL 识别面（core/agent_runner/harness/dsh_adapter.py）；产出 findings.md（含今日四签名事故现场引用），确认 infra/judgment 分级不破坏任何既有消费者。

## 2. 分级与复位（arbiter-infra-failure-reset）

- [ ] 2.1 失败分级与 infra 通道：`classify_lane_failure` + `_infra_failure_counts` 独立计数（上限 `arbiter.max_consecutive_infra_failures` get-or-default），infra 失败写台账 kind=infra-failed、不进 `_deadmanned`、不升级人工；预算耗尽恒判 judgment（R1/R2、场景 S1-S3）。
- [ ] 2.2 复位消费：健康信号→清 infra 计数 + 日志留痕；judgment 计数与 dead-man 不动（R3、场景 S4）；台账读侧兼容回归（R4、场景 S5）。

## 3. 前置自检（agent-lane-preflight）

- [ ] 3.1 探针模块 core/agent_runner/lane_preflight.py：`probe_lane_health`（CLI 可达 + 凭据路由本地解析）+ `LaneHealth`，fail-open（R1/R4、场景 S3）。
- [ ] 3.2 接线：fenixd.py 启动自检 + 告警单发/恢复自动关闭；arbiter 派发前置缓存拦截（TTL `arbiter.preflight_ttl` 缺省 300s）；周期重探挂靠既有节拍、禁内存定时器（R2/R3、场景 S1/S2/S4）。

## 4. 回归验证

- [ ] 4.1 回归测试 tests/test_arbiter_lane_resilience.py：覆盖两能力全部场景（S1-S5 + preflight S1-S4），含台账读侧兼容回归。
- [ ] 4.2 fenixd 全量测试面回归绿。

## 5. 知识回填

- [ ] 5.1 run-resilience 域登记「arbiter 车道故障分级与 infra 复位」能力页，更新 spec/knowledge/index.md 计数与时间戳。
