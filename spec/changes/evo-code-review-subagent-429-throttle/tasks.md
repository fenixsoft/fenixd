## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: agents/code-review.md
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/QualityPanel.tsx
  kind: modify
- path: tests/test_code_review_429_throttle.py
  kind: new
```

## 1. 并发缺省与派发契约

- [x] 1.1 core/config.py:4969-4971：get_repo_code_review_concurrency 缺省值 4 改为 2（配置键 verify.repo_code_review_concurrency 语义不变，已显式配置的项目不受影响；一键两用的 ocr scan --concurrency 缺省并行度同步降为 2，属 spec 声明内接受面，docstring 同步补注）
- [x] 1.2 core/agent_runner/prompt_builder.py：在飞上限注入的 fail-open 回退值由 4 同步改为 2（现值见 :2449 注释与 :2466 调用链）
- [x] 1.3 agents/code-review.md：在并行扇出上限条款（:39）后新增「429 处置」条款——任一子代理死于 429（错误文本含 429 或 1302）后本 run 后续子代理一律串行派发（在飞 1）不得恢复高并发；重派前按 60s/120s/240s 指数退避等待（等待期间继续自审未派发文件，不违反「禁 async 等待收工」）；连续 3 个及以上子代理因 429 在派发后 60 秒内死亡时停止派发子代理、转为主循环自行逐文件审查，并在完成统计行末追加 `[review_429_storm=true; failed_shards=<n>]` 标记（唯一额外输出通道，产物与分片写路径契约不动）
- [x] 1.4 core/dashboard/static/src/pages/settings/components/QualityPanel.tsx:56：REPO_REVIEW_DEFAULT_CONCURRENCY 4→2（与 ConfigLoader 缺省同源，:161 空值回显与 :727 描述文案自动跟随）

## 2. 风暴标记解析与告警消费

- [x] 2.1 core/agent_runner/maintenance_runs.py：run_code_review 收尾解析完成统计行的 review_429_storm 标记（result 事件文本收尾已在手，同 maintenance_runs.py:3677 归因骨架），回填 CodeReviewResult 新字段 review_429_storm（bool，缺省 False）与 failed_shards（int，缺省 0）；run 主体漏报时保持缺省，不产生假阳性
- [x] 2.2 core/admin_monitor.py：审查 run 终态 result 携带 review_429_storm=true 时产生一条 admin 告警（沿用 admin_monitor.py:2843 getattr 意图消费既有模式，同 run 去重），evidence 含 failed_shards 死亡分片数与时间线，建议文案包含「检查同账户并发：注意多项目全仓审查窗口重叠，建议错峰排程」；与既有 run 级 ratelimit_redispatch 意图按 run 终态天然互斥（not run_ok 时风暴标记无从产生），无重复告警面

## 3. 测试

- [x] 3.1 tests/test_code_review_429_throttle.py：覆盖未显式配置时在飞上限取 2、fail-open 回退取 2、审查 prompt 渲染含 429 处置条款、完成统计行标记解析回填 CodeReviewResult（含漏报保持缺省）、终态 review_429_storm=true 触发恰好一条告警且重复终态不重复告警、QualityPanel REPO_REVIEW_DEFAULT_CONCURRENCY=2
