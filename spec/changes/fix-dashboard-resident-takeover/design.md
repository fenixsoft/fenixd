## Context

`serve()`（`core/dashboard/server.py:444`）的端口独占语义在占用者为旧 `--serve` 实例时无差别 SIGTERM 接管（473-493 行）。2026-09-29 事故：agent run 内自测实例接管 8787，杀掉 tmux 常驻实例（pane 进程死 → 单窗口会话消失、SIGTERM 无输出 → dashboard.log 静默）；接管者装配 `CLAUDE_PID` watchdog + `PR_SET_PDEATHSIG`，run 结束即自杀，用户可访问实例随机静默死亡。

同文件已有「显式长驻」判据 `_is_tmux_hosted(ppid)`（320 行）：读 `/proc/<ppid>/comm` 恰为 `tmux: server`，回退 cmdline 时 argv[0] basename 判定；读取失败返回 False（fail-safe 偏向防泄漏）。该判据的防误判纪律（不用 `TMUX` 环境变量、不用 argv 子串）已在 2026-09-26-fix-dashboard-watchdog-misfire 固化进 spec。

## Goals

- tmux 常驻 dashboard 不可被任何 agent 自测实例杀死
- agent 自测在 8787 被常驻占用时得到明确、可操作的失败（换端口重试），而非静默杀常驻
- 非 tmux 旧实例的既有接管语义零变化

## Decisions

1. **复用 `_is_tmux_hosted` 判据而非新写判定**：同源纪律（comm 精确匹配 → cmdline argv[0] 回退 → 读取失败 False），避免两套判据漂移。新增一小步辅助函数 `_parent_is_tmux_server(pid)`：读 `/proc/<pid>/stat` 取占用者 ppid（解析纪律同 `_proc_starttime`（server.py:305：`data.rindex(")")` 后切片取字段，注意是 `rindex` 而非 `rpartition`）），再调 `_is_tmux_hosted(ppid)`。
2. **判定时机**：身份复核（starttime 锚定）通过后、`os.kill(SIGTERM)` 前执行。父进程读取失败（占用者已成孤儿、ppid 变 1 等）→ 视为非 tmux 承载，走既有接管——孤儿化的 dashboard 实例已无 tmux 会话可依归，接管它不破坏任何常驻形态；这与「读取失败按防泄漏处理」方向相反，但场景语义不同：`_is_tmux_hosted` 读不到父进程时该实例自身要装配 watchdog（防泄漏优先），而接管路径读不到时放行接管（不误伤常驻优先，孤儿实例本就可收割）。
3. **拒绝方式为报错退出而非自动换端口**：serve() 已收敛「仅对最终确定的单一端口做占用检测（不再自动上探）」；自动上探会让场景 URL 写死 8787 的验证流量打到常驻实例而非被测实例。错误信息含 PID + 指引，agent 自适应换端口。
4. **不扩大 watchdog/`_bind_parent_lifecycle` 改动面**：两者语义已在 2026-09-26 SPEC 固化且行为正确，本次只堵接管这一个洞。

## Risks

- **接管语义收窄的回归**：经评审实测（2026-09-30），serve() 接管分支（EADDRINUSE 路径）当前**无任何既有单测**——tests/ 下不存在 `test_dashboard_server*`，test_dashboard_*.py 中亦无 EADDRINUSE/占用者类用例，故不存在旧用例翻转风险；tasks 2.1-2.3 三形态用例为净新增，落 tests/test_dashboard_orphan_guard.py（`_is_tmux_hosted` 判据用例已在该文件，其 fake /proc 手法——monkeypatch `server_mod.Path`——可复用）。`tests/test_verify_command_port.py` 的端口用例走真实绑定、不构造 tmux 常驻占用者，不受收窄影响。
- **ppid 读取竞态**：占用者在判定与 kill 之间退出由既有 starttime 复核覆盖；判定本身读的是快照时刻的 ppid，无新竞态窗口。
- **容器/CI 无 /proc**：`_parent_is_tmux_server` 读取失败返回 False → 走既有接管，CI 行为不变。

## Migration

无迁移。tmux 常驻实例无感（行为不变）；agent 自测脚本若依赖「无脑顶掉 8787」，需改为 `--port` 指定空闲端口（错误信息已指引）。
