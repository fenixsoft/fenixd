# 宿主机级全用户态 SIGKILL 事件击穿 fenixd 托管链（2026-11-04 实录）

## 现象

2026-11-04 00:53:55（本地）宿主机发生全用户态进程同时 SIGKILL：containerd/docker/dbus/udevd/journald/polkit 等全部 `code=killed, status=9/KILL`，Wi-Fi 被踢下线（wlo1 DEAUTH_LEAVING），journald 自身被杀重启。**内核与 systemd[1] 存活**（uptime 42 天未中断，非重启）。无 dmesg OOM 记录。

fenixd 侧形态：supervisor.log 无 exited 行、daemon 日志停在 00:53:08 正常周期内容、tmux server 连带全部会话消失——「托管链连坐死亡」的宿主机级变体（此前已知变体是单独杀 tmux server）。

## 关键对比：谁自愈了、谁没自愈

- **自愈**：`dsh-web.service` 等 systemd unit 服务，systemd 在 00:53:55 后自动重启（dsh web 00:53 即回到 :3080）。
- **未自愈**：fenixd 的 supervisor→daemon→dashboard 整条托管链只住在 tmux、无任何 systemd unit，无人拉起，停机约 7.75 小时（00:53 → 08:39 人工恢复）。

## 恢复过程（配方实测有效，2026-11-04 08:39）

1. supervisor：`tmux new-session -d -s "$(python3 .fenix/bin/fenix_session.py name "$(pwd)")" "cd $(pwd) && python3 .fenix/bin/fenixd_supervisor.py --project-root $(pwd) >> .fenix/logs/supervisor.log 2>&1"`（配方见 skills/fenix-setup/SKILL.md，会话名 fenixd-fenixd-f7f989）
2. dashboard：`env -u CLAUDE_PID tmux new-session -d -s fenix-dashboard "env -u CLAUDE_PID python3 /root/fenixd/.fenix/bin/fenix_dashboard.py --serve >> .fenix/logs/dashboard.log 2>&1"`
3. 验证：supervisor_runtime.json 刷新（新 pid + 新 script_hash）、daemon 全量扫描正常、curl :8787 得 200、真实 python 进程 environ 无 CLAUDE_PID、dist（11-03 23:20 构建）不落后于 src。

## 坑与教训

- **进程检测自命中**：`pgrep -f 'fenix_dashboard.py --serve'` 会命中执行检测的 claude shell 自身（命令行里含同字符串）且它带 CLAUDE_PID，假阳性判「CLAUDE_PID 剥离失败」。处方：`pgrep -af` 全列后按 `/proc/<pid>/exe` 是否 python 过滤再验 environ。
- fenixd 托管链**无 systemd unit 是停机 7.75h 的直接放大器**——宿主机级事件后只有 systemd 管的服务能自愈；「supervisor 看门狗」自身也在事件中死亡，看门狗没有看门狗的问题升级为宿主级。
- daemon 重启后恢复链正常工作：全量扫描 19 事件处理完毕，过期处置链在办件自动清除（chain-1793716373508 走既有孤儿接管）。
