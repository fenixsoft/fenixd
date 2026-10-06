<!-- knowledge: capability=fixture-project-governance rev=1 sources=spec/archive/2026-09-24-fix-fixture-project-alert-noise -->

# 验证夹具项目治理

dashboard 全局监控中「验证夹具项目」的标记、读写与跨项目聚合过滤规则，使夹具数据不污染全局告警与运维视图。

## 现行规则

- 标记权威单源：dashboard 全局配置 `~/.config/fenixd/dashboard.yaml` 的项目条目布尔字段 `fixture` 表示「该项目是验证夹具、其数据为验证噪音」。
- `Registry.discover()` 返回的每个项目 dict 均含 `fixture` 布尔键：显式配置 `fixture: true` 为真；未配置该键的项目与 `scan_dirs` 自动扫描发现的项目缺省为假。
- `Registry.add_project(path, name=None, fixture=False)` 支持带标记注册；对已存在的同路径条目再次注册一律跳过——不重复添加、也不静默改标记。
- `Registry.mark_fixture(path, fixture=True)` 按规范化路径定位配置条目写入/更新 `fixture` 键后写回，是显式更新既有条目标记的唯一途径；目标路径不在配置中时返回未变更提示且不抛异常。
- 验证场景在场景命令内自注册探针夹具项目（/tmp 扫描根外的临时路径）时 MUST 以 `fixture=True` 调用 `Registry.add_project`：夹具 seed/对照告警（severity 可为 critical）直写项目 `.fenix/admin_alerts.json`，不经摄取抑制（alert-noise-governance 5.1 只覆盖 AdminMonitor 捞取路径），缺省跨项目聚合分支的 `fixture` 过滤是唯一降噪面。依据 ADR-163：标记收窄仅在缺省聚合分支，显式点名查询 `?project=` 零改动，打标对场景断言零影响。反例：add-alert-self-heal-marking 的 selfheal-scratch-verify 与 add-alerts-archive-and-overview-cache 的 arch-scratch-verify（`fixture=False` 使夹具 critical 对照告警直通人工告警聚合横幅，引发用户误排查）。
- `fixture` 只标记来源，不改变项目的发现、监控、daemon 生命周期或可见性语义：夹具项目仍出现在项目列表与 `/api/projects/overview` 卡片中。
- `GET /api/alerts` 缺省（跨项目聚合）分支跳过夹具项目：夹具的未处理告警、已解决告警与摘要不出现在 `alerts`/`resolved`/`projects`，`total_unhandled` 不计入；`?project=<name>` 显式查询分支保留原行为，夹具项目的完整告警与处置记录照常返回。
- `GET /api/admin-activities` 缺省聚合分支同样跳过夹具项目；`?project=` 显式查询仍可返回其处置记录。
- 夹具供给脚本 `bin/fixture_scheduling_showcase.py --reset` 在重建基线之外，还须把夹具 `.fenix/admin_alerts.json` 复位为空基线（上一轮 seed 的告警/处置不跨验证轮次累积），并确保夹具以 `fixture: true` 登记进全局 registry；复位幂等，连续多次执行后状态一致。

## 溯源

- 2026-09-24 fix-fixture-project-alert-noise（spec/archive/2026-09-24-fix-fixture-project-alert-noise） — 新增 fixture 标记读写与透出、跨项目告警/运维记录聚合过滤、供给脚本复位告警基线并登记标记
