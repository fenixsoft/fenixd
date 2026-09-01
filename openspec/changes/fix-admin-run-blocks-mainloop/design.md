# design

## Context

`fenixd.py` 主循环（1s 粒度）中的 `_check_admin_invoke_requests()` 拾取 `.fenix/admin_invoke_request.json` 后，**同步**调用 `admin_monitor.invoke_manual(signal)` → `agent_runner.run_administrator(signal)` → `_run_claude(...)`。`_run_claude` 阻塞直至处置完成（实测单次数分钟），期间主循环完全停摆：SPEC 派发、admin_monitor 巡检、后续 invoke 拾取全部延迟。实测 Dashboard 发起呼叫后拾取延迟最高 231 秒。

Administrator 的资源模型（add-administrator-agent design D4）：直接在主树操作（不建 worktree），涉及 git、进程管理、STATE.md、处置结果文件。用户决策（2026-09-01）：**不建 worktree、保留主树操作、容忍主树写冲突风险**；但处置状态文件必须按实例分离。

## Goals

- 主循环不再被 admin run 阻塞（拾取后立即投递，处置后台执行）
- Administrator 支持并行多实例（worker 池，数量可配置，默认 2）
- 每个实例的处置状态文件相互独立（`.fenix/admin_disposition-<run_id>.json`）
- 处置落痕语义不变：pending disposition（执行前）→ final disposition（结束后，按 run_id 关联）→ 异常时 failed disposition
- worker 不因单次处置异常退出

## Decisions

### D1: 后台执行用线程池而非子进程

`run_administrator` 与主循环共享 AgentRunner/AdminStore/logger 等对象。用 `concurrent.futures.ThreadPoolExecutor`（max_workers 可配置，默认 2）执行即可消掉主循环阻塞；子进程方案需要跨进程序列化整个 runner 上下文，复杂度高且无额外收益。风险：Python GIL 对阻塞式 `_run_claude`（subprocess 等待 + 文件 IO）无影响。

### D2: 主循环侧只拾取与投递

`_check_admin_invoke_requests` 改为：读文件 → 删文件（先读后删语义保留）→ 校验 spec/构造 signal（含 prompt 透传）→ `executor.submit(worker_run, signal)`。原有"spec 缺失忽略""损坏文件删除"逻辑保留。

### D3: 处置状态文件按 run 实例分离

现状：runner 执行前 `_clear_admin_disposition()` 删 `.fenix/admin_disposition.json`，提示词指示 Admin 写入该路径，执行后 `_read_admin_disposition()` 读取——全局单文件，并行实例互相覆盖。

改造：
- `run_administrator(signal)` 生成 run_id 后，实例文件路径为 `.fenix/admin_disposition-<run_id>.json`
- `_clear_admin_disposition(path)` / `_read_admin_disposition(path)` 按传入路径操作（参数化）
- `prompt_builder` 的 administrator 分支把写入路径注入提示词（替换固定的 `.fenix/admin_disposition.json` 字样）
- run 结束读取自身文件落 final disposition 后删除实例文件
- `.fenix/admin_disposition.json` 旧路径不再使用（迁移说明：旧文件若存在直接忽略/清理）

### D4: 落痕与升级语义保留在 worker 路径

worker 调 `admin_monitor.invoke_manual(signal)`（维持既有入口）：pending disposition 在 `run_administrator` 执行前落（现有代码），final disposition 与 escalate 告警在返回后落（现有代码），异常走 `invoke_manual` 的既有 except 分支（failed disposition + 升级）。worker 函数体 catch-all，保证线程池 worker 存活（ThreadPoolExecutor 默认对异常任务安全，但需在 worker 函数内 catch-all 以保持任务边界清晰）。AdminStore 记录已按 admin_run_id 关联，天然支持并行；其文件锁与线程亲和无关（tasks 中验证）。

### D5: 主树并发风险（用户已决策容忍）

多个 admin run 并行在主树操作（git/进程/STATE.md）存在写冲突风险。用户决策（2026-09-01）：不建 worktree、容忍该风险（admin 处置多为只读诊断 + 收尾单次 commit，实际冲突窗口小）。实现不做主树互斥，但 tasks 中加入观察项：若实际出现冲突（处置记录互相踩踏/commit 冲突），再引入轻量串行旗标或操作分级。

### D6: worker 数量可配置

`dashboard.admin_workers`（或 `admin.workers`，默认 2）配置项；0 表示不启用后台池（回退同步行为，保留逃生门）。同步行为回退时 disposition 路径参数化仍生效（单实例路径）。

## Risks

- AgentStore/agent_runner 跨线程共享状态：AdminStore 文件锁验证（tasks 4.1）；agent_runner 内部若有无锁可变状态需审视（tasks 4.2）
- 实例文件泄漏：run 异常中断时 `admin_disposition-<run_id>.json` 残留——无功能影响（按 run_id 读取），但需在 tasks 中加清理（拾取新请求时可顺带清理超过 24h 的残留实例文件）
- 主树并发写冲突：用户已决策容忍（D5）
