# ADR-115：daemon 托管链——supervisor 父进程拓扑与三态托管态

date: 2026-09-18
status: accepted

## Context

文档声称 daemon 由 supervisor 托管，实现侧（setup 与 dashboard）仍用 tmux 直启 daemon。软链解析缺陷（`Path(__file__).resolve()` 跟随 `.fenix/bin` 软链回主树）使任何子项目手工补启的 supervisor 都绑定主树：拉起的第二个 daemon 被 flock 拒退后无限空转，并逐轮吞掉主树真正的 restart_request。`is_running` 布尔口径把「有 daemon 但无人托管」与「正常运行」压成同一状态，断链只能靠十分钟后一条 restart_failed 告警间接察觉；且既有告警建议文案恰好引导用户执行那个投毒操作。

## Decision

- 托管链拓扑固定为：supervisor 是 daemon 的父进程，负责退出感知与拉起；tmux 只承担「脱离终端」的承载手段，不再直接承载 daemon。启停一律经 supervisor（`start_daemon`/`stop_daemon` 单一实现点，dashboard 端点复用同一对函数，不出现第三套启停）。
- 计划性重启走 restart_request 排水；「停止」走 `.fenix/stop` + SIGTERM 快速停机语义，不复用排水（1800s 排水对停止操作不可接受）。
- 项目根解析禁用 `__file__` 派生（软链跟随会静默错绑项目）：显式参数 > 环境变量 > cwd 兜底，解析后校验 `.fenix/` 存在。
- 托管态三态 `managed` / `unmanaged` / `stopped` 是一等可观测状态，判定基于 /proc 扫描（不引入 pidfile）；`unmanaged`（有 daemon 无 supervisor）必须可见并升级告警。
- 需要「信号必被消费」保证的写操作前置校验 `hosting_state == managed`（取代进程存活布尔）：消费者不存在时写信号必须失败而非成功——细化 ADR-100 的写前探活口径。
- supervisor 陈旧（script_hash 与磁盘不一致）只检测告警，升级靠显式「安装托管」操作；不做自动 re-exec（双 daemon 风险高于排水截断风险）。
- 本裁定取代 ADR-031 中「daemon 生命周期以 tmux 会话为唯一载体」的启停拓扑；ADR-031 的忽略列表软删除裁定不受影响。

## Consequences

- daemon 崩溃可被自动拉起，断链在下一轮检测即升级为告警而非静默；「照告警建议操作反而投毒」的路径被移除。
- supervisor 自身成为单点，其崩溃使项目转 `unmanaged`，由三态可见性兜底；外部 init 系统仍在范围外。
- 旧启动命令（无参数）依赖 cwd 在项目根；跨目录调用被显式拒绝启动——新增显式失败，非行为回归。
