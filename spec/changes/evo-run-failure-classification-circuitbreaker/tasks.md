## 依赖

- **硬依赖 evo-run-failure-artifact-first**（当前 drafted，.fenix/STATE.md:5448）：
  `_artifact_landed_valid` 与 `_classify_run_failure` 须先实现；本 SPEC 复用并扩展之，
  禁止并行新开同名异义实现（若该 SPEC 未落位则在本 SPEC 内以同名新建，artifact 分支回退 content）。

## Deliverables

```yaml
- path: core/pm_engine/spec_review.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/config.py
  kind: modify
- path: tests/test_review_circuit_breaker.py
  kind: new
```

## 1. 失败分类

- [ ] 1.1 core/pm_engine/spec_review.py：扩展 evo-run-failure-artifact-first 的 _classify_run_failure(reason)（沿用同名，勿另开 _classify_failure）→ artifact|infra|content 三分（artifact 复用其 _artifact_landed_valid，依赖其先实现；infra 指纹 403/402/429/quota/budget/余额/rate limit/"provider circuit open"/"provider chain exhausted"/CLI 进程级崩溃）
- [ ] 1.2 _handle_review_failure 按分类落点：content → 既有重试；infra → 熔断计数 + 升级告警，且清 reviewer_run、不递增 _review_attempts（熔断前与冷却期均不计入，防 MAX_REVIEW_ATTEMPTS=3 freeze 与冷却后锚点残留拒派双重死锁）；artifact → 直接消费（不重试，_artifact_landed_valid 缺失时回退 content）

## 2. 熔断与冷却

- [ ] 2.1 core/pm_engine/engine.py：链路级熔断器（threshold=3、cooldown=30min、持久化 .fenix/admin_infra_breaker.json，文件损坏按复位 fail-open）；熔断窗口内评审派发入口（_on_spec_reviewing / dispatch_review）短路；v1 仅接驳 spec-review 链路（verify/impl 链路留后续 SPEC，分类函数链路无关可复用）
- [ ] 2.2 core/config.py：admin.run_infra_breaker.{threshold, cooldown_minutes}（默认 3/30）
- [ ] 2.3 冷却到期自动恢复，恢复后首次成功清零计数（熔断前成功 run 同样清零，落实「连续 ≥3 次」语义）；daemon 重启后熔断状态从持久化文件恢复（损坏/不可读 fail-open 复位）

## 3. ADMIN 信号接入

- [ ] 3.1 core/admin_monitor.py：登记 run_infra_failure（critical）至 SIGNAL_SEVERITY/SIGNAL_RECOMMENDATION；熔断触发落 kind=ESCALATION（critical，attach_trigger，不唤起 Administrator——评审链路 infra 对 admin 无杠杆）、恢复落 SIGNAL 档，evidence 含链路/指纹/次数/时间窗；若改走 SIGNAL 摄取唤起须同步补 STORED_SIGNAL_TYPES（防 verify_uniform_failure 式静默丢失）

## 4. 测试

- [ ] 4.1 tests/test_review_circuit_breaker.py：连续 3 次 infra → 熔断（不再派发、恰好 1 条 critical）；冷却后自动恢复重试
- [ ] 4.2 内容失败维持重试语义；artifact 失败不重试（联动 run-failure-artifact-first 测试）
- [ ] 4.3 熔断状态 daemon 重启后恢复（持久化读回）