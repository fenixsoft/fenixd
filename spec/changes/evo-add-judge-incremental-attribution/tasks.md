## Deliverables

```yaml
- path: core/pm_engine/verification.py
  kind: modify
- path: core/verify_engine/judge_files.py
  kind: new
- path: tests/test_judge_incremental_attribution.py
  kind: new
```

## 1. 增量写盘结构

- [x] 1.1 新增 core/verify_engine/judge_files.py：judge 归因产物按 `scenarios:[{id, attribution, status}]` 逐场景条目读写（读兼容旧整块结构回退解析）
- [x] 1.2 planner-judge 落盘路径切换为逐场景写盘（每场景独立条目，附场景 id/时间戳）

## 2. 场景级查重拒绝

- [x] 2.1 批量归因查重判定粒度从整批降为场景：命中重复的归因置 requeue 状态，非重复置 accept 保留
- [x] 2.2 回炉驱动：requeue 子集汇总回炉清单，下轮 judge 仅重做该子集；完成后整轮再校验一次
- [x] 2.3 回炉子集=全量（100% 重复）时复用既有整批拒绝 escalation 告警（防御语义不弱化）

## 3. 测试

- [x] 3.1 tests/test_judge_incremental_attribution.py：部分重复仅回炉子集并保留已通过场景；全量重复仍整批回炉+告警；旧整块结构向后兼容读
