# Design: fix-daemon-lifecycle-races

## Context

调查确认三组生命周期竞态（详见 fenixd.log 09-05T16:31–17:33 / 09-06T02:13 与 supervisor.log）：

1. **排水被截断**：daemon（09-05 15:42 UTC+8 起新代码）收 SIGTERM 进入 1800s 排水（`fenixd.py:908-935`，等在途 run 自然终态、不杀不写标记）；supervisor 进程（8/26 启动，内存持旧代码）60s 硬 SIGKILL。结果：interrupted 标记写入（`liveness.py:491-534`）与 sidecar 保全（`_preserve_interrupted_runs`）全未执行，run 1788625917/1788627192 永久无终态，claude 孤儿进程与新 daemon 并行跑同一 spec。D2 修复（`bin/fenixd_supervisor.py:71-81`，SIGKILL 等待 = drain+120s）代码正确但 supervisor 进程未重启而未生效。
2. **重启重验无计数**：恢复路径 `testing→implemented`（`state_machine.py:622-634`）清 `tester_run/_retry_count`，重派全量 verify（场景冻结复用只省出题；planner-judge 实测 68–113 turns 全新跑）。无跨重启重验计数，毒 spec 可借反复 restart 无限重验。runner 内部 `attempt 1/3`（`runner.py:1549`）是单次 dispatch 的网关故障重试链，与本问题无关。
3. **done→pushed 双路径并发**：verify 成功后同步直调 `_on_spec_done`（`engine.py:363`）与 event_bus 的 spec_done 事件（`event_bus.py:332-336` diff 驱动）并发进入 `_auto_approve` → `approve_push`；`status=="done"` 门槛检查（`engine.py:980`）在对方 push 完成（≈12s）前双双通过 → 双 `git push main`、重复 project log、输家撞 `PUSHED:[]` 终态报 ERROR（历史 40 条）。另有真实非法迁移：stale-result 防护拨回 implemented（01:51:47）与在飞 planner-judge 完成（02:13:12）竞态 → `implemented→verified` 被拒后 fallback 又转 testing 重派整轮 verifier。

约束：daemon 单实例锁（`daemon.lock`）；STATE.md 为状态唯一持久层（`_` 前缀内部字段解析已支持，`state_machine.py:140-142`）；run jsonl 由 daemon 侧转写（孤儿 claude 进程存活也不会再产生新事件——终态判定不能等孤儿进程）。

## Goals / Non-Goals

**Goals:**
- 任何 daemon 非正常死亡（SIGKILL/断电/崩溃）后，遗留无终态 run 在新 daemon 启动时被补写 interrupted 终态
- drain 窗口与 supervisor SIGKILL 等待不一致时产生可观测告警
- 重启重验次数持久化，超限冻结
- `old==new` 自迁移幂等降级，ERROR 只留真实非法迁移
- done→pushed 全链单飞，双路径并发无害化
- 在飞 verify run 遇 spec 被重置时静默丢弃结果，不再触发重复派发

**Non-Goals:**
- 不改 supervisor 的进程模型（仍单实例长驻、auto-restart）
- 不做 run 文件格式重构（仍 jsonl 追加、终态事件约定不变）
- 不处理 fast-track 语义冲突打回等其他生命周期缺口
- 不做 admin 自动处置升级链扩展（复用现有 freeze_spec / admin 巡检）

## Decisions

### D1 启动时终态补写扫描（terminal-state sweep），而非「排水先写 interrupted」

自省建议「daemon 关停路径对在途 run 补写终态」有两个缺陷：排水语义本就是等自然收工，先写 interrupted 会污染正常完成路径（result 与 interrupted 并存、读侧歧义）；且 SIGKILL 场景 daemon 根本没有执行机会。改在**新 daemon 启动早期**（AgentRunner 初始化、任何派发前）扫 `.fenix/runs/*.jsonl`，尾部无终态事件（result/interrupted/error/cancelled，判定口径对齐 `runner.py:2595-2627` 的 `_run_was_interrupted` 与 admin 侧 `admin_monitor.py:835`）→ 追加 `{"type": "interrupted", "reason": "startup terminal-state sweep"}`。daemon 刚启动时注册表为空 + 单实例锁，存量无终态 run 必为遗留死 run；孤儿 claude 进程存活不阻塞补写（写者是 daemon，孤儿不会再写文件）。排水标记（draining event）不引入——sweep 主判据已充分，少一个写路径少一类漂移。备选（排水快照文件）被否：需额外原子性与清理语义，增益为零。

### D2 supervisor SIGKILL 等待窗口自报 + daemon 启动比对

supervisor `main()` 启动时写 `.fenix/supervisor_runtime.json`（`{"sigkill_wait": <n>, "started_at": <iso>}`，原子写）。daemon 启动时若 `shutdown_drain_seconds > 0`：文件缺失 → WARNING「supervisor 未上报等待窗口（疑似旧代码进程），排水可能被截断，建议重启 supervisor」；`sigkill_wait < drain + 120` → 同类 WARNING。告警走 logger WARNING + `_append_project_log`（不新增 admin signal 类型，避免过度设计）。旧 supervisor 不会写文件 → 缺失分支即精准命中 8/26 旧进程场景。

