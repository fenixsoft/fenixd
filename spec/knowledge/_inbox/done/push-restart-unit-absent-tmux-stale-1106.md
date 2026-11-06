# pushed 自动重启在 unit 缺席 + tmux 托管兜底形态下静默失效（陈旧进程缺口）

- **发现于**：add-spec-chinese-title 落地后用户报告规格列表无中文标题（2026-11-06 17:2x，merge 17:04 / pushed 17:23 / dashboard 进程 11-04 11:31 启动未重启）
- **现象**：`dashboard-push-restart` 内置 hook（pushed → `systemctl restart fenix-dashboard`）在本机按「unit 缺席静默跳过」分支执行（设计内，无 failure 审计），而本机 dashboard 实际是 **tmux 托管兜底形态**（session `fenix-dashboard:0`，start command `cd /root/fenixd && env -u CLAUDE_PID /usr/bin/python3 bin/fenix_dashboard.py --serve`；PPID 为 tmux server 非 PID 1）——重启动作找不到目标也不留痕，主树合入后的 Python 读侧改动对常驻实例永不可见。
- **诊断签名**：前端正常渲染（dist 实时读盘）但 `/api/specs` 等读侧字段缺失/恒旧；同数据在全新进程 `python3 -c` 直跑正常 → 运行进程陈旧。`ps -o lstart` 对比 merge 时间即可钉死。
- **修复动作（本次实测有效）**：`tmux respawn-window -k -t fenix-dashboard:0`（保留常驻形态与 `env -u CLAUDE_PID` 双保险启动命令），验证三件套：curl :8787 得 200、`/proc/<新pid>/environ` 无 CLAUDE_PID、API 新字段有值。
- **建议方向**：二选一收口——①（治本）补装/修复 `fenix-dashboard` systemd unit（11-05 systemd 承载环境三连缺陷修复的延续），让 pushed 重启 hook 回到设计路径；②（治标兜底）push-restart 动作在 unit 缺席分支增加 tmux 托管形态探测（占用 :8787 且父进程为 tmux server 的实例），respawn 对应窗口并留 skipped→executed 审计，消掉「静默跳过无人重启」的盲态。
- **关联**：dashboard-platform 域 dashboard-push-restart / dashboard-instance-lifecycle 两页；daemon-runtime 域 host-env-hazards（systemd 承载缺陷族）。
