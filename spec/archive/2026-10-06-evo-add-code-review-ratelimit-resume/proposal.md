# add-code-review-ratelimit-resume

## Why

09-28 手动全仓审查 code-review-1790574672 跑 218 轮、13.89 美元后死于账户级 429：自述 16 个分片仅落账 b1-b4（4 片 19 条，25%），全仓快照核销未做。事故暴露的不是「无重派机制」——add-code-review-concurrency-and-429-resilience 已建 429 分类（classify_ratelimit_error）、300 秒 provider 冷却与自动重派骨架——而是骨架被双重旁路完全未生效：

1. 429 归因丢失：意图登记以异常文本为分类输入，异常文本经 _denoise_stderr 降噪后只剩 Exit code: 1（429 文案在 result 事件的 api_error_status/result 字段），classify_ratelimit_error 恒 False——意图不登记、provider 不冷却、run 无标注（归档 jsonl 无 ratelimit_redispatch 行）。
2. 手动通道消费缺口：意图消费只挂周期调度 worker；手动触发 worker（fenixd.py _check_code_review_requests）只记日志从不读 ratelimit_redispatch。429 spec design「run_code_review 唯一生产调用方是 admin_monitor._worker」的前提自 09-19 手动路径落地起失真。
3. 重派整轮重来：现有消费逻辑复用原 manifest 全量重跑（270 文件，重烧约 14 美元），而分片行 file 字段与 manifest 清单足以算出剩余文件，剃余续跑只缺实现。

## What Changes

1. 归因双源：runner 非零退出分支把 result 事件的 api_error_status 与 result 文本挂到异常（对齐 exc.api_timeout 先例），文本分类未命中时回退读 result 事件判 429。
2. 消费统一：手动审查 worker 消费 ratelimit_redispatch 意图，复用 admin_monitor 的 300 秒冷却延迟重投递、上限 1 与单飞让位语义。
3. 分片续跑：重派前把 manifest 剃成「原清单 − 已落账分片覆盖」，redispatch_of 链路保留；全仓快照核销以「本轮累计覆盖=完整 manifest」为解锁门，未覆盖完整维持抢救红线。
4. 触发入口防叠加：手动 full 触发在台账 open 条数超阈值时回确认态（对齐 trigger-ack 409 守卫先例）。

## Non-Goals

- 不放宽重派上限与冷却时长（重派再 429 走既有失败收场与升级）。
- 不改周期调度路径既有行为。
- 不动 spec run 的 in-place retry（与审查车道无关，其不经 attempt 循环）。

## Impact

- Specs: specs/repo-review-ratelimit-resume/spec.md（ADDED：429 归因双源、手动通道消费、分片续跑与核销门、二次全仓确认）
- Code: core/agent_runner/runner.py、core/agent_runner/maintenance_runs.py、fenixd.py、core/admin_monitor.py、core/code_review.py、core/dashboard/routes/code_review_routes.py
- Tests: tests/test_provider_failover.py、tests/test_code_review.py
- 行为：429 终局在手动与周期两通道都登记意图并于 300 秒后自动重派，重派只跑剩余文件；上一轮未消化完时手动二次全仓需确认。