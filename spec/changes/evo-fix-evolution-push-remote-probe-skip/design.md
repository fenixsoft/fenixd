# design

- 探测点：core/evolution.py:1106 push 执行前加一次 `git remote` 探测（复用同函数既有 git 命令构造），remote 为空则 logger.debug（含 proot）并跳过 push、提交语义不变（commit 已产生是既有行为）；core/self_review.py:2689 一带 _commit_todo 同型接入，两车道抽共用小函数避免实现漂移。
- 告警聚合：按项目根维护进程内连续失败计数与当日已告警标记（进程级去重，与 config 线协议守卫告警同款模式），首败发含仓路径与计数的聚合告警，后续失败仅递增计数、跨日重置。
- 文案修复：现 WARNING 文案 stderr 被 `[:200]` 截断且不含 proot，统一补项目根路径，使失败可逐条归仓。
- 不做：不为零 remote 仓自动创建 remote（是否配远端备份属用户决策）；不改 stderr 截断长度以外的日志设施。
