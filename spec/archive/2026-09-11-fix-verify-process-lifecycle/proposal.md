# Proposal: fix-verify-process-lifecycle

## Why

验证用 dev-server 的进程生命周期存在四缺口叠加（内存注册表重启失忆 + 仅启动时清扫 + 豁免无接管 + daemon 被杀零兜底），游离进程已成常态：2026-09-04 两次人工补杀共 4 个 PID，每次 daemon 重启均清扫出 1~3 个孤儿；**2026-09-05 02:52:25 V2 端口段（19000-19019）已实际耗尽**（20 个端口约 18 个被游离监听占住），且耗尽后静默回退 8787 主树常驻实例——「旧码污染验证」的污染形态已实际发生，非潜在风险。另有 repair 复用载体轮无 dev-server、测试静默打主树 8787 的伴生缺陷。

## What Changes

- **终态收割**：`core/agent_runner/runner.py` `_execute_agent` 包 try/finally，维护本 run 使用/有意交接的 worktree 集合，finally 对非交接集合收割 dev-server 注册条目 + 扫杀 worktree 游离进程——一处覆盖 frozen 早退、chain_exhausted、日限 raise、任意异常等全部漏网终态。
- **杀整树**：dev-server spawn 加 `start_new_session=True`，停止逻辑从单进程 SIGTERM 升级为进程组 killpg（TERM → 等待 → KILL → 单进程兜底），杜绝"只杀 shell 不杀孙进程"。
- **ppid 自杀绑定**：`tests/v2/dev-server.mjs` 周期轮询 `process.ppid === 1` 即退出（claude-watchdog 同款父子绑定模式），daemon 被杀后孤儿自灭。明确不用 PDEATHSIG（per-dispatch 线程 spawn，父线程死亡会误杀存活服务）。
- **周期清扫 + 豁免修复**：daemon 主循环加 10 分钟级低频 `cleanup_orphans`（泄漏可见窗口从"直到下次重启"压到一个周期）；豁免判定补 `_is_claude_process` 过滤，修复同 worktree 双孤儿互为"存活引用"互相豁免、永不清扫的缺陷。
- **端口加固**：`_port_in_use` 加 `SO_REUSEADDR` 消除 TIME_WAIT 假性轮换；端口耗尽不再抛异常静默回退 8787 主树，改为回退系统临时端口 + WARNING 留痕。
- **command 型被测实例登记制**：新增 `.fenix/verify-serving/servers.json`（pid/port/spec/worktree），`CommandVerifyServer` 与 `_ensure_app_reachable` 兜底 spawn 创建时登记、stop 时移除，daemon 启动与周期清扫按 /proc liveness 收割；spec 推进 done/verified 时同步驱逐。
- **repair 轮 dev-server 补启**：`_v2_launch_for_worktree` 改幂等 ensure 语义，repair 复用载体轮无注册条目时补启，消灭静默打 8787 主树的路径。
- **明确不做**：dev-server 跨轮常驻复用（收益趋零：启动+就绪 <2s；风险为负：拉长进程寿命正是本次孤儿事故的放大器）。

## Capabilities

### New Capabilities

- `verify-process-lifecycle`: 验证进程（dev-server / command 型被测实例 / worktree 游离进程）的全生命周期治理——终态收割义务、进程组杀树、父子绑定自杀、周期清扫与豁免规则、端口分配与耗尽兜底、被测实例登记制、repair 轮服务保障。

### Modified Capabilities

（无——归档能力 `worktree-test-server`（add-worktree-test-server）、`worktree-hygiene`（fix-fenix-token-waste）的需求不被本变更修改，本变更为其未覆盖的生命周期收口新增能力）

## Impact

- **代码**：`core/agent_runner/runner.py`（终态 try/finally）、`core/agent_runner/v2_server.py`（launch 幂等 ensure、耗尽兜底路径）、`core/v2_dev_server.py`（start_new_session/killpg/SO_REUSEADDR/临时端口回退/豁免过滤）、`core/worktree_manager.py`（`_kill_worktree_strays` cwd 盲区 + SIGKILL 兜底）、`core/pm_engine/verification.py` + `core/verify_contract.py`（servers.json 登记制、spec verified 驱逐）、`tests/v2/dev-server.mjs`（ppid 绑定）、`fenixd.py`（周期清扫定时器）。
- **新增运行时状态文件**：`.fenix/verify-serving/servers.json`（登记制载体，`kind: reference`，不入库交付物）。
- **测试**：新建 `tests/test_v2_dev_server.py`（当前 v2_dev_server.py 零专项覆盖），补 `tests/test_agent_runner.py`、`tests/test_worktree_stray_and_identical.py`、`tests/test_pm_verification.py`；含一条对齐事故的 E2E 场景（run 中途重启 daemon → run 结束 → 一个清扫周期内回收 → 端口段全量可用）。
- **不受影响**：verify.yaml 三段式契约语义、worktree 复用（keep_for_reuse）机制、主树 dashboard :8787 服务本身。
