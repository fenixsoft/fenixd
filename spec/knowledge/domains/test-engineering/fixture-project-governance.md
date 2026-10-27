# 验证夹具项目治理
<!-- knowledge: capability=fixture-project-governance rev=2 sources=spec/archive/2026-09-24-fix-fixture-project-alert-noise,spec/archive/2026-10-27-evo-add-verify-fixture-flag-guard -->

dashboard 全局监控中「验证夹具项目」的标记、读写与跨项目聚合过滤规则，以及验证场景自注册探针夹具的强制打标守卫，使夹具数据不污染人工告警与运维视图。

## 现行规则

- 标记权威单源：dashboard 全局配置 `~/.config/fenixd/dashboard.yaml` 的项目条目布尔字段 `fixture` 表示「该项目是验证夹具、其数据为验证噪音」。
- `Registry.discover()` 返回的每个项目 dict 均含 `fixture` 布尔键：显式配置 `fixture: true` 为真；未配置该键的项目与 `scan_dirs` 自动扫描发现的项目缺省为假。
- `Registry.add_project(path, name=None, fixture=False)` 支持带标记注册；对已存在的同路径条目再次注册一律跳过——不重复添加、也不静默改标记。
- `Registry.mark_fixture(path, fixture=True)` 按规范化路径定位配置条目写入/更新 `fixture` 键后写回，是显式更新既有条目标记的唯一途径；目标路径不在配置中时返回未变更提示且不抛异常。
- 验证场景在场景命令内自注册探针夹具项目（/tmp 扫描根外的临时路径）时 MUST 以 `fixture=True` 调用 `Registry.add_project`，实参显式 `fixture=False` 或缺省不传均为违规形态。夹具 seed/对照告警（severity 可为 critical）直写项目 `.fenix/admin_alerts.json`，不经摄取抑制（alert-noise-governance 5.1 只覆盖 AdminMonitor 捞取路径），缺省跨项目聚合分支的 `fixture` 过滤是唯一降噪面，未打标即直通人工告警聚合横幅与跨项目聚合。依据 ADR-163：标记收窄仅在缺省聚合分支，显式点名查询 `?project=` 零改动，打标对场景断言零影响。
- 出题端触达：场景出题提示词（agents/planner-plan.md「场景夹具注册规范」节）载明 MUST 规则，正例 `reg.add_project(SROOT, name=…, fixture=True)`，反例为显式 `fixture=False` 或缺省不传。
- 机械守卫：场景静态扫描（core/verify_engine/scenario_static_check.py 模式表）含 `unmarked_fixture_add_project` 模式——cli 场景 steps `command`/`stdin` 文本（str/list 双形态拼接后扫描）中的 `add_project(` 调用实参未含字面 `fixture=True` 即产出 judge 情报（只情报不拦截，随静态 findings 注入 judge 定向修复）；显式 `fixture=True` 不产出情报。打标判定只认关键字实参字面形态，变量传参等非字面写法会漏报（接受：情报定位是提示而非硬闸，漏报成本低于误报）。该模式与端口无关，serving 端口未知时仍执行。
- 守卫层级边界：夹具未打标的兜底不得通过翻转 `Registry.add_project` 的 `fixture` 缺省值实现——按路径条件翻转缺省属 ADR-163 禁止的路径推导，且拦不住显式 `fixture=False` 形态；检测责任固定在静态扫描情报层，Registry 缺省值与聚合分支过滤语义零改动。
- `fixture` 只标记来源，不改变项目的发现、监控、daemon 生命周期或可见性语义：夹具项目仍出现在项目列表与 `/api/projects/overview` 卡片中。
- `GET /api/alerts` 缺省（跨项目聚合）分支跳过夹具项目：夹具的未处理告警、已解决告警与摘要不出现在 `alerts`/`resolved`/`projects`，`total_unhandled` 不计入；`?project=<name>` 显式查询分支保留原行为，夹具项目的完整告警与处置记录照常返回。
- `GET /api/admin-activities` 缺省聚合分支同样跳过夹具项目；`?project=` 显式查询仍可返回其处置记录。
- 夹具供给脚本 `bin/fixture_scheduling_showcase.py --reset` 在重建基线之外，还须把夹具 `.fenix/admin_alerts.json` 复位为空基线（上一轮 seed 的告警/处置不跨验证轮次累积），并确保夹具以 `fixture: true` 登记进全局 registry；复位幂等，连续多次执行后状态一致。

## 溯源

- 2026-09-24 fix-fixture-project-alert-noise（spec/archive/2026-09-24-fix-fixture-project-alert-noise） — 新增 fixture 标记读写与透出、跨项目告警/运维记录聚合过滤、供给脚本复位告警基线并登记标记
- 2026-10-27 evo-add-verify-fixture-flag-guard（spec/archive/2026-10-27-evo-add-verify-fixture-flag-guard） — 新增「场景自注册探针夹具 MUST fixture=True」规则（selfheal-scratch-verify / arch-scratch-verify 两起事故：场景 fixture=False 使夹具 critical 对照告警直通人工告警横幅引发误排查）及双重触达：出题提示词正反示例固化 + 静态扫描 `unmarked_fixture_add_project` 情报模式；裁定守卫走静态扫描而非翻转 Registry 缺省（按路径翻转即 ADR-163 禁止的路径推导，且拦不住显式 False 形态）
