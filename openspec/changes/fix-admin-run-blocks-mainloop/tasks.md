# tasks

## 1. 后台队列基础设施

- [ ] 1.1 `fenixd.py` 新增 AdminInvocationWorker：`queue.Queue` + 单 worker 线程（daemon=True），循环 `get(timeout)` → 执行处置；循环体 catch-all 保证线程存活，异常记日志
- [ ] 1.2 worker 存活监控：主循环周期检测 worker 线程 `is_alive()`，死亡时通过 admin_store 写告警并重建 worker（避免队列静默吞请求）
- [ ] 1.3 worker 退出（daemon shutdown）时的在途请求处理：进程退出不等待处置完成即可（处置产物已由 pending disposition 标记，admin_monitor 会升级人工）

## 2. 主循环改造

- [ ] 2.1 `_check_admin_invoke_requests` 改为投递：读文件 → 先读后删 → 校验 spec/构造 signal（含 prompt 透传）→ `admin_queue.put(signal)`，移除对 `invoke_manual`/`run_administrator` 的同步调用
- [ ] 2.2 保留既有容错语义：损坏请求文件删除并记日志、spec 缺失忽略、投递成功日志
- [ ] 2.3 验证拾取及时性：invoke 写文件后，下一轮扫描（≤1s）完成投递

## 3. 落痕语义保持

- [ ] 3.1 worker 中调用 `admin_monitor.invoke_manual(signal)`（或无 monitor 时 `agent_runner.run_administrator`），保持 pending → final disposition 与 escalate 告警链路不变
- [ ] 3.2 异常路径保持：处置异常落 failed disposition（不丢痕），worker 捕获后继续处理队列
- [ ] 3.3 AdminStore 跨线程使用验证：文件锁与线程亲和无关，append/read 在 worker 线程正常工作

## 4. 并发安全审视

- [ ] 4.1 审视 `run_administrator` 与主循环共享状态（agent_runner 内部计数、session 管理），跨线程访问补锁或消除共享
- [ ] 4.2 观察项：admin run 期间主循环 SPEC 派发与处置在主树上的实际写冲突——若出现冲突，引入"处置运行期间暂停派发"轻量旗标（记录在实现报告，不阻塞本 change）

## 5. 验证

- [ ] 5.1 单元/脚本验证：写入请求文件后 1 个扫描周期内被投递（拾取及时性）
- [ ] 5.2 集成验证：处置运行期间（数分钟）主循环日志持续输出（派发/巡检未停摆）
- [ ] 5.3 集成验证：连续两次 invoke，第二个请求在第一个处置结束后自动开始（串行先到先得）
- [ ] 5.4 集成验证：处置异常场景落 failed disposition，worker 存活并继续处理后续请求
- [ ] 5.5 Dashboard 回归：呼叫 Admin 介入弹窗发起后，拾取不再出现分钟级延迟
