# Design: fix-verify-process-lifecycle

## Context

- dev-server 生命周期现状：
  - Spawn：`core/v2_dev_server.py:144-151` `subprocess.Popen(cmd, stdout/stderr=DEVNULL)`
    **无 start_new_session**；node 单进程，argv 带 `fenix-v2-dev-server` 标记。
  - 注册表：`core/agent_runner/v2_server.py:22` `_v2_servers: {wt_path: (port, proc)}`
    **纯内存**，daemon 重启即失忆。
  - 清理点：runner 终态若干分支（`runner.py:1063/1440/1487/1491`）+ dispatch 层
    （`dispatch.py:1156/1170/1514/1632`）；优雅关闭 `fenixd.py:603-613`；启动清扫
    `fenixd.py:193` → `v2_dev_server.cleanup_orphans`（`v2_dev_server.py:307-324`）
    ——**唯一孤儿清扫时机**。
  - worktree 粒度扫杀：`core/worktree_manager.py:1157-1190` `_kill_worktree_strays`
    （pgrep cmdline 含 `worktrees/<name>`、排除 claude 与自身、逐 PID SIGTERM、
    **无 SIGKILL 兜底**），挂 `cleanup()`/`keep_for_reuse`/`cleanup_stale_worktrees`。
  - 端口：`v2_dev_server.py:21-22` base=19000 range=20；`allocate_port`（:64-89）
    按 `19000 + ((run_seq+offset) % 20)` 探测；`_port_in_use`（:50-61）裸 bind
    无 SO_REUSEADDR；`run_seq` 每 daemon 生命周期归零。
- 09-04/09-05 事故链（log 实证）：
  1. daemon 重启时在飞 run 的 dev-server 被启动清扫豁免（`v2_dev_server.py:301-302`
     "归属存活 attempt，保留"），但新 daemon 注册表为空 → 无钩子可再接管 → claude
     死后成永生孤儿（01:19:09Z 补杀 1 PID、01:51:45Z 补杀 3 PID）。
  2. 每次重启清扫出 1~3 孤儿，两次重启之间持续累积。
  3. 09-05 02:52:25 `V2 test port exhausted: base=19000 range=20, used=[19017,19018]`
     ——注册表仅 2 条，~18 端口被游离监听占住。
  4. 耗尽 → `V2DevServerError` → `v2_server.py:52-57` 仅 WARNING 后**静默回退 8787
     主树常驻实例**（旧码污染验证形态，已实际发生）。
  5. supervisor 60s 窗口超时 kill -9，SIGTERM handler 不执行，dev-server 被 init 收养。
- 次级泄漏族：`verification.py` `_contract_static_servers` 缓存中的
  `CommandVerifyServer`（`Popen(shell=True, start_new_session=True)`，:253-257）仅在
  root/HEAD 变更/启动失败三处 stop（:128/:157/:263），spec 到 done/verified 无人回收；
  `_ensure_app_reachable` 兜底 spawn（:393-395）完全无跟踪。
- 豁免判定缺陷：`v2_dev_server.py:261-276` `_worktree_has_live_referencing_process`
  不过滤 claude（对照 `worktree_manager.py:1138-1155` 有 `_is_claude_process` 锚定）
  → 同 worktree 双孤儿互为"存活引用"互相豁免，永不清扫。
- 伴生缺陷：repair 复用载体时 `runner.py:1240` 仅 create 分支启动 dev-server，
  `pre_wt_path` 路径无服务、`_v2_inject_env` 返回空 → repair 轮测试打 8787 主树。
- 复用评估：dev-server 启动+就绪 <2s（log 实证同端口 stop→重起 19s 间隔成功），
  每轮真实成本在 worktree 创建 + node_modules 供给 + prepare 构建；每轮新 worktree
  静态根必然变化。跨轮常驻复用收益趋零、拉长进程寿命放大孤儿概率，与
  "常驻实例=旧码污染验证"防线语义冲突 → 放弃。

## Goals / Non-Goals

**Goals:**

1. 任意终态（含异常、被杀外的全部路径）后无 dev-server/游离进程残留。
2. daemon 被杀后孤儿自灭（ppid 绑定）+ 周期清扫兜底，泄漏可见窗口 ≤ 一个周期。
3. 端口段永不因游离监听耗尽；即使耗尽也绝不静默回退 8787 主树。
4. command 型被测实例全生命周期可观测、可收割；repair 轮必有专属 dev-server。

**Non-Goals:**

- 不做 dev-server 跨轮常驻复用（见 Context 评估结论）。
- 不改 verify.yaml 三段式契约（prepare/serve/ready）语义与 BASE_URL 注入铁律。
- 不改 worktree 复用（keep_for_reuse）机制本身——目录保、进程不保的现行语义维持。
- 不动主树 dashboard :8787 服务。
- 不做 fast-track 同根接养（pgrep marker 解析端口接养，仅在 worktree 复用成为
  高频路径后作为二期选项）。

## Decisions

**D1 — 终态收割用 `_execute_agent` 包 try/finally，不逐终态分支补调用。**
运行作用域维护 `used_wts`（本 run 创建/复用的 wt_path）与 `handed_off`（deliberate
keep 集合：fast-track/repair 延迟分支 :1437-1438、keep 分支 :1492-1497、取消 keep
分支 :1063-1071）；finally 对 `used_wts - handed_off` 且仍在注册表的条目调
`_v2_stop_for_worktree` + `_kill_worktree_strays`（幂等，双调无害）。一处 closing
覆盖 frozen 早退（:1043）、chain_exhausted（:1135）、熔断拦截（:1154）、日限 raise
（:1093）、任意异常——逐分支补调用已被事故证明必然漏。dispatch 层
（`dispatch.py:1039` fast-track worker 与 repair worker）加 worker 级 try/finally
兜底：runner success 返回后的 hand-off 边界内异常 runner 管不到。

