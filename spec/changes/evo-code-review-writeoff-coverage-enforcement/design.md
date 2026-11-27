## 设计

### 改动点

1. core/agent_runner/maintenance_runs.py（_writeoff_coverage_guard 及收尾资格门段 :3304-3465）：
   - 守卫现有行为：计算覆盖并落 WARNING「核销锁定」。本次在其后加执行层：缺口比例 > 阈值（新常量，缺省 0.02）时——
     a. 终态降格：把该 run 的终态记法从 success 改为 partial（复用既有 partial 终态通道，如存在；无则按 run 结果分类的 partial 形态落）；
     b. 告警：经 core/admin_store.py 既有告警写回通道落一条告警（kind 参照车道信号既有形态），正文含未覆盖文件数、比例与差集摘要；
     c. 落锚：调用 core/code_review.py 的 write_pending_writeoff（:2164 附近既有实现），锚内记本 run id 与未覆盖清单，使锚续审扫描（core/admin_monitor.py:2933 _run_writeoff_anchor_resume_checkpoint）自动武装 redispatch。
   - 缺口 ≤ 阈值时全部跳过，保持现行为。
   - 幂等：同一 run 只降格/落锚一次（以 pending-writeoff 在册为判）。
2. core/code_review.py（manifest 与批次管理）：
   - 批次派发留痕：派发侧已有批号推进逻辑处，每批派出时落一行事件（批号+计划文件数），写入 manifest 附属事件流或档案事件流（选与既有 manifest-code-review-<runid>.json 读写路径最小耦合的一侧）。

### 不改动

- 锚续审扫描消费侧（core/admin_monitor.py）零改动——「锚在册与否是唯一触发条件」的既有语义直接复用。
- redispatch 链字段（redispatch_of）、writeoff 抢救红线、限流终局续跑等既有机制不动。

### 测试设计

tests/test_code_review_coverage_gate.py（新建）：构造 manifest scope 与分片/主产物夹具，覆盖三形态（超阈值→partial+告警+锚；低阈值→success 不落锚；派发事件行对账计划偏短）；回归既有锚语义测试。