## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/code_review.py
  kind: modify
- path: core/dashboard/routes/code_review_routes.py
  kind: modify
- path: tests/test_provider_failover.py
  kind: modify
- path: tests/test_code_review.py
  kind: modify
```

## 1. 429 归因双源

- [ ] 1.1 core/agent_runner/runner.py：非零退出分支（约 :5160-5180）把 run jsonl result 事件的 api_error_status 与 result 文本挂到异常（对齐 exc.api_timeout 先例）；_ratelimit_redispatch_on_terminal（约 :3196）文本分类未命中时回退读 result 事件判 429
- [ ] 1.2 core/agent_runner/maintenance_runs.py：意图登记（约 :1332-1346）接收富归因，照常登记意图并标注 run

## 2. 手动通道消费

- [ ] 2.1 fenixd.py：_check_code_review_requests 的 _worker（约 :3175-3205）消费 result.ratelimit_redispatch，复用 core/admin_monitor.py 的 300 秒冷却延迟重投递与上限 1（核对按车道计数语义），单飞让位语义保持

## 3. 分片续跑

- [ ] 3.1 core/code_review.py：新增 covered/remaining 清单计算（输入原 manifest 与已落分片行的 file 字段）
- [ ] 3.2 core/admin_monitor.py：_consume_ratelimit_redispatch（约 :1332）重派前把 manifest 剃成剩余文件，redispatch_of 链路保留；全仓快照核销以「本轮累计覆盖=完整 manifest」为解锁门，未覆盖完整维持抢救红线

## 4. 触发入口防叠加

- [ ] 4.1 core/dashboard/routes/code_review_routes.py：手动 full 触发在台账 open 条数超阈值时回确认态（对齐 trigger-ack 的 409 守卫先例），阈值入配置

## 5. 测试

- [ ] 5.1 tests/test_provider_failover.py：stderr 全噪音加 result 事件 429 时意图仍登记并进冷却的用例；重派剃余（以本 run 形状为夹具，270 文件剃至剩余）与核销门用例
- [ ] 5.2 tests/test_code_review.py：手动 worker 消费意图 300 秒调度重派（上限 1、不重复派发、单飞让位）与触发入口确认态用例；既有分类/抢救/产物硬门用例全绿