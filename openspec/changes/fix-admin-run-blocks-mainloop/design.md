# design

## Context

`fenixd.py` 主循环（1s 粒度）中的 `_check_admin_invoke_requests()` 拾取 `.fenix/admin_invoke_request.json` 后，**同步**调用 `admin_monitor.invoke_manual(signal)` → `agent_runner.run_administrator(signal)` → `_run_claude(...)`。`_run_claude` 阻塞直至处置完成（实测单次数分钟），期间主循环完全停摆：SPEC 派发、admin_monitor 巡检、后续 invoke 拾取全部延迟。实测 Dashboard 发起呼叫后拾取延迟最高 231 秒。

Administrator 的资源模型（add-administrator-agent design D4）：直接在主树操作（不建 worktree），涉及 git、进程管理、`.fenix/admin_disposition.json`（单文件，执行前 clear、完成后覆写）、STATE.md。这些操作互斥，不能并行多实例。

## Goals

- 主循环不再被 admin run 阻塞（拾取后立即投递，处置后台执行）
- Administrator 对主树的处理保持串行（同一时刻最多一个 run，先到先得排队）
- 处置落痕语义不变：pending disposition（执行前）→ final disposition（结束后，含 escalate 升级告警）→ 异常时 failed disposition
- 后台工作线程不因单次处置异常退出

## Decisions

### D1: 后台执行用线程而非子进程

`run_administrator` 与主循环共享 AgentRunner/AdminStore/logger 等对象。用 `threading.Thread`（daemon=True）执行即可消掉主循环阻塞；子进程方案需要跨进程序列化整个 runner 上下文，复杂度高且无额外收益。风险：Python GIL 对阻塞式 `_run_claude`（subprocess 等待 + 文件 IO）无影响，CPU 计算段占比可忽略。

### D2: 串行化用队列 + 单工作线程（先到先得）

`queue.Queue` 投递信号 dict，后台单 worker 线程循环 `get()` → 执行处置。天然满足"同一时间最多一个 admin run"且先到先得；不需要显式锁。主循环拾取到请求后 `put()` 即返回。

### D3: 主循环侧只拾取与投递，不再直接调 invoke_manual

`_check_admin_invoke_requests` 改为：读文件 → 删文件（先读后删语义保留）→ 校验 spec/构造 signal（含 prompt 透传）→ `admin_queue.put(signal)`。原有"spec 缺失忽略""损坏文件删除"逻辑保留。

### D4: 落痕与升级语义保留在 worker 路径

worker 调 `admin_monitor.invoke_manual(signal)`（维持既有入口）：pending disposition 在 `run_administrator` 执行前落（现有代码），final disposition 与 escalate 告警在返回后落（现有代码），异常走 `invoke_manual` 的既有 except 分支（failed disposition + 升级）。worker 循环体 catch-all，保证线程存活。

### D5: 主树并发窗口的处理

处置在后台执行后，主循环的 SPEC 派发可能与 admin run 在主树上并发。决策：**保持现状不改派发逻辑**——既有 admin_monitor 自动巡检唤起路径本就与主循环并发窗口共存（巡检线程化先例），且 admin run 时长内的派发行为与原串行时序一致（原本该窗口内主循环也停摆，SPEC 本就不会被派发；移出后新出现的并发窗口由 admin run 的实际操作性质决定——只读诊断为主，写操作集中在收尾 commit）。实现时须在 tasks 中加入观察项：若发现派发与处置的实际写冲突，再引入"admin run 期间暂停派发"的轻量旗标。

## Risks

- AdminStore 追加写入的线程安全：AdminStore 内部有文件锁（read/append 路径），跨线程使用需确认锁实现与线程亲和无关（tasks 中验证）
- `agent_runner` 内部若有主循环共享的可变状态（如进度计数），跨线程访问需加锁或复制（tasks 中审视）
- 后台线程异常退出导致队列吞请求：worker 循环 catch-all + 线程存活监控（主循环检测 worker 存活，死亡时告警）
