<!-- knowledge: capability=daemon-health rev=3 sources=spec/archive/2026-09-02-add-multi-project-monitoring,spec/archive/2026-09-18-fix-supervisor-hosting-chain,spec/changes/add-systemd-hosting -->

# daemon 健康检测

数据聚合层为每个被监控项目判定 fenixd daemon 是否在运行，并经项目列表与概览 API 暴露结果。

## 现行规则

- `daemon_health(project_root)` 返回 `"running"`/`"stopped"`，以 `/proc` 进程检测判定（复用 `fenix_session.is_running` 单源）：匹配 `cwd` 等于该项目根、且 `cmdline` 含 `.fenix/fenixd.py` 或 `fenixd_supervisor` 的活跃进程——覆盖 supervisor 托管与未经托管的裸 daemon 形态。
- `/proc` 不可用时判 `"stopped"`（fail-closed）：无 `/proc` 环境无从判定进程存在性，宁可误判 stopped 也不误判 running；subprocess 调用异常或均未命中同样返回 `"stopped"`，不抛异常。
- 检测结果带短 TTL 缓存（默认约 5s），避免高频轮询重复 spawn 子进程。
- `/api/projects` 与 `/api/overview` 返回的每个项目对象含 `daemon` 字段（`"running"`/`"stopped"`）与 `hosting` 字段（`"managed"`/`"unmanaged"`/`"stopped"`，三态判定语义见 [supervisor-hosting](supervisor-hosting.md)）；健康检测或数据源异常时两字段均以 `"stopped"` 兜底返回，不使请求失败或 500。`hosting` 字段把「进程在跑但无人托管」与「未运行」区分开。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：daemon 存活按进程判定而非端口探测；健康状态经周期 refresh 心跳自动推送 dashboard
- 2026-09-02 add-multi-project-monitoring（spec/archive/2026-09-02-add-multi-project-monitoring） — 新增每项目 daemon 健康检测函数与 `/api/projects`、`/api/overview` 的 `daemon` 字段暴露（tmux session 命中口径）
- 2026-09-18 fix-supervisor-hosting-chain（spec/archive/2026-09-18-fix-supervisor-hosting-chain） — 判定主源改为 `/proc` 进程检测（裸 daemon 不再漏判为未运行），tmux session 降为回退
- 2026-11-04 add-systemd-hosting（spec/changes/add-systemd-hosting） — tmux session 回退判定随承载层迁移退役：`/proc` 不可用改判 `"stopped"`（fail-closed），判定收敛到 `is_running` `/proc` 进程检测单源
