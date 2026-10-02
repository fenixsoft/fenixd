<!-- knowledge: capability=supervisor-hosting rev=1 sources=spec/archive/2026-09-18-fix-supervisor-hosting-chain -->

# supervisor 托管链

daemon 由 supervisor 托管运行：tmux 仅作脱离终端的承载手段，信号消费、优雅重启与停止语义都锚定 supervisor 的存在性。

## 现行规则

- 目标项目根解析优先级：`--project-root` 参数 > `FENIX_PROJECT_ROOT` 环境变量 > `Path.cwd()`；禁止由 `Path(__file__).resolve()` 派生（该路径会跟随项目内 `.fenix/bin` 软链回到框架主树，绑错目标）。解析出的项目根下必须存在 `.fenix/`，缺失时打印可读错误并以非零码退出，不启动任何 daemon 进程。
- supervisor 每次启动时原子覆写 `.fenix/supervisor_runtime.json`（临时文件 + rename），五键齐备：`sigkill_wait`、`started_at`、`pid`、`script_hash`（本脚本内容 sha256）、`project_root`；写入失败不中断 supervisor 主流程。
- 托管态三态：`hosting_state(root)` 返回 `managed`（supervisor 在跑）/ `unmanaged`（有 daemon 进程但无 supervisor）/ `stopped`（两者皆无）；`supervisor_running(root)` 扫描 `/proc`（`cmdline` 含 `fenixd_supervisor` 且 `cwd` 或 `--project-root` 解析后等于项目根），`/proc` 不可读时返回 False 不抛异常。
- 唯一托管启动路径：`start_daemon(root)` 在项目唯一 tmux session 内执行 `python3 .fenix/bin/fenixd_supervisor.py --project-root <root>`（日志落 `.fenix/logs/supervisor.log`），不以 `python3 .fenix/fenixd.py` 直接作为 session 命令，daemon 必须是 supervisor 的子进程；启动前校验项目根存在 `.fenix` 与 `.fenix/STATE.md`；操作幂等（已在运行返回 `already=True`，不建第二个 session）。
- 托管停止语义：`stop_daemon(root)` 按序执行——① 写 `.fenix/stop`（使 supervisor 不在 daemon 退出后重新拉起）② 经 `/proc` 定位该项目的 daemon 进程发 SIGTERM ③ 轮询等待 daemon 与 supervisor 双双退出（上限约 30 秒）④ 超时以 `tmux kill-session` 强制终止并对残留进程补发 SIGKILL ⑤ 无论成败清除 `.fenix/stop`；停止未运行项目幂等返回成功。
- 信号只写给有消费者的项目：`restart-daemon` hook 写 `.fenix/restart_request` 前校验该项目存在活跃 supervisor，不存在时返回失败并触发既有告警链，detail 说明「本项目无 supervisor，重启请求不会被消费」；审批推送写 `.fenix/approve_push_request.json` 前校验托管态为 `managed`——`unmanaged` 返回 409 并附「安装托管」指引且不写信号文件，`stopped` 维持「daemon 未运行，请先启动 daemon」文案与行为。
- daemon 启动自检把 supervisor 存在性作为独立判定项（不受 `admin.shutdown_drain_seconds` 取值影响，drain=0 仍检查存在性、仅跳过 drain 一致性比对）；判定为缺失时落 WARNING 并经 AdminStore 写一条 `severity: major`、`signal_type: supervisor_missing` 的 escalation 告警，描述说明「未受 supervisor 托管，restart_request 不会被消费」，同一未处置告警去重不堆积。
- `restart_failed` 升级建议按托管态分支：`unmanaged`/`stopped` 时指引经 Dashboard 项目页「安装 supervisor 托管」或 `/fenix-setup` 恢复托管，不得出现「手动启动 `.fenix/bin/fenixd_supervisor.py`」这类会绑定框架主树的直接命令；`managed` 时指引检查 supervisor 进程与 daemon 排水状态。
- 安装托管操作：Dashboard `POST /api/projects/<name>/install-hosting` 对 `unmanaged` 项目执行「停止裸 daemon → 经 supervisor 启动」转入 `managed`，对 `managed` 项目幂等返回不重启，对 `stopped` 项目等价于启动；必须复用 `stop_daemon`/`start_daemon`、不得绕过直接操作进程或 tmux；成功时广播 SSE `refresh`。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：daemon 由 tmux/supervisor 托管：重启走 env -u CLAUDE_PID 协议，杀 tmux server 会连带杀 daemon，须重建托管链
- 2026-09-18 fix-supervisor-hosting-chain（spec/archive/2026-09-18-fix-supervisor-hosting-chain） — 固化项目根解析守卫与五键运行时自报、托管态三态判定、唯一托管启动/停止语义、supervisor_missing 告警、restart-daemon 与审批推送的消费方校验、install-hosting 端点
