# memory 存量蒸馏：跨框架危险面与开放缺口（2026-11-04 复核仍开放）

## 背景

auto-memory 存量中**结构性风险与未闭合缺口**类知识——事故已处置但机制缺口仍在，
或属设计内脆弱面。均已对照 2026-11-04 代码复核确认仍开放。适合折叠进
daemon-runtime / worktree-vc / knowledge-atlas 域的相应能力页（或新增「已知脆弱面」
类页）。

## 结论（当前事实）

### tmux server 单例连坐托管链（架构缺口，仍未修）

supervisor 在 tmux session 里跑，而 **tmux server 是所有 session 共享单例**；
supervisor/daemon 无 SIGHUP handler、Popen 无 setsid、同 pane 前台进程组——
kill tmux server（或 server 级死亡）→ 整条托管链收 SIGHUP 静默死，零日志
（supervisor.log 停在 `daemon started`，fenixd.log 停正常内容）；supervisor 陪着死，
`while True: start_daemon()` 无机会执行。09-19/09-22 两次复发；**11-04 宿主机级
变体：全用户态 SIGKILL（内核/systemd 存活），有 systemd unit 的服务自愈而 fenixd
托管链无 unit 全灭 7.75h**。恢复=fenix-setup 配方重起 supervisor+dashboard（实测
有效）。处方：①运维绝不动 tmux server / kill-server；重启 dashboard 只 kill 其
pid 或 `tmux kill-session -t fenix-dashboard`；②「daemon 静默消失、supervisor.log
无 exited 行」先 `ps -o ppid= -p <supervisor_pid>` 反查宿主；③socket 文件已删但
server 进程仍活（fd 在）的孤儿 tmux server 极易被误判为可清理残留；④框架侧
SIGHUP handler + daemon setsid **待立项**（2026-11-04 grep 确认 bin/fenixd_supervisor.py
与 agent_runner 均无 SIGHUP/start_new_session）。

### spec 目录自动提交 hook 的夹带风险（结构性）

fenix-new 等入口的「git add spec 目录即自动提交」hook 在主树堆未提交决策时会把
同文件热修顺带卷入上游提交，与下游车道（merge-back）撞车（09-23 code-fix 第 3 批
合回失败实证：主树热修被无关 SPEC 的 spec 目录自动提交卷入）。无守卫，靠
hunk 手术纪律规避（见 ops 手册条目）。

### 蒸馏「放弃产出」的破坏性清理半径

validate_knowledge 修正轮耗尽 → `git restore spec/knowledge/` + 清理未跟踪新增——
对脏工作区会清掉用户 untracked 文件（10-01 实证：恢复中的 ADR md 数分钟内被在飞
蒸馏轮再清一次）。处方：恢复工作完成后第一动作 commit 入库（committed 不在
restore/clean 半径）；恢复与提交之间不留窗口。

### merge-back tracked-modified 自愈缺口

untracked 冲突与 stash pop UU 均有框架自愈（`_backup_conflicting_untracked` /
checkout -f HEAD 自愈），但 **tracked-modified 冲突的 self-heal 不覆盖**——字节级
与分支相同时本可无损 checkout 分支版的自愈未做；spec 车道已由 wip-overlap gate
旁路（escalate→`wip_gate_blocked=True`），code-fix 车道有 defer 队列兜底，
跨会话并行写主树仍是合回失败的第一大来源。

### 冻结 error 被 daemon 重启静默清空（待取证）

连带观测（09-18）：冻结的 error 在 daemon 重启后被清空（frozen 仍 True、
error→null）——写入方疑似用 NullLogger 的 StateMachine 实例（dashboard
admin_actions 多处 `StateMachine(..., None)`）。冻结 error 不应被任何链路清空，
尚未独立取证定位写入方。

### 宿主 DNS 网关失效的临时绕过（待 revert）

网关 192.168.20.3 的 53 端口自 2026-10-28 失效；Admin drop-in
`/etc/systemd/network/10-netplan-enp42s0.network.d/99-admin-dns-priority.conf`
（223.5.5.5 提权）为**临时绕过**，网关设备须人工检修（管理面凭据不在本机）；
修好后删该文件并 `resolvectl revert enp42s0` 还原 DHCP 原生配置。批量
dns_probe_failed 类告警先查网关 53 端口。

### 测试夹具与「归档清单命中形态」断言

凡断言「归档清单命中形态」（如 command_center 归档剔除），夹具的 spec 段必须取
真实归档清单里存在的名字——伪造名字会 Scenario 假绿、端到端才撞墙（11-02 蒸馏
观测盲区实证；aggregate_org 的 knowledge-distiller 豁免已于 11-01 收编）。
蒸馏产物长跑批需心跳写点（无心跳 1800s 判 stale 被提前移 archive，终态行写空）。

## 证据

- 源记忆：fenixd-supervisor-ops（tmux 连坐段含 11-04 变体）、
  fenixd-codefix-batch3-samefeature-conflict-and-lock-wedge（hook 夹带段）、
  fenixd-autostash-worktree-wipe-incident-and-recovery（10-01 复发段）、
  fenixd-mergeback-stash-deadlock-family（仍开放段）、fenixd-freeze-family
  （连带观测段）、fenixd-gateway-dns-dead-admin-dropin、
  fenixd-distill-observation-archive-list-blindspot。
- 2026-11-04 复核：`grep -rn "SIGHUP\|start_new_session" bin/fenixd_supervisor.py
  core/agent_runner/` 零命中（缺口仍开放）；`core/dashboard/data/command_center.py:62-67`
  knowledge-distiller 已收编（该子缺口已闭合）。
