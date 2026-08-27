# Tasks: fix-dispatch-orphan

## 1. 状态机读取防御（design D3，先复现再修）

- [ ] 1.1 编写最小复现用例：构造含字符串形条目/半写内容的 STATE.md 调用 `state_machine.read_all()`，证实 `string indices must be integers` 崩溃点位（或证实根因另有其处并记录实际点位）；用例入库 tests/test_core.py
- [ ] 1.2 在 read_all() 解析层规范化条目：非法条目跳过并记 warning；1.1 用例转绿后确保既有解析用例无回归

## 2. bug_found 重发无害化（design D2）

- [ ] 2.1 pm_engine spec_bug_found 处理器扩展幂等守卫：fix 子 SPEC 处于 implementing/testing/implemented/verified/done/pushed 时仅记日志不动状态；全路径禁止向 implementer_run/tester_run 写空值；补单元测试三例（implemented 存活两轮扫描 / ready 无历史正常 reset 且不清字段 / done 完全跳过）
- [ ] 2.2 全局 grep implementer_run/tester_run 消费点确认「保留历史 run id」语义兼容（dashboard 与排队去重），结论写入 PR 描述

## 3. 同状态行动性重置补发（design D1）

- [ ] 3.1 定位 spec_bug_found 处理器内所有同状态重置写回点（含"already exists (status=ready) — resetting to ready"路径），写回后直调 `_on_spec_ready(spec)`；复用 pm_engine.py L105 启动路径先例；补测试：同状态重置周期内派发被触发、与真实事件序列不双重排队
- [ ] 3.2 排查其他产生行动性同状态更新的处理器（error 更新后可重新派发的 ready 场景），逐点接入补发并列清单到 PR 描述；确认无遗漏点后进入下一任务

## 4. full_scan 单条隔离与统计（spec-full-scan-resilience）

- [ ] 4.1 event_bus.full_scan 中 recovery 循环逐条 try/except（单条失败记 error 含 spec 名），check_blockers 同样包裹；扫描末尾输出 handled/failed 统计日志；补测试：注入单条毒条目时其余 SPEC 的 recovery 全部完成且统计可见

## 5. 孤儿 ready 白名单恢复（design D4）

- [ ] 5.1 实现 ready 存活判定：优先调用 improve-run-lifecycle-governance 已落地的 has_live_attempt/refresh_locks 接口（若未合入则用兜底实现——pgrep 匹配 `.claude/worktrees/{impl,verify}-<spec>-*` claude 进程 + 对应最新 run 文件 mtime < 120s），接口选型写在 PR 描述
- [ ] 5.2 改写 full_scan recovery 的 ready 分支为白名单判定（存活才 skip 并记「skip: live child present」），重派发前清 error、保留 implementer_run；补测试四例：带 error 孤儿重派发 / 带 implementer_run 无活跃运行重派发 / 有存活进程跳过 / 锁表在册跳过

## 6. 回归与核验

- [ ] 6.1 全量 pytest 通过（重点 tests/test_core.py 及新增用例），无既有用例回归
- [ ] 6.2 对照两个 capability spec 的全部 Scenario 逐条核对实现覆盖并记录结论
