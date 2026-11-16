## Deliverables

```yaml
- path: core/pm_engine/escalation_chain.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_escalation_chain.py
  kind: modify
- path: tests/test_admin_disposition_reschedule.py
  kind: modify
```

## 1. 链痕单源与 deferred 留痕（escalation_chain.py）

- [x] 1.1 新增链痕查询函数（输入签名，输出 in_flight/deferred/arbiter_active 三态只读聚合；arbiter 单飞队列经既有注册只读访问，不新建注册表；链状态文件缺失/损坏按零命中 fail-open 降级）
- [x] 1.2 deferred 留痕：让行路径从整条清除改为改写 `phase: "deferred"`（含新增 yield_to 与 deferred_at；现行条目已持久化 phase="admin"/"arbiter"，clear 点在 _process_item 主流程、须按返回 phase 条件化）；读侧对缺 yield_to/deferred_at 的既有条目按 admin/arbiter 相待、缺 phase 条目按 "admin" 兼容（防御，新旧形态混合共存）
- [x] 1.3 frozen 预检：_run_admin_phase 派发前查 spec 冻结态，frozen=True 不派发不计配额，转 deferred 留痕（yield_to 空，重派条件=spec 解冻）
- [x] 1.4 frozen-terminated 不计配额：Admin 失败计点处判「0 API 轮次 + 终态 frozen-terminated」双条件，命中视为未尝试不计失败（跑过轮次后被冻结击杀仍计失败）

## 2. 看护链痕抑制与重派（admin_monitor.py）

- [x] 2.1 孤儿升级前查链痕抑制：同签名 in_flight/deferred/arbiter 在飞任一命中则不产生升级告警且不终结 pending disposition；链痕全部消失且仍超时照常升级（「升级即终结」与「interrupted 终结不告警」既有口径不变）
- [x] 2.2 告警归因取 run 终态实证：复用 run 末事件终态读法生成归因文案（frozen-terminated/killed/死因不明保守兜底）并附终态摘录入 evidence，废弃「疑似 daemon 重启/崩溃」固定模板
- [x] 2.3 deferred 扫描重派：挂既有巡检循环与 _reap_chain_inflight 同拍——被让行 run 已终态且信号未收口则调链派发器入口重派（单飞/互斥守卫生效）；spec 已解冻且已收口则仅清条目；deferred 条目纳入既有超时 reap 一视同仁

## 3. 测试

- [x] 3.1 链侧用例（tests/test_escalation_chain.py）：frozen 预检不烧配额 / 冻结击杀空壳不计尝试 / 让行留痕形态（phase/yield_to/deferred_at）/ deferred 超时 reap / 新旧条目形态混合兼容
- [x] 3.2 看护侧用例（tests/test_admin_disposition_reschedule.py）：链在飞抑制不告警不终结 / 链痕消失兜底升级 / 归因四态（frozen-terminated、killed、死因不明、interrupted 口径不变）/ deferred 重派触发与单飞守卫限流
- [x] 3.3 端到端时序用例：复刻首例事件时间轴（冻结竞态→让行留痕→被让行 run 死→看护重派→链终点唯一人工作品，全程人工队列零重复条目）

## 4. 收尾

- [x] 4.1 全量回归通过 + compileall 自证
- [x] 4.2 落位 restart_request 信号文件（根路径，JSON：reason/origin/date）并冒烟预演（全新进程 + 消费方 import + 链/看护核心 API）；实际重启由 supervisor 消费该信号完成
