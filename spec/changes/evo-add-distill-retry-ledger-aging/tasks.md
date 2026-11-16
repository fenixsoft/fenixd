## Deliverables

```yaml
- path: core/knowledge.py
  kind: modify
- path: tests/test_distill_retry_ledger_aging.py
  kind: new
```

## 1. 龄期展示与超期升级

- [ ] 1.1 core/knowledge.py：check_retry_ledger_age 发射时在 description/evidence 补当前龄期（按行归位日期节零点起算，与 _retry_display_names 登记日期同源，展示为小时/天；归档名与登记日期沿用既有展示形态），并把 recommended_action 的排查指引改为 proposal 附节口径（移除指向已排除 unrecognized_model 假说的指引）
- [ ] 1.2 core/knowledge.py：欠账龄期超过 72 小时未处置时在同一 kind=SIGNAL 通道内 severity 升为 major（不使用 kind=ESCALATION），24~72 小时维持 warning

## 2. 升级穿透现行持久节流

- [ ] 2.1 core/knowledge.py：应发级别纳入现行持久节流状态（.fenix/knowledge-distill-retry-state.json 新增 last_severity 键，沿用 flock 持锁原子写与「未知键保留」前向兼容语义）；「同日且指纹未变」跳过判据扩为「同日且指纹未变且应发级别未升」，级别提升的首次发射穿透立即发出，发射成功后回写新级别，拒写不回写（下一周期重试穿透）
- [ ] 2.2 core/knowledge.py：穿透仅在级别提升边沿触发一次——同级后续发射回到现行日粒度节流，不回弹、不引入第二条节流机制、不放宽现行「至多每日一条」节奏

## 3. 测试

- [ ] 3.1 tests/test_distill_retry_ledger_aging.py：覆盖龄期字段正确性（与日期节零点同源）、72 小时升级边界（<72h warning、≥72h major）、现行节流跨 daemon 重启语义不回归、升级首射穿透节流、穿透后同级再发射仍被节流
