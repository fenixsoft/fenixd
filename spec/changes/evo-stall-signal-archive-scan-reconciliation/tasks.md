## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_lane_stall_accounting.py
  kind: modify
- path: spec/knowledge/domains/cost-observability/api-stall-observability.md
  kind: modify
```

## 1. 扫描面归档盲区修复与对账自证

- [x] 1.1 core/admin_monitor.py：扩展车道日预算信号面（_evaluate_lane_stall_daily_signals）与单轮停滞升级信号面（_check_api_round_stall_escalated）共用的 run 档案扫描源——从顶层 glob（_check_api_round_stall_escalated 内，约 4487-4491 行）扩展为「顶层 + archive/」双源，使终态 run 被 runs 保留清理移入归档后仍可入账；扫描量控制沿用循环既有 48h 新鲜度界（_API_STALL_SCAN_MAX_AGE_SECONDS 陈旧跳过，admin_monitor.py:1028/:4502），MUST NOT 按「当日 UTC 日桶」过滤归档源——日桶收拢语义由入账 helper 既有当日过滤（mtime≠今日确定性不计，:4344）承担，归档源日桶过滤会在跨午夜边界（日末终态、归档跨零点、窗口内无巡检轮）保留一处同型漏报，违背 R1 的无条件不漏报承诺
- [ ] 1.2 core/admin_monitor.py：对账自证——每巡检轮将终态 run_metrics 停滞行合计（含当日 archive 内终态 run）与内存累计器 _lane_stall_daily 对账，差额超 60 秒补发 lane_stall_daily_budget 信号留痕且 evidence 注明对账来源；补发走既有信号落账通道，不新增 kind；对账基准 MUST 与入账面同口径——success 终态行计入合计（:4518-4520 既有约定「success 豁免与否都要计」）、当日 mtime 过滤、latency_stall_total_seconds 缺键按 0，基准侧豁免 success 会制造系统性假差额
- [ ] 1.3 core/admin_monitor.py：三来源（顶层/归档/对账补发）共用既有 run 级去重集合，同一 run 停滞行只入账一次；入账去重集的每轮收敛裁剪（_lane_stall_accrued &= 候选茎，约 :4493-4496）MUST 以「顶层 ∪ archive」双源候选全集为收敛基——若仍只按顶层候选裁剪，「顶层入账→归档→条目被裁→归档源重新入账」会同 run 双计、日累计虚高；success 终态豁免（升级信号面）、阈值与 UTC 日桶语义不变
- [ ] 1.4 spec/knowledge/domains/cost-observability/api-stall-observability.md：补记「终态秒级归档 vs 巡检节拍」竞态盲区（历史落账最险仅早归档 4 秒、2026-11-25 窗首例漏报与 api_round_stall_escalated 面零落账实证）与扫描面双源、对账自证机制

## 2. 测试

- [ ] 2.1 tests/test_lane_stall_accounting.py：覆盖终态即归档场景——构造停滞 run 档案直接落入 archive/（顶层无文件）断言车道日累计入账且越线时信号落账；覆盖「落盘后立即归档」场景下一巡检轮仍入账
- [ ] 2.2 tests/test_lane_stall_accounting.py：覆盖对账自证——构造累计器与档案合计差额超 60 秒场景断言补发信号且 evidence 含对账来源注记；覆盖三来源去重——同一 run 档案经顶层、归档、对账补发只入账一次；覆盖 success 终态豁免与阈值语义无回归