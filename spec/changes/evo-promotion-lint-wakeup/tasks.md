## Deliverables

```yaml
- path: core/deliverables.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: tests/test_deliverable_lint.py
  kind: modify
- path: tests/test_promotion_tasks_wakeup.py
  kind: new
```

## 1. lint 一次全报

- [x] 1.1 core/deliverables.py：lint_tasks_text 分组不可解析分支（约 :3329）的违规消息并列披露 item_count（可测 checkbox 任务行总数）与「分组修正后任务行还需补组号.序号编号」提示，保持 ownership 检查独立函数不被可解析性短路吞并
- [x] 1.2 tests/test_deliverable_lint.py：补「分组缺失+多条未编号 checkbox 行」单轮双信息用例，断言消息同时含分组形态要求与任务行计数

## 2. tasks.md 变化即时唤醒

- [x] 2.1 core/event_bus.py：_watch_loop/_file_checksum 扩展 tasks.md checksum 监视面，仅对 status=drafted 且 STATE error 含「tasks.md 可解析性 lint 未通过」段的 spec 生效（子串匹配——error 为三类 lint 固定顺序 join 的拼接串，tasks 段未必居首；短语唯一生成点 promotion.py:165；名单预过滤避免全量目录常驻扫描）；名单内任一 tasks.md 读/checksum 异常单条隔离记 WARNING，不汇入 _watch_loop 既有 fail_backoff 通道
- [x] 2.2 core/event_bus.py：tasks.md 变化触发复用 pm_engine.handle_event("spec_drafted", ...) 恢复出口（同 _recover_one 约 :412-413，自动继承 start_after 门与 promote_mode 短路）；lint 仍败重写同值 error 时按 error 值+checksum 联合去重，抑制重复触发与重复日志
- [x] 2.3 tests/test_promotion_tasks_wakeup.py：lint 修复落盘后秒级重评晋升、lint 仍败同值抑制、promote_mode=manual 不被唤醒、非 lint error 的 drafted spec 不受影响四类用例（event_bus 装配参照 tests/test_startup_full_scan_async.py 的 pm_engine 替身）

## 3. 清错留痕

- [x] 3.1 core/dashboard/data/admin_actions.py：clear_spec_error（约 :1529）清空成功时显式写一行留痕日志（含 spec 名与清空来源=dashboard），不改 STATE 写语义
- [x] 3.2 tests/test_promotion_tasks_wakeup.py：清错留痕断言（留痕行含 spec 名与清空来源）
