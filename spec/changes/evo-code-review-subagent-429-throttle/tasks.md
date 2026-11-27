## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: agents/code-review.md
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_code_review_429_throttle.py
  kind: new
```

## 1. 并发缺省与派发契约

- [ ] 1.1 core/config.py：get_repo_code_review_concurrency 缺省值 4 改为 2（配置键 verify.repo_code_review_concurrency 语义不变，已显式配置的项目不受影响）
- [ ] 1.2 core/agent_runner/prompt_builder.py：在飞上限注入的 fail-open 回退值由 4 同步改为 2
- [ ] 1.3 agents/code-review.md：在并行扇出上限条款后新增「429 处置」条款——任一子代理死于 429（错误文本含 429 或 1302）后本 run 后续子代理一律串行派发（在飞 1）不得恢复高并发；重派前按 60s/120s/240s 指数退避等待；连续 3 个及以上子代理因 429 在派发后 60 秒内死亡时停止派发子代理、转为主循环自行逐文件审查，并在终态 result 携带 review_429_storm=true

## 2. 风暴告警消费

- [ ] 2.1 core/admin_monitor.py：审查 run 终态 result 携带 review_429_storm=true 时产生一条 admin 告警（沿用终态意图消费既有模式，同 run 去重），evidence 含死亡分片数与时间线，建议文案包含「检查同账户并发：注意多项目全仓审查窗口重叠，建议错峰排程」

## 3. 测试

- [ ] 3.1 tests/test_code_review_429_throttle.py：覆盖未显式配置时在飞上限取 2、fail-open 回退取 2、审查 prompt 渲染含 429 处置条款、终态 review_429_storm=true 触发恰好一条告警且重复终态不重复告警