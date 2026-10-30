# design

- 探测点：core/evolution.py:1106 push 执行前加一次 `git remote` 探测（复用同函数既有 git 命令构造），remote 为空则 logger.debug（含 proot）并跳过 push、提交语义不变（commit 已产生是既有行为）；core/self_review.py:2689 一带 _commit_todo 同型接入，两车道抽共用小函数避免实现漂移。
- 告警聚合（仅 evolution todo 回写车道；self_review 每项目每日至多一次 push，无刷屏面，不聚合）：按项目根维护进程内连续失败计数（自最近一次成功 push 起累计，成功清零；仅进程内存活，重启归零——与 config 线协议守卫告警同款限制）与当日已告警标记。当日首败发一条聚合 WARNING（含仓路径、连续失败计数、stderr 尾部）；当日后续失败不再记常规 WARNING，仅递增计数并降级记 DEBUG（含 stderr 尾部，诊断细节不丢失）。当日已告警标记跨日重置（连续失败计数不清零），次日首败再发含最新计数的一条聚合。即同仓同日 WARNING 收敛为至多一条。
- 第三链路覆盖：knowledge_backfill 的 append_todo_line / upsert_todo_line 就地提交经延迟导入复用 `core.evolution._commit_todo_marker`（core/knowledge_backfill.py:319-333），remote 探测在共享函数内单点收口，append/upsert 写入链路自动获得跳过语义；本 SPEC 不改 knowledge_backfill.py，测试经共享函数断言覆盖。
- 文案修复：现 WARNING 文案 stderr 被 `[:200]` 截断且不含 proot，统一补项目根路径，使失败可逐条归仓。
- 不做：不为零 remote 仓自动创建 remote（是否配远端备份属用户决策）；不改 stderr 截断长度以外的日志设施。
