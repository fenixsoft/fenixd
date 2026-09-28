# design — add-code-review-ratelimit-resume

## 事故链基线（验收对照）

code-review-1790574672：218 轮 / 13.89 美元 / 自述 16 批仅落 b1-b4（4 片 19 条）；归档 jsonl 无 ratelimit_redispatch 标注（意图未登记的直接证据）；.fenix/logs/fenixd.log:31554-31555 抢救与收场（红线：不做全仓快照核销）。

## 归因双源

- 现状：意图登记（core/agent_runner/maintenance_runs.py:1332-1346）以 claude_error 异常文本（:1150/:1176）为分类输入；429 文案在 result 事件，stderr 经 _denoise_stderr 降噪后只剩 Exit code: 1（core/agent_runner/runner.py:5160-5167），classify_ratelimit_error（core/agent_runner/provider_circuit.py:406）恒 False。
- 改法：runner 非零退出分支把 result 事件的 api_error_status 与 result 文本挂到异常（先例 exc.api_timeout，runner.py:401 与 :5167-5180）；_ratelimit_redispatch_on_terminal（:3196）文本分类未命中时回退读 result 事件判 429。归因优先级：文本分类 → result 事件回退，与降噪既有语义兼容（降噪只作用于日志与 error 字段，不动 result 事件）。

## 消费统一

- 现状：周期链 admin_monitor._worker（:1229-1243）→ _schedule_ratelimit_redispatch（:1266，PROVIDER_RATELIMIT_COOLDOWN_SECONDS=300、RATELIMIT_REDISPATCH_MAX=1）→ _consume_ratelimit_redispatch（:1332）；手动链 fenixd.py:3004 的 _worker（:3175-3205）只记日志。
- 改法：手动 worker 复用 admin_monitor 的延迟重投递（抽共享入口或直接调用其方法），按车道核对上限计数语义（admin_monitor.py:860-864），单飞让位语义保持，周期路径行为不变。

## 分片续跑

- 数据基础：分片行携带 file 字段、manifest 落盘完整文件清单（core/code_review.py manifest_path/shard_paths 已有）。
- 改法：core/code_review.py 新增 covered/remaining 计算；_consume_ratelimit_redispatch 重派前剃余（本 run 形状 270→约 202）；redispatch_of 保留串联链路。
- 核销门：剃余重派后仅当「本轮累计覆盖 = 完整 manifest」才解锁全仓快照核销，否则维持抢救红线（防止部分覆盖白洗核销）。

## 触发入口防叠加

- 现状：周期入口仅同日防重（admin_monitor.py:1124-1127），手动入口无台账检查；open 数可从 items.jsonl 读。
- 改法：core/dashboard/routes/code_review_routes.py 手动 full 触发在 open 超阈值时回确认态（add-code-review-trigger-ack 的 409 三态回链先例），阈值入配置。

## Risks

- 归因回退读 jsonl 的 IO：仅终局时一次读取，可忽略。
- 双消费路径漂移：抽共享入口，周期路径行为逐字不变（既有 17 处 ratelimit_redispatch 用例回归保障）。
- 重派再遇 429：走既有失败收场与升级，不放宽上限。