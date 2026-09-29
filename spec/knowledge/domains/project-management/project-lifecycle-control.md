<!-- knowledge: capability=project-lifecycle-control rev=2 sources=spec/archive/2026-09-02-improve-dashboard-sections,spec/archive/2026-09-18-fix-supervisor-hosting-chain -->

# 项目生命周期控制

跨项目概览对单个项目的 daemon 启动/停止/重启、托管安装与软删除操作；daemon 启停一律经 supervisor 托管。

## 现行规则

- 启动：概览项目卡片「启动」操作由服务端复用该项目唯一 tmux session（`fenix_session.session_name(root)`，形如 `fenixd-<目录名>-<哈希6位>`），在 session 内拉起 supervisor 托管入口 `cd <root> && python3 .fenix/bin/fenixd_supervisor.py --project-root <root> >> .fenix/logs/supervisor.log 2>&1`（与 fenix-setup 一致）；tmux 仅是脱离终端的承载手段，daemon 必须由 supervisor 拉起。启动幂等：daemon 已运行时重复点击返回成功且不重复拉起。启动前校验项目根存在 `.fenix` 框架软链接与 `STATE.md`，缺失返回可读错误且不产生 daemon 进程。启动成功后概览在既有自动刷新周期内更新为「运行中」，项目托管态为 `managed`。
- 停止：按序执行——写 `.fenix/stop`（supervisor 见标记后不再拉起）→ 向该项目 daemon 进程发送 SIGTERM 触发既有优雅关闭 → 轮询等待 daemon 与 supervisor 双双退出至多约 30 秒 → 超时以 `tmux kill-session -t <session>` 强制终止并对残留进程补发 SIGKILL → 无论成败清除 `.fenix/stop`。不得只杀 daemon 遗留 supervisor 空转，也不得只杀 supervisor 遗留孤儿 daemon。SIGTERM/SIGKILL 只作用于入口快照中 cwd 或 `--project-root` 锚定到该项目根的进程，不重新扫描（防误杀并发拉起的进程）。停止幂等：daemon 未运行时不报错、不写 `.fenix/stop`。
- 软删除：「删除项目」语义为软删除——先停止该项目 daemon，再把规范化路径写入 `~/.config/fenixd/dashboard.yaml` 顶层 `ignored` 列表；此后该项目（无论显式注册还是自动发现）不再出现在监控列表与自动发现结果中，直至手工从 `ignored` 移除该路径。软删除 MUST NOT 删除或修改项目目录中的任何文件与数据；操作有二次确认，确认文案说明保留项目文件、仅停止监控、可通过编辑配置文件恢复。
- 管理端点：五个——`POST /api/projects/<name>/start`、`POST /api/projects/<name>/stop`、`POST /api/projects/<name>/restart`（写 `.fenix/restart_request` 走 supervisor 优雅重启）、`POST /api/projects/<name>/install-hosting`（把 `unmanaged` 项目转入 supervisor 托管：停止裸 daemon → 经 supervisor 重启；对 `stopped` 项目等价于启动）、`DELETE /api/projects/<name>`（软删除）。端点按项目名解析到当前发现结果中的路径；项目不存在或目录不存在（`exists=False`）返回 400 与错误信息。成功返回 JSON（含 `ok`、可选 `session`/`error` 字段）并经 SSE Hub 广播 `refresh`，概览在自动刷新周期内跟随更新；环境异常（tmux 不可用等）返回错误对象，HTTP 状态非 500。
- 重启前置托管校验：对 `unmanaged` 项目调用 restart 返回 `ok:false` 与含「未受 supervisor 托管」的可读错误，不得当作成功重启（文件信号无人消费）；`stopped` 项目维持「daemon 未运行」语义。install-hosting 与 stop 不得并发互踩（一路的 SIGKILL 兜底不得误杀另一路刚拉起的 supervisor）。
- 托管态三态：项目 daemon 状态区分 `managed`（有活跃 supervisor，文件信号有消费方）/ `unmanaged`（有裸 daemon 无 supervisor）/ `stopped`（两者皆无）；判定异常按 `stopped` 兜底，不抛异常。

## 溯源

- [2026-09-02 improve-dashboard-sections](spec/archive/2026-09-02-improve-dashboard-sections/) — 新增本能力：概览卡片启动/停止 daemon（当时 tmux 直启 `fenixd.py`、SIGINT 优雅关闭约 5 秒）、软删除（停 daemon + 写 `ignored`）与三个管理端点（start/stop/delete）
- [2026-09-18 fix-supervisor-hosting-chain](spec/archive/2026-09-18-fix-supervisor-hosting-chain/) — 启动改为 session 内拉起 supervisor 托管入口；停止改为「写 `.fenix/stop` + SIGTERM + 约 30 秒双进程收口 + 兜底 SIGKILL」；端点扩为五个（新增 restart、install-hosting）；unmanaged 项目 restart 前置拒绝
