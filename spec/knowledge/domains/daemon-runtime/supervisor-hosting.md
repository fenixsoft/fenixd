<!-- knowledge: capability=supervisor-hosting rev=6 sources=spec/archive/2026-09-18-fix-supervisor-hosting-chain,spec/knowledge/_inbox/done/host-wide-sigkill-hosting-chain-wipeout.md,spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md,spec/knowledge/_inbox/done/memory-distill-open-gaps-hazards.md,spec/knowledge/_inbox/done/memory-distill-ops-runbook.md,spec/changes/add-systemd-hosting -->

# supervisor 托管链

daemon 由 supervisor 托管运行，systemd unit 是托管链的承载层（unit 形态、重启策略与拉回规则见 [systemd 承载的托管链](systemd-hosting.md)）；信号消费、优雅重启与停止语义都锚定 supervisor 的存在性。

## 现行规则

- 目标项目根解析优先级：`--project-root` 参数 > `FENIX_PROJECT_ROOT` 环境变量 > `Path.cwd()`；禁止由 `Path(__file__).resolve()` 派生（该路径会跟随项目内 `.fenix/bin` 软链回到框架主树，绑错目标）。解析出的项目根下必须存在 `.fenix/`，缺失时打印可读错误并以非零码退出，不启动任何 daemon 进程。
- supervisor 每次启动时原子覆写 `.fenix/supervisor_runtime.json`（临时文件 + rename），五键齐备：`sigkill_wait`、`started_at`、`pid`、`script_hash`（本脚本内容 sha256）、`project_root`；写入失败不中断 supervisor 主流程。
- 托管态三态：`hosting_state(root)` 返回 `managed`（supervisor 在跑）/ `unmanaged`（有 daemon 进程但无 supervisor）/ `stopped`（两者皆无）；`supervisor_running(root)` 扫描 `/proc`（`cmdline` 含 `fenixd_supervisor` 且 `cwd` 或 `--project-root` 解析后等于项目根），`/proc` 不可读时返回 False 不抛异常。daemon 在跑判定 `is_running(root)` 同为 `/proc` 进程检测，`/proc` 不可用时判未运行（fail-closed——宁可误判 stopped 也不误判 running，误判 running 会让启动幂等门吞掉启动、停止谎报成功）。
- 唯一托管启动路径：`start_daemon(root)` 确保目标项目存在 `fenixd-<项目名>.service` unit（缺失时生成安装）并 `systemctl enable --now` 启动，daemon 必须是 supervisor 的子进程，不以 `python3 .fenix/fenixd.py` 直接作为启动命令；`systemctl` 不可用时返回含「需要 systemd」指引的可读错误且不产生任何进程。启动前校验项目根存在 `.fenix` 与 `.fenix/STATE.md`，缺失返回可读错误且不产生进程、不写 unit。操作幂等：`is_running(root)` 为真直接返回 `already=True`；unit 已启用且服务活跃时重复调用不重建 unit、不重启服务。
- 托管停止语义：`stop_daemon(root)` 按 unit 接管状态双轨执行。unit 已安装：① 写 `.fenix/stop`（使 supervisor 不在 daemon 退出后重新拉起）② `systemctl stop --no-block`（不同步等待，systemctl stop 最坏等待为排水上界量级）③ 轮询等待 daemon 与 supervisor 双双退出（上限约 30 秒，保留快速停机契约与 dashboard stop 端点 30 秒预算）④ 超时对入口快照中仍存活的残留进程补发 SIGKILL。unit 未安装但进程在跑（managed-but-no-unit 态，如迁移期或 unit 被手工卸载）：保留既有直接信号链——写 `.fenix/stop` → 经 `/proc` 定位向该项目 daemon 发 SIGTERM → 轮询等待（上限约 30 秒）→ 超时补 SIGKILL，不因 `systemctl stop` 对未启动 unit 是 no-op 而谎报成功。两条轨的 SIGTERM/SIGKILL 只作用于入口快照中 cwd 或 `--project-root` 锚定到该项目根的进程集合，不重新扫描（防误杀并发 start 新拉起的进程）；不得只杀 daemon 遗留 supervisor 空转，也不得只杀 supervisor 遗留孤儿 daemon。两轨均无论成败清除 `.fenix/stop`；停止未运行项目幂等返回成功且不写 `.fenix/stop`。
- 信号只写给有消费者的项目：`restart-daemon` hook 写 `.fenix/restart_request` 前校验该项目存在活跃 supervisor，不存在时返回失败并触发既有告警链，detail 说明「本项目无 supervisor，重启请求不会被消费」；审批推送写 `.fenix/approve_push_request.json` 前校验托管态为 `managed`——`unmanaged` 返回 409 并附「安装托管」指引且不写信号文件，`stopped` 维持「daemon 未运行，请先启动 daemon」文案与行为。
- daemon 启动自检把 supervisor 存在性作为独立判定项（不受 `admin.shutdown_drain_seconds` 取值影响，drain=0 仍检查存在性、仅跳过 drain 一致性比对）；判定为缺失时落 WARNING 并经 AdminStore 写一条 `severity: major`、`signal_type: supervisor_missing` 的 escalation 告警，描述说明「未受 supervisor 托管，restart_request 不会被消费」，同一未处置告警去重不堆积。
- `restart_failed` 升级建议按托管态分支：`unmanaged`/`stopped` 时指引经 Dashboard 项目页「安装 supervisor 托管」或 `/fenix-setup` 恢复托管，不得出现「手动启动 `.fenix/bin/fenixd_supervisor.py`」这类会绑定框架主树的直接命令；`managed` 时指引检查 supervisor 进程与 daemon 排水状态。
- 安装托管操作：Dashboard `POST /api/projects/<name>/install-hosting` 对 `unmanaged` 项目执行「停止裸 daemon → 经 supervisor 启动」转入 `managed`，对 `managed` 项目幂等返回不重启，对 `stopped` 项目等价于启动；必须复用 `stop_daemon`/`start_daemon`（底层为 systemctl 双轨语义），不得绕过其直接操作进程或 unit；成功时广播 SSE `refresh`。
- 整链人工重建经 systemctl 承载语义执行：项目托管链重新 `start_daemon`（或对既有 unit `systemctl enable --now`）拉起，dashboard 经 `fenix-dashboard.service` unit 拉起，配方以 `skills/fenix-setup/SKILL.md`、`skills/fenix-dashboard/SKILL.md` 为准（含 tmux 承载存量部署的一次性搬迁脚本与回滚配方）。重建完成后按判据验证：`.fenix/supervisor_runtime.json` 已刷新（新 pid 与新 script_hash）、daemon 全量扫描正常消化积压事件、dashboard 端口 curl 返回 200、真实 python 进程的 environ 无 `CLAUDE_PID`、dashboard dist 构建产物不落后于 src。
- 代码改动生效语义：daemon 进程的代码改动须经重启才生效（模块启动时加载），单测通过不等于生产生效；在飞 run 期间不重启，等空窗再重启。诊断「修复无效」先核对 `.fenix/daemon_started`（daemon 启动时刻锚点）与修复提交时间的先后，再归因代码。
- supervisor_fused 解熔断前置核验：解熔断（重置熔断态并重启）前先 `python3 -m compileall` 验证主树无瞬时坏文件——restart 撞上瞬时坏文件即熔断，提交版本可能无辜零 diff；不核验直接解熔断会在坏文件仍在场时立刻复熔断。熔断告警文案所称「新代码」不指示真实死因，以 compileall 结果为准。熔断以专用码 75 退出、不被 systemd 拉回，恢复一律人工。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：daemon 由 tmux/supervisor 托管：重启走 env -u CLAUDE_PID 协议，杀 tmux server 会连带杀 daemon，须重建托管链
- 2026-09-18 fix-supervisor-hosting-chain（spec/archive/2026-09-18-fix-supervisor-hosting-chain） — 固化项目根解析守卫与五键运行时自报、托管态三态判定、唯一托管启动/停止语义、supervisor_missing 告警、restart-daemon 与审批推送的消费方校验、install-hosting 端点
- 2026-11-04 host-wide-sigkill-hosting-chain-wipeout（spec/knowledge/_inbox/done/host-wide-sigkill-hosting-chain-wipeout.md） — 折叠宿主级全用户态 SIGKILL 事件实录：新增托管链宿主级暴露面规则（全链只住 tmux 无 systemd unit、宿主机级事件连坐死亡无人拉起、两变体与识别形态）与整链人工重建配方及五点验证判据
- 2026-11-04 memory-distill-agent-prompt-rules（spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md） — 折叠代码改动生效语义：daemon 代码改动重启才生效（单测通过≠生产生效、在飞期间不重启等空窗、「修复无效」先核对 daemon_started 与修复提交时间）
- 2026-11-04 memory-distill-open-gaps-hazards（spec/knowledge/_inbox/done/memory-distill-open-gaps-hazards.md） — 折叠 tmux server 单例连坐机制与运维纪律：共享单例/无 SIGHUP handler/未脱离进程组的连坐根因、零日志识别形态、kill-server 禁令与孤儿 server 误清风险；SIGHUP+setsid 保护缺口仍开放
- 2026-11-04 memory-distill-ops-runbook（spec/knowledge/_inbox/done/memory-distill-ops-runbook.md） — 折叠 supervisor_fused 解熔断前置核验配方（解熔断前 compileall 验证主树无瞬时坏文件，告警文案「新代码」不指示死因）
- 2026-11-04 add-systemd-hosting（spec/changes/add-systemd-hosting） — 承载层迁移（BREAKING）：唯一托管启动路径改 unit 安装 + `systemctl enable --now`（tmux session 创建退役、systemctl 不可用拒绝不回退）、托管停止改 systemctl 双轨（tmux kill-session 兜底退役）；已随本 SPEC 废除：「托管链只住 tmux 无 unit、宿主机级事件连坐死亡无人拉起」暴露面、「tmux server 单例连坐机制」与 tmux 运维纪律（kill-server 禁令/孤儿 server 变体）、「tmux 会话整链人工重建配方」（重建改 systemctl 语义）；is_running `/proc` 不可用改判 stopped（fail-closed）；承载层细节由 systemd-hosting 能力页承载
