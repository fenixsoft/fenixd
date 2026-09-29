<!-- knowledge: capability=project-discovery rev=2 sources=spec/archive/2026-09-02-add-multi-project-monitoring,spec/archive/2026-09-18-fix-dashboard-fault-isolation -->

# 多项目自动发现

Dashboard 以自动扫描为主、显式注册为辅发现被监控项目，支持从监控列表移除已注册项目；发现层对不可读路径逐点容错，单点故障不拖垮整体聚合。

## 现行规则

- 自动扫描判据：`Registry.discover()` 在 `~/.config/fenixd/dashboard.yaml` 未配置 `scan_dirs`（或为空）时，默认以用户主目录 `~` 为唯一扫描根，遍历其一级子目录，仅当子目录下存在 `.fenix/STATE.md` 才识别为 Fenixd 项目并纳入监控列表；显式配置 `scan_dirs` 时以其为扫描根（覆盖默认）。显式 `projects` 中的项目始终出现在监控列表（扫描未命中或目录不存在时标记 `exists=False`）；扫描结果与显式注册按规范化路径去重。
- 逐目录异常隔离：对每个子目录的类型判断（`is_dir()`）与 `.fenix/STATE.md` 存在性探测（`is_file()`）必须异常隔离——捕获 `OSError`（含 EIO）后跳过该子目录（不计入监控列表、不改动显式 `projects`），继续处理其余子目录，最终正常返回发现结果而非抛异常。pathlib 存在性探测只吞 ENOENT/ENOTDIR/EBADF/ELOOP，EIO 直接上抛，隔离不得依赖 `is_file()` 的默认吞异常行为。扫描根自身不可读（`iterdir()` 抛 `OSError`）时跳过该扫描根，其余扫描根与显式注册照常返回。
- 跳过可观测：跳过不可读子目录时输出一条 WARNING 日志（含被跳过路径与错误原因），不使请求失败；UI 层对此静默——`/api/projects` 与 `/api/overview` 不出现该路径的项目卡片，也不追加告警条目。
- 忽略列表前置：`ignored` 过滤先于目录类型判断与存在性探测——命中 `ignored` 的路径不执行任何可能抛 `OSError` 的文件系统探测。路径匹配基于规范化路径（与写侧 `_norm` 同一规范化），对尚不可读的路径也能完成匹配与过滤；`add_ignored(path)` 不因目标路径不可读而拒绝写入。软删除（写入 `ignored`）是用户面对不可读/故障目录的逃生通道。
- 显式注册为辅：`add_project(path)` 把项目写入配置 `projects`（规范化路径去重，已存在跳过），供 `bin/fenix_dashboard.py --add-project` 与 /fenix-dashboard skill 调用；扫描范围（默认 `~` 或 `scan_dirs`）外的路径经显式注册纳入监控。
- 移除已注册项目：`remove_project(path)` 把显式注册的项目从配置 `projects` 移除（规范化路径匹配）并写回；未显式注册（含仅由扫描自动发现）的路径返回未变更提示且不报错；`--remove-project <path>` 子命令承载该能力。仅扫描发现的项目不在配置中，无法被移除，仍会因扫描出现在监控列表。
- 发现缓存语义：监控列表经 `DashboardHTTPServer.projects()` 的 TTL 缓存（10 秒）对外提供，「TTL 判断→discover→写回」序列持锁互斥。改变发现结果的写操作（删除/注册项目等）完成后必须调用 `invalidate_projects_cache()`，否则已删项目在概览页「消失→马上重现→约 10 秒后再消失」。`discover()` 抛异常时保留上次成功结果（从未成功过则为空列表）并记录错误，TTL 时间戳照常推进，不使每个请求都重试重炸。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：watcher 周期扫描注册表发现项目并接入监控；移除后缓存须失效防写后读盲区
- [2026-09-02 add-multi-project-monitoring](spec/archive/2026-09-02-add-multi-project-monitoring/) — 确立自动扫描为主（默认扫描主目录一级子目录，当时判据为 STATE.md+config.yaml 双文件）、显式注册为辅、`--remove-project` 移除与去重
- [2026-09-18 fix-dashboard-fault-isolation](spec/archive/2026-09-18-fix-dashboard-fault-isolation/) — 识别判据收窄为仅 `.fenix/STATE.md`；逐子目录/逐扫描根异常隔离；`ignored` 过滤前置于探测（软删除对不可读路径生效）；跳过落 WARNING、UI 静默；发现缓存异常保留上次结果不逐请求重炸
