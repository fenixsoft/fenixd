# 验证进程生命周期管理
<!-- knowledge: capability=verify-process-lifecycle rev=1 sources=spec/archive/2026-09-11-fix-verify-process-lifecycle -->

dev-server 与被测实例的进程组、登记与清扫契约：run 终态必收割、杀树杀全、孤儿自灭、端口不污染主树。

## 现行规则

- 终态收割义务：agent run 进入任意终态（成功、失败、取消、frozen 早退、chain_exhausted、日限 raise、未预期异常）时，runner 对本 run 使用过且未被有意交接（fast-track keep / repair 延迟 / keep_for_reuse）的每个 worktree 执行收割——停止其 dev-server 注册条目并扫杀该 worktree 游离进程；收割幂等（dispatch 层与 runner 层都触发时第二次为无害空操作）。
- 进程组杀树：dev-server spawn 使用 `start_new_session=True`（独立进程组）；停止按 SIGTERM 进程组 → 等待 → SIGKILL 进程组 → 单进程兜底的顺序终止整棵进程树，不只杀直接子进程；daemon 自身与其他 agent 进程（不同进程组）不受 killpg 影响。
- 父子绑定自杀：dev-server 入口脚本周期轮询父进程存活（`process.ppid === 1` 判定孤儿）并在成为孤儿后自行退出；不使用 PDEATHSIG（daemon 从 per-dispatch 线程 spawn，父线程死亡会误杀存活服务）。
- 周期清扫与豁免：daemon 主循环以 ≤10 分钟间隔周期执行 dev-server 孤儿清扫；「归属存活 attempt」的豁免判定必须校验引用进程为 claude 进程（marker 锚定），同 worktree 两个孤儿 dev-server 互相引用不构成有效豁免、均被清扫。
- 端口分配与耗尽兜底：端口探测在 bind 前设置 `SO_REUSEADDR`（TIME_WAIT 不判占用）；端口段耗尽时回退分配系统临时端口并留 WARNING 级留痕，不抛异常终止验证，不静默回退主树 8787 常驻实例。
- 被测实例登记制：command 型被测实例（verify.yaml serve.kind=command 与 `_ensure_app_reachable` 兜底 spawn）创建时向 `.fenix/verify-serving/servers.json` 登记（pid/port/spec/worktree），stop 时移除；spec 推进 done/verified 时同步 stop 登记服务、驱逐缓存条目并移除 serving worktree；daemon 启动与周期清扫按 /proc liveness 收割「无在飞 spec 但进程仍存活」的登记项。
- repair 轮服务保障：`_v2_launch_for_worktree` 具备幂等 ensure 语义——worktree 无存活注册条目时补启 dev-server；repair 复用载体轮必有可用 dev-server 与 BASE_URL 注入，不以空 env / 主树 8787 作为测试目标。
- 游离进程清扫升级：worktree 游离进程清扫在 cmdline 匹配外增加 `/proc/<pid>/cwd` 归属匹配（覆盖 argv 不含 worktree 路径的进程），并在 SIGTERM 宽限期后对无响应进程补 SIGKILL。

## 溯源

- [2026-09-11 fix-verify-process-lifecycle](spec/archive/2026-09-11-fix-verify-process-lifecycle/) — 新增 run 终态收割义务、进程组杀树、父绑定自杀、实例登记制与端口耗尽兜底（治理 dev-server 孙进程残留、双孤儿互引豁免失效、端口语义污染主树与 repair 轮打主树 8787）
