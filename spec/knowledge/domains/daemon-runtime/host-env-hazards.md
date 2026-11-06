<!-- knowledge: capability=host-env-hazards rev=4
     sources=spec/knowledge/_inbox/done/memory-distill-open-gaps-hazards.md,spec/changes/add-systemd-hosting,spec/knowledge/_inbox/done/systemd-hosted-daemon-path-missing-local-bin.md,spec/knowledge/_inbox/done/push-restart-unit-absent-tmux-stale-1106.md -->

# 宿主环境已知脆弱面

框架宿主机的环境级故障事实与临时绕过台账：每条绕过配置都是临时手段、附带回滚义务；环境级故障的告警形态与归因判读在此登记，避免被误归因到 provider 或框架自身。

## 规则

- 网关 DNS 失效的临时绕过（待 revert）：局域网网关 192.168.20.3 的 53 端口失效（ping 通但端口无响应），现以 systemd drop-in `/etc/systemd/network/10-netplan-enp42s0.network.d/99-admin-dns-priority.conf`（223.5.5.5 静态 DNS 提权、网关 DNS 降为末位 fallback）临时绕过。网关设备须人工检修（管理面凭据不在本机）；检修完成后删除该 drop-in 文件并执行 `resolvectl revert enp42s0` 还原 DHCP 原生配置。
- dns_probe_failed 判读：批量 dns_probe_failed（派发前连通预检失败、顺延本轮派发的 agent_runner 挂点信号）先查网关 53 端口连通性，不归因 provider 或框架调度；预检自身 fail-open（探测异常、无探测目标均照常派发），故该信号成批出现即指向宿主 DNS 链路本身。
- spawn 层失败三查（systemd 承载部署）：run 启动数秒内死亡（零 API 轮次）先查承载环境，不归因模型链或框架调度——① `/proc/<daemon_pid>/environ` 对表 `which claude`：PATH 缺 agent CLI 所在目录即 spawn FileNotFoundError；② run jsonl 只有 provider_marker/prompt 头等元数据、无任何 API 事件即 spawn 层死亡特征，归因文本里的「模型链/配置问题」措辞不可信；③ 错误文案含 `--dangerously-skip-permissions` 与 root 字样即子进程环境缺 `IS_SANDBOX=1`（运行时已由 claude adapter 恒注入兜底，见 [HarnessAdapter 进程边界协议与 claude 平移](../harness-integration/agent-harness-adapter.md)；承载层 env 文件缺键仍属环境劣化面，须补齐提升稿）。
- dashboard systemd unit 缺席、tmux 托管兜底常驻（待收口）：本机 `fenix-dashboard` unit 未安装，dashboard 常驻实例以 tmux 托管兜底形态运行——session `fenix-dashboard:0`，启动命令 `cd /root/fenixd && env -u CLAUDE_PID /usr/bin/python3 bin/fenix_dashboard.py --serve`，PPID 为 tmux server 非 PID 1。后果：pushed 自动重启 hook 的 unit 缺席分支每次静默跳过，主树 Python 读侧改动对常驻实例不生效（陈旧进程判读与重启配方见 [Dashboard 实例生命周期](../dashboard-platform/dashboard-instance-lifecycle.md)）；临时修复 `tmux respawn-window -k -t fenix-dashboard:0`。收口义务：补装 unit 让 pushed 重启回到设计路径，或 push-restart 动作补 tmux 托管形态探测与 skipped→executed 审计；收口后本条销账。
- 环境级故障面与托管链的交集：托管链承载于 systemd unit（supervisor、daemon、dashboard 异常死亡由 systemd 自动拉回），承载与自愈规则见 [systemd 承载的托管链](systemd-hosting.md)。

## 溯源

- 2026-11-04 memory-distill-open-gaps-hazards（spec/knowledge/_inbox/done/memory-distill-open-gaps-hazards.md） — 新建本页：网关 DNS 失效 drop-in 临时绕过（待 revert 与还原配方）、dns_probe_failed 批量信号的归因判读、与 supervisor-hosting 宿主级暴露面互链
- 2026-11-04 add-systemd-hosting（spec/changes/add-systemd-hosting） — 交集条目改指 systemd 承载：托管链获得进程外监督与自动拉回，「全链只住 tmux、宿主机级事件连坐死亡」的暴露面已随承载层迁移不再成立
- 2026-11-05 systemd-hosted-daemon-path-missing-local-bin（spec/knowledge/_inbox/done/systemd-hosted-daemon-path-missing-local-bin.md） — 新增 spawn 层失败三查判读（environ 对表 which claude、jsonl 零 API 事件=spawn 层死亡签名、skip-permissions+root 文案=IS_SANDBOX 缺席）
- 2026-11-06 push-restart-unit-absent-tmux-stale-1106（spec/knowledge/_inbox/done/push-restart-unit-absent-tmux-stale-1106.md） — 新增 dashboard unit 缺席、tmux 托管兜底常驻的环境实态登记（session 与启动命令、pushed 重启静默失效后果、respawn-window 临时修复、收口销账义务）
