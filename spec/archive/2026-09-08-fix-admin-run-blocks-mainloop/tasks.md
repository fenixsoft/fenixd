# tasks

## 1. 处置状态文件按实例分离

- [x] 1.1 `core/agent_runner/runner.py`：`_clear_admin_disposition` / `_read_admin_disposition` 按 run_id 参数化（实例路径形如 .fenix/admin_disposition-<run_id>.json，不再用固定文件名），`run_administrator` 内部改用实例路径
- [x] 1.2 `core/agent_runner/prompt_builder.py`：administrator 提示词中的 disposition 写入路径按 run_id 注入（替换固定 .fenix/admin_disposition.json 字样，两处：中途持久化与最终写入）
- [x] 1.3 run 结束读取自身 disposition 落 final 记录后删除实例文件；拾取新请求时顺带清理超过 24h 的残留实例文件

## 2. worker 池基础设施

- [x] 2.1 `fenixd.py` 新增后台 worker 池：`ThreadPoolExecutor(max_workers=admin.workers, 默认 2)`（可配置，0 回退同步行为）；worker 函数 catch-all 保证线程存活
- [x] 2.2 worker 存活与队列监控：提交计数/完成计数可观测（日志），executor 拒绝或异常时告警
- [x] 2.3 daemon shutdown 时 executor 优雅关闭（不等待在途处置，处置由 pending disposition 标记可追溯）

## 3. 主循环改造

- [x] 3.1 `_check_admin_invoke_requests` 改为投递：读文件 → 先读后删 → 校验 spec/构造 signal（含 prompt 透传）→ `executor.submit(worker_run, signal)`，移除对 `invoke_manual`/`run_administrator` 的同步调用
- [x] 3.2 保留既有容错语义：损坏请求文件删除并记日志、spec 缺失忽略、投递成功日志
- [x] 3.3 验证拾取及时性：invoke 写文件后，下一轮扫描（≤1s）完成投递

## 4. 落痕语义保持与并发安全

- [x] 4.1 worker 中调用 `admin_monitor.invoke_manual(signal)`，保持 pending → final disposition 与 escalate 告警链路不变（按 admin_run_id 关联）
- [x] 4.2 异常路径保持：处置异常落 failed disposition（不丢痕），worker 捕获后继续领取后续任务
- [x] 4.3 AdminStore 跨线程使用验证：文件锁与线程亲和无关，append/read 在 worker 线程正常工作
- [x] 4.4 审视 `run_administrator` 与主循环/其它 worker 的共享状态（agent_runner 内部计数、session 管理），跨线程访问补锁或消除共享
- [x] 4.5 观察项：并行 admin run 在主树的实际写冲突——若出现（处置记录互相踩踏/commit 冲突），引入轻量操作分级或串行旗标（记录在实现报告，不阻塞本 change）

## 5. 验证

- [x] 5.1 单元/脚本验证：写入请求文件后 1 个扫描周期内被投递（拾取及时性）
- [x] 5.2 集成验证：处置运行期间（数分钟）主循环日志持续输出（派发/巡检未停摆）
- [x] 5.3 集成验证：连续两次 invoke，两个 run 并行执行（run_id 不同、实例 disposition 文件独立、互不覆盖），均正常落 final 记录
- [x] 5.4 集成验证：处置异常场景落 failed disposition，worker 存活并继续处理后续请求
- [x] 5.5 集成验证：并行 run 的提示词中写入路径为各自实例文件，Admin 按提示词写入后 runner 读到的是自身结果
- [x] 5.6 Dashboard 回归：呼叫 Admin 介入弹窗发起后拾取即时，多实例并行时弹窗输出按 run 正确区分
