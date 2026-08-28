# Tasks: improve-run-lifecycle-governance

## 1. 锁一致性与进程表重建（D4）

- [x] 1.1 worktree_manager 新增 `refresh_locks()`：扫描进程表匹配 `.claude/worktrees/{impl,verify}-<spec>-*` 的 claude 进程，重建/校验 `_spec_locks`；在册锁无匹配进程且对应 run 流文件 mtime 超过 120s 时释放陈锁；`has_active_worktree` 判定前先调用；补单元测试（持锁有进程=true、陈锁=回收放行、daemon 重启模拟）
- [x] 1.2 agent_runner 新增 `has_live_attempt(spec)`：pgrep 进程 cmdline 含该 spec worktree 目录字面量；不可用时回退 run 文件 mtime < 120s；补单元测试（存活子进程/已死进程/回退路径三例）

## 2. 派发锁冲突退避（D5）

- [x] 2.1 config 读取 `pm.dispatch_backoff_schedule`（默认 [30,120,600]）；pm_engine 派发遇 `worktree already active` 时不再连续硬试三连发：不递增 `_retry_count`、不写 retries exhausted，spec 保持 ready 且 error 字段记录「backoff until <time>」，按序列安排下次派发尝试；补单元测试
- [x] 2.2 退避序列耗尽仍持锁时发出 dispatch_stalled Administrator 信号（severity major，含 spec 与最近一次冲突证据）；信号经 admin_alerts 去重；补单元测试

## 3. auto-recovery 一致性（D4+设计）

- [x] 3.1 pm_engine auto-recovery 分支重置状态前先调 `agent_runner.has_live_attempt(spec)`：存活则跳过本次恢复并记日志「recovery deferred, live child present」，保留 implementer_run 等跟踪字段；无存活才按现行流程重置；补单元测试（含 defer 后下轮仍卡死的路径不进入死循环——defer 也登记观察项）
- [x] 3.2 超时续期事件同步顺延 stuck 检测基准：agent_runner 续期时更新内存基准注册表，pm_engine stuck 计算改读该基准而非固定起点；无注册表条目时行为与现状一致；补单元测试

## 4. 运行超时活性监督（D1–D3）

- [x] 4.1 agent_runner 实现 run jsonl 活性快照函数：统计判定窗口内事件数、tool_use 数、最后事件距今间隔，产出窗口摘要（工具名计数 + 最后输出片段截断）；补单元测试（空窗口/高活动/循环重复特征样例）
- [x] 4.2 实现轻量 LLM 判定调用：单轮 SDK 调用复用 fallback 模型路由（同 admin 路径），prompt 输入活性摘要，输出 `{verdict: advancing|stagnant, evidence}` JSON；解析失败或调用异常一律按 stagnant 处理并记录「liveness judge unavailable」；补单元测试（桩 LLM 双分支）
- [x] 4.3 接入 deadline 循环：到达 `agents.run_timeout_seconds` 时若 `agents.timeout_supervision.enabled`（默认 true）→ 零事件直接判停滞杀；否则调 4.2，advancing 则 deadline += `extension_seconds` 并广播续期（写 run 文件与日志），stagnant 或命中 `max_extensions` / `absolute_max_seconds` 封顶则终止并留证据摘要；enabled=false 保持现行纯墙钟行为；补封顶矩阵单元测试
- [x] 4.4 config.yaml 增加 agents.timeout_supervision 段（enabled/extension_seconds/max_extensions/absolute_max_seconds/judge_window）文档注释与默认值注释

## 5. 恢复闭环复查与假就绪巡检（D6）

- [x] 5.1 pm_engine 新增观察项机制：auto-recovery 成功后登记 {spec, 指纹, 到期时间}，镜像持久化到 .fenix/recovery_watch.json（重启续查）；到期复查通过条件 = 已离开 ready 或存在活跃派发；未通过则触发 dispatch_stalled 信号；补单元测试
- [x] 5.2 巡检扩展 ready 滞留规则：ready 超过 `pm.recovery.ready_stall_threshold_minutes`（默认 20）且期间无成功派发 → 报告为阻塞项；BLOCKER CHECK 无 in-progress spec 时 MUST 继续执行非运行态扫描不得提前返回；信号指纹去重冷却（默认 30 分钟）；补单元测试
- [ ] 5.3 dashboard 日志无需改动前提下验证告警可在既有 admin activity view 可见（手动冒烟即可）

## 6. 全量回归

- [ ] 6.1 全量 pytest 通过（重点 tests/test_core.py、tests/test_agent_runner.py 及新增用例），确认无既有用例回归
- [ ] 6.2 对照三个 capability 的每个 Scenario 手动核对实现覆盖情况并记录结论