### D3 重验计数 `_verify_redo_count`：恢复路径递增 + verify 成功清零 + 超限冻结

字段加入 `state_machine.py` 字段名单（与 `_impl_run_budget_used` 同段）。递增点：`recover_interrupted` 的 `testing→implemented` 分支（读旧值 +1 写入）。阈值：`agents.verify_redo_budget`（缺省 3，复用现有配置加载）。达到阈值 → 调 `freeze_spec`（结构化冻结现成机制），error 注明「重启重验超限，等待人工裁决」。清零点：verify 自然通过（verified/done 落定，对齐 `_verify_fail_rounds` 清零点 `verification.py:1312-1316`）与人工 `unfreeze_spec`。语义与 `_verify_fail_rounds`（失败→fix 轮数）正交，互不替代。

### D4 `old==new` 幂等自迁移：transition 入口短路，但须复查返回值依赖

`transition()` 开头：`if new_status == old_status: logger.info(幂等自迁移); return True`。**风险**：现有代码把返回 False 当「已迁移过」信号——`engine.py:332` `if transition(done)` 注释明言「done→done 非法转换返回 False 不会重复覆盖 total_duration」。实现时全库 grep `transition(` 调用点逐个核对：依赖 False 阻断重复副作用的调用点，改用入口前置状态判断或接受幂等覆盖（值相同覆盖无害，但重复日志需消噪）。`transition_gate` 同型处理。

### D5 done→pushed 全链单飞：pm_engine 级 push 互斥锁

`pm_engine` 实例级 `threading.Lock`，`approve_push` 入口 acquire（blocking）→ 锁内重读 spec status → 执行 → release。锁覆盖含 `git push` 的全临界区（check-then-act 原子化；push 低频，12s 串行可接受——并发 push main 本身亦是隐患，串行化顺带根治）。第二流进锁后见 pushed → 幂等跳过（返回 True），重复 project log / 双 push / ERROR 噪声一并消失。备选（per-spec 锁）被否：不同 spec 并发 push main 的竞态同样需要串行，全局锁更正确。`_on_spec_done` 双路径不合并（同步直调有其存在的时序理由，见 `engine.py:356-362` 注释），仅危害消除即可。

### D6 在飞 verify 结果丢弃：入口状态判据，不建登记集合

verifier/planner-judge 结果处理入口（02:13:12 `Verifier result: status=verified` 的消费点）加前置判据：`spec.status != "testing"` → 结果 DEBUG 丢弃（注明 run_id 与当前状态），不走迁移、不触发 fallback 重派。覆盖 stale-result 拨回（implemented）与一切状态漂移变体。备选（拨回时登记 invalidated run_id 集合）被否：集合需要生命周期管理，而状态判据是现有 transition 校验的自然前置化，且定位该 fallback（02:13:12.745 `implemented→testing` 回退派发）一并拆除。实现时需回归确认正常路径（testing 状态消费结果）不受影响。

## Risks / Trade-offs

- [sweep 误补写合法进行中 run] → 启动时序保证（sweep 先于任何派发）+ 单实例锁；测试覆盖「sweep 后正常派发新 run」场景
- [sweep 与孤儿 claude 进程并存] → 补写不影响孤儿；孤儿回收由 v2_dev_server / worktree_manager 既有机制承接，不在本 SPEC 范围
- [D4 幂等 True 改变既有调用点行为] → 强制全库调用点核查清单进 tasks；仅允许「值相同覆盖无害 + 日志消噪」类调用点依赖新语义
- [D5 全局 push 锁死锁] → 锁内不调用会再获该锁的路径（approve_push 自身不可重入调用）；锁范围最小化
- [D6 状态判据误伤正常结果] → 正常路径 spec 恒为 testing（transition testing→verified 由同一流程发起）；回归测试覆盖「结果到达时状态尚未变更」的正常竞态
- [supervisor_runtime.json 与 supervisor 生命周期漂移（文件残留自旧进程）] → supervisor 每次启动覆写 + daemon 比对 started_at 与 daemon_started 时间戳接近性，漂移超阈值按缺失处理

## Migration Plan

纯行为修复 + 新增字段/文件，无数据迁移。上线顺序：实现合并 → supervisor 进程重启（S1 已于立项前人工执行，代码部署后自然加载新逻辑）→ daemon 经 restart_request 重启加载新代码。回滚 = git revert（新字段残留无害，解析端向后兼容）。

## Open Questions

（无——阈值缺省 3、字段命名、锁粒度均已在决策中定案；如实现中发现 `transition(` 调用点存在 D4 无法兼容的依赖，回退该调用点为前置状态判断并登记 findings）