**D2 — spawn 加 `start_new_session=True` + killpg 杀整树。**
与 `CommandVerifyServer` 既有模式对齐：`v2_dev_server.py:144` 加参数；`_kill`
（:188-200）改为 `os.killpg(getpgid(pid), SIGTERM)` → 等待 → `killpg SIGKILL` →
单进程兜底。把"杀整树"能力内置到停止原语，未来 serve 换 shell 包装形态不会重现
"只杀 shell 不杀孙进程"。

**D3 — ppid 轮询自杀绑定，不用 PDEATHSIG。**
`tests/v2/dev-server.mjs` 加 `setInterval` 检查 `process.ppid === 1` → `process.exit()`。
这是 dashboard `_claude_watchdog_loop`（`dashboard/server.py:1775-1813`）"绑生命周期、
防 PID 复用"的镜像。PDEATHSIG 被否：daemon 从 per-dispatch 线程 spawn
（`dispatch.py:511/1406`），Linux PDEATHSIG 在父**线程**死亡即触发，run 结束线程
退出会把存活服务提前误杀；ppid 轮询无此坑。

**D4 — 周期清扫 + 豁免过滤修复。**
主循环定时器族（对齐 config_check_ts 模式，`fenixd.py:215+`）加 10 分钟级
`cleanup_orphans`。前置修复：`v2_dev_server.py:261-276` 补 `_is_claude_process`
过滤——把 `worktree_manager.py:18` 判定抽到公共模块防循环依赖。无此修复则互引
孤儿永不清扫，周期清扫形同虚设。

**D5 — 端口策略：SO_REUSEADDR + 耗尽回退临时端口，绝不回退 8787。**
`_port_in_use` bind 前 `setsockopt(SO_REUSEADDR)` 消除 TIME_WAIT 假性轮换；
`allocate_port` 耗尽时不再抛 `V2DevServerError`，回退系统临时端口（复用
`verify_contract.py:249` `_find_free_port`，上移共用）+ WARNING。宁用随机端口
也绝不静默回退主树常驻实例（09-05 已实证该路径污染验证）。可选增强：`run_seq`
持久化到 `.fenix/` 降低重启后碰撞概率，不作为验收项。

**D6 — command 型实例登记制：`.fenix/verify-serving/servers.json`。**
`CommandVerifyServer` 创建时登记（pid/port/spec/wt）、stop 时移除；
`_ensure_app_reachable` 兜底 spawn 同登记。spec 推进 done/verified 在
`_on_spec_verified` 调用点同步 stop + 驱逐 `_contract_static_servers[spec]` +
`_remove_serving_worktree`。daemon 启动与周期清扫按 /proc liveness 收割"无在飞
spec 但进程仍存活"的登记项。文件属运行时状态（`kind: reference`），不入库。

**D7 — repair 轮服务保障：`_v2_launch_for_worktree` 改幂等 ensure 语义。**
对无注册条目的 wt_path 一律补启（而非仅在 create 分支启动），`_v2_inject_env`
不再返回空，repair 轮测试落在专属实例上。

**D8 — `_kill_worktree_strays` 能力升级。**
cmdline 匹配外加 `/proc/<pid>/cwd` readlink 匹配（抓 agent 经 Bash 起的
argv 无路径进程）；SIGTERM 后短等待、SIGKILL 兜底。

## Risks / Trade-offs

- [try/finally 收割与 dispatch 层 hand-off 语义交织，误收割 keep_for_reuse 的
  worktree 服务] → `handed_off` 集合显式枚举三个 keep 分支；收割幂等设计使双调
  无害；keep 分支单测锁定不被收割。
- [killpg 若 pid 恰好死亡引 ProcessLookupError] → 停止原语全程 try/except 包裹，
  单进程兜底路径覆盖竞态。
- [ppid 轮询间隔内孤儿短暂存活] → 轮询秒级间隔 + 周期清扫兜底，两道防线叠加。
- [servers.json 与真实进程状态漂移（写入失败/崩溃丢条目）] → 登记制是兜底增强
  而非唯一防线，v2 dev-server 仍有 marker pgrep 扫描路径；json 读写走
  `.fenix/` 既有 lock 模式。
- [SO_REUSEADDR 在极端下两个 listener 短暂共存] → 仅用于探测判定，真实 bind 仍
  由 node dev-server 自身完成，冲突会在 ready 探测阶段暴露为验证失败而非静默污染。
- [改动横跨 runner/dispatch/verification 多个核心链路] → 分组提交（收割原语 →
  终态挂钩 → 端口与登记制），每组独立可回滚；E2E 场景（run 中途重启 daemon）
  作为验收门。

## Migration Plan

合并后 `touch .fenix/restart_request` 重启 daemon 生效；首启 `cleanup_orphans`
自然清掉存量孤儿。servers.json 首次运行自动创建，无迁移。回滚 = revert 提交
再重启（servers.json 残留无副作用，旧代码不读）。

## Open Questions

（无——dev-server 复用已评估为放弃，端口策略取"确定性 + 兜底"路线）
