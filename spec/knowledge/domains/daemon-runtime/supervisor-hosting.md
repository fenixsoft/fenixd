<!-- knowledge: capability=supervisor-hosting rev=3 sources=spec/archive/2026-09-18-fix-supervisor-hosting-chain,spec/knowledge/_inbox/done/host-wide-sigkill-hosting-chain-wipeout.md,spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md -->

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
- 托管链的宿主级暴露面：supervisor→daemon→dashboard 整条托管链只承载于 tmux 会话，不注册任何 systemd unit。宿主机级全用户态进程死亡事件（如全量 SIGKILL，内核与 systemd 本身存活）发生后，只有 systemd 管理的服务会被自动重启，托管链三进程无人拉起、整链停机直至人工恢复；supervisor 看门狗自身也在事件中死亡——看门狗没有更高层看护，是托管链停机时长的放大器。整链连坐死亡有两个已知变体：单独杀 tmux server 与宿主机级事件，后果同构。识别形态：supervisor.log 无 exited 收尾行、daemon 日志停在正常周期内容、tmux 会话整体消失（区别于优雅停机）。
- 托管链整链死亡后的人工重建：supervisor 会话以 `python3 .fenix/bin/fenix_session.py name <项目根>` 生成会话名，在其中以 `python3 .fenix/bin/fenixd_supervisor.py --project-root <项目根>` 拉起 supervisor（配方以 skills/fenix-setup/SKILL.md 为准）；dashboard 常驻会话（fenix-dashboard）以 `env -u CLAUDE_PID` 剥离环境后重建。重建完成后按五点判据验证：`.fenix/supervisor_runtime.json` 已刷新（新 pid 与新 script_hash）、daemon 全量扫描正常消化积压事件、dashboard 端口 curl 返回 200、真实 python 进程的 environ 无 `CLAUDE_PID`、dashboard dist 构建产物不落后于 src。
- 代码改动生效语义：daemon 进程的代码改动须经重启才生效（模块启动时加载），单测通过不等于生产生效；在飞 run 期间不重启，等空窗再重启。诊断「修复无效」先核对 `.fenix/daemon_started`（daemon 启动时刻锚点）与修复提交时间的先后，再归因代码。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：daemon 由 tmux/supervisor 托管：重启走 env -u CLAUDE_PID 协议，杀 tmux server 会连带杀 daemon，须重建托管链
- 2026-09-18 fix-supervisor-hosting-chain（spec/archive/2026-09-18-fix-supervisor-hosting-chain） — 固化项目根解析守卫与五键运行时自报、托管态三态判定、唯一托管启动/停止语义、supervisor_missing 告警、restart-daemon 与审批推送的消费方校验、install-hosting 端点
- 2026-11-04 host-wide-sigkill-hosting-chain-wipeout（spec/knowledge/_inbox/done/host-wide-sigkill-hosting-chain-wipeout.md） — 折叠宿主级全用户态 SIGKILL 事件实录：新增托管链宿主级暴露面规则（全链只住 tmux 无 systemd unit、宿主机级事件连坐死亡无人拉起、两变体与识别形态）与整链人工重建配方及五点验证判据
- 2026-11-04 memory-distill-agent-prompt-rules（spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md） — 折叠代码改动生效语义：daemon 代码改动重启才生效（单测通过≠生产生效、在飞期间不重启等空窗、「修复无效」先核对 daemon_started 与修复提交时间）
