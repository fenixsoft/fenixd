# 2026-11-16 evolution accept 二幕：同步阻塞 push + 30s 客户端超时 → 异步化改造

## 事故
用户点「批量同意」，5 条报错（2 条客户端 30s 超时、3 条 frp 502）。事后台账核对：**5 条实际全部接受成功**（decided_by=manual，git log 有对应 [fenix] spec: 提交）——后端成功、客户端没等到响应，「失败还是成功」不可知是本次真正的缺陷面。

## 根因链
1. `accept_item` 单条耗时 5-13s（flock CAS + copytree + git commit + STATE 注册 + todo 写）。
2. `_commit_todo_marker`（core/evolution.py）尾部的 `git push`（30s timeout）在 /root/cloud-phone 坏 remote 上逐条挂满 30s——批量同意 N 条 = N×30s 串行白烧。
3. 客户端 `request()` 封装（dashboard.ts）30s AbortController 超时；frp 隧道上游另有 502 超时。
4. 失败的条目状态是 accepted（服务端已成功），但 UI 只展示报错——状态与感知割裂。

## 修复（已落地）
- **push 后台化 + 冷却**：`_push_todo_background` daemon 线程执行 push（30s timeout），失败登记 `_push_cooldown`（300s 内同项目根跳过），成功清冷却；commit 保持同步，`_commit_todo_marker` 返回语义不变。
- **异步 accept**：POST /api/evolution/accept body `async:true` → 进程内任务表 `_ACCEPT_JOBS`（item_id → phase/started_at/finished_at/result）+ 后台线程跑 accept_item，入队即回；running 期重复入队去重（already_running）。GET /api/evolution/accept-status?item_id= 轮询终态。默认无 async 保持同步语义（测试兼容）。
- **前端逐条异步 + 轮询**：acceptWithPoll（POST async → 2s 轮询 → 终态），批量仍串行 for（CAS 安全），每条更新进度条（done/total + 当前条目名）；失败明细 Modal 加「重试失败项」按钮（retry:true 重跑）。`allow_draft_failed_retry` 参数让 draft_failed 条目可原地重入。
- 台账 draft_failed/accept_failed **终态保留**（不回 pending）：accept_failed/residue 是防 daemon auto_accept 双份在途 SPEC 的 CAS 语义；「失败可见 + 一键重试」达成用户意图而不破坏退避。

## 教训
1. **长尾子进程（git push/clone 等网络操作）不得在请求同步链路上**：远端坏了不是异常是常态（挂死 30s×N）。同仓同日聚合告警（_todo_push_fail_note）本来就把重复失败压到 DEBUG——既然重复失败被聚合，重复尝试本身也该被冷却。
2. **「失败还是成功」不可知比失败本身更糟**：超时后端可能已成功。任何 >数秒的写操作都该异步化 + 任务表 + 轮询查询，客户端永不持握长请求。
3. **批量 UI 必须有进度显示**：串行循环 N×10s+ 无反馈 = 用户以为卡死。
4. 排查入口：台账 decided_at + git log 时序对账（谁成功了谁没成功，日志说了不算，台账和提交说了算）。
