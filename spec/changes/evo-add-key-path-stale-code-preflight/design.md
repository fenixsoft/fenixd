# design：关键路径执行前陈旧代码预检

## 现状与挂点

- 陈旧判定在 daemon 主文件：启动时建立受跟踪代码文件 mtime 基线（fenixd.py:651-652），_update_stale_code_state 每 30 秒重算 self._code_stale（fenixd.py:1359），自愈 tick _maybe_stale_selfheal_tick（fenixd.py:2192）在连续空闲满足时写 .fenix/restart_request（fenixd.py:2494 一带）。
- self._code_stale 目前仅被自愈与告警消费，关键路径零消费。
- supervisor（.fenix/bin/fenixd_supervisor.py:842-846）每 2 秒轮询 restart_request，命中即 SIGTERM → daemon 排水（50 秒窗）→ 重启；生产已消费 351 次，通道成熟。
- 三个插入点（均在主树语境执行，无 worktree HEAD 误配）：
  - 收尾提交：core/pm_engine/engine.py 收尾步 → core/verify_report.py 的 _commit_verification_report；
  - 蒸馏派发：core/knowledge.py 的 DistillManager.dispatch / dispatch_distill；
  - admin choice：core/admin_monitor.py 的 _apply_choice_execution → core/dashboard/data/admin_actions.py 的 execute_adjudication_choice。

## 方案

1. 新增模块级陈旧旗标注册表（core/code_stale_flag.py）：daemon 启动初始化与每 30 秒检测点把 _code_stale 同步进注册表；core/ 关键路径模块 import 查询。import 方向必须 core←daemon 单向，故注册表落在 core/ 侧，daemon 只写入。线程安全：daemon 检测线程写、车道线程读。
2. 预检语义（三个插入点同款）：动作开始前查询；陈旧 → logger.WARNING 一条 + 确保 restart_request 存在（已存在不写、不刷 mtime）+ 照常执行动作。不阻塞、不自我中断。
3. fail-open：注册表未注册（单测/冷启动）返回 False，关键路径零感知。

## 设计决策点（实现者须保持）

- 「照常完成 + 异步重启」而非「让位」：restart_request 写入后 supervisor 最快 2 秒 SIGTERM，daemon 进程内动作（报告提交、choice 执行、蒸馏派发）可能在执行中被打断。可接受依据：收尾的 verification-report 文件先落盘后提交、重启后收尾可重放；蒸馏派发在装载 R1 后有 pending 台账、重启后 recover_pending 接管。残余风险：若进程仍是更旧（无 R1）代码，派发被打断仍可能产生无台账批次——该残余由知识蒸馏 stray 对账扩展（另条目）兜底，不在本 SPEC 范围。
- 不用 git rev-parse HEAD 现场比对：mtime 基线已覆盖未提交修改，读旗标零开销；HEAD 比对至多作补充手段。
- 与既有机制划界：不动空闲阈值自愈触发、不动悬空超时（现配 8 小时）强转、不新增告警分档。

## 测试要点

- 注册表注册/查询/未注册 fail-open 三态；
- 三个关键路径在旗标置位下各产生 WARNING 且 restart_request 出现、动作返回值与产物不变；
- restart_request 已存在时不重复写、不刷 mtime；
- tests/test_stale_code_selfheal.py 全量回归。
