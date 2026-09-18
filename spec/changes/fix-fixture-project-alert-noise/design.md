## Context

`scheduling-showcase` 是 fenixd 自身验证链的**夹具被管项目**（8 个特定状态 SPEC，29 个 api/web/cli 场景依赖），早已登记进 dashboard 全局监控配置 `~/.config/fenixd/dashboard.yaml`。多个 SPEC 的 seed 场景会经真实 `AdminStore.append` 往夹具 `.fenix/admin_alerts.json` 写入**真实形态**的升级告警/处置记录（`handled=false`、`major`/`critical`），供 api/web 场景经被测 dashboard 消费（如验证「告警横幅能展示 mergeback_wip_overlap」）。

这些 seed 记录是**验证数据**，本不该进入用户的人工告警视野。但当前：

1. 夹具 `--reset` 只复位 `STATE.md`/`config.yaml`，**从不清理 `admin_alerts.json`** → seed 记录跨验证轮次永久累积（当前夹具已积压 19 条，最新为 2026-09-18 00:25 的 mergeback 告警）。
2. `/api/alerts` 的**缺省分支**跨所有被监控项目聚合未处理告警 → 夹具 seed 告警被当作真实人工告警，进顶部横幅并触发用户收到的告警消息。

用户要求：夹具项目带**标识**，读侧跨项目聚合时跳过它；但 `?project=<name>` 显式查询必须保留（api/web 验证场景依赖）。

现有相关机制：
- `Registry`（`core/dashboard/registry.py`）：配置 schema `{port, projects, scan_dirs, ignored}`；`discover()` 合并显式 projects 与扫描结果，返回 `[{name, path, discovered, exists}]`；`add_project(path, name)`/`remove_project`/`add_ignored`/`is_ignored`。
- 读侧聚合点：`core/dashboard/routes/alert_routes.py` 的 `_api_alerts`（缺省分支 `for p in self.server.projects():`）与 `_api_admin_activities`（同样缺省分支）。两处均已有「显式 `?project=` 分支」与「缺省聚合分支」的清晰分流。
- 夹具供给：`bin/fixture_scheduling_showcase.py` 的 `reset_fixture()`（写 `STATE.md`/`config.yaml` 基线 + `_ensure_registered()`）。

## Goals / Non-Goals

**Goals:**

- 引入夹具项目**权威标识**（registry `fixture` 布尔字段），语义为「该项目是验证夹具，其数据为验证噪音」。
- `/api/alerts` 与 `/api/admin-activities` 的**缺省跨项目聚合分支**跳过夹具项目；**显式 `?project=` 分支保留**，验证场景零回归。
- 夹具 `--reset` 复位 `admin_alerts.json` 基线，杜绝跨轮累积；并确保夹具以 `fixture: true` 登记。
- 存量夹具遗留 seed 告警随之清理。

**Non-Goals:**

- 不改写侧 seed 场景（验证数据必须保持真实形态，断言依赖 severity/handled 等字段）。
- 不移除夹具项目出监控列表、不隐藏其 overview/项目列表卡片（它是验证必需基础设施，用户仍需能进入查看）。
- 不为 `fixture` 新增独立 Dashboard 设置 UI（该字段由夹具供给脚本机械化写入，非用户手工配置项；registry 现有 `ignored`/`scan_dirs` 亦无专门 UI，沿用同一先例）。
- 不改告警存储格式、不改 AdminStore 读写语义。

## Decisions

### D1：标识载体 = registry 显式字段 `fixture`（存 `dashboard.yaml`），非项目内 config

在 `~/.config/fenixd/dashboard.yaml` 项目条目加 `fixture: true`。

- **为何不选项目内 `.fenix/config.yaml` 标记**：读侧聚合发生在 dashboard server，其项目来源是 `Registry.discover()`；若标记落在被管项目内，聚合时需为每个项目额外读一份 config.yaml（多次 IO、且目录不存在/不可读时语义复杂）。registry 是聚合的**唯一数据源**，标记放这里读取零成本、单一真源。
- **为何不放内存/推导**：夹具路径 `scheduling-showcase` 若靠路径/名字约定推导（如名字含 `showcase`、路径在 `tests/fixtures`），脆弱且不可扩展（未来多夹具、用户自建夹具）。显式字段是声明式、可审计的。

### D2：`discover()` 透出 `fixture`，`add_project` 支持写入，缺省假

`discover()` 返回项目 dict 新增 `fixture: bool`：显式条目读该键（缺省假），扫描发现的项目恒假（扫描无法判断夹具属性，缺省保守=非夹具，符合「宁多展示不静默隐藏」）。`add_project(path, name=None, fixture=False)` 新增关键字参数，写入配置条目。既有调用点（`--add-project` CLI）不传该参 → 缺省假，零行为变更。

**替代方案**：单独 `fixtures: [path...]` 列表。否决：与 `ignored` 平行的独立列表是重复 schema，且「项目属性」语义更契合放在项目条目内。

### D3：读侧只在**缺省聚合分支**过滤，显式分支零改动

`_api_alerts` / `_api_admin_activities` 的缺省分支循环 `for p in self.server.projects():` 处，加 `if p.get("fixture"): continue`。显式 `?project=` 分支（`self.server.project_by_name(...)` 路径）**完全不动**。

**为何不按「把夹具从 projects() 里过滤掉」整体实现**：`self.server.projects()` 是项目列表/overview/daemon 操作等**所有**读路径的共同数据源；在源头过滤会连带隐藏夹具卡片、破坏 `install-hosting`/`start`/`stop` 等操作与 29 个依赖夹具可见性的场景。过滤必须**收窄在告警/运维记录两个聚合端点**，这是「夹具数据是噪音」这一判断的唯一适用面。

### D4：夹具 `--reset` 复位 `admin_alerts.json` 到空基线

`reset_fixture()` 增加一步：把夹具 `.fenix/admin_alerts.json` 写为空数组 `[]`（或删除文件，读取层 `AdminStore.read_all()` 缺省返回空）。

**为何写空数组而非删除**：`AdminStore` 路径缺文件时返回空集，两者效果等同；写空数组让「夹具已复位」在磁盘上可见、且与既有 `STATE.md`/`config.yaml` 的「写回基线」风格一致。**注意**：必须用与 `AdminStore` 一致的写回方式（或直接原子写文件），避免半写损坏——写 `[]` 是最简单无锁风险的形态。

**为何放在 `--reset`（而非独立步骤）**：`--reset` 是 `verify.yaml` prepare 每轮验证前必经步骤，天然承担「夹具基线复位」职责；与 `STATE.md`/`config.yaml` 复位同处，语义一致。

### D5：夹具登记时带 `fixture: true`

`_ensure_registered()` 改为 `Registry().add_project(ROOT, fixture=True)`（并在既有条目缺标记时补写）。这样 `--reset` 每轮确保标记就位，存量夹具条目在下次验证时自动补标记。

## Risks / Trade-offs

- **[风险] 存量 `scheduling-showcase` 条目已存在且无 `fixture` 键，`add_project` 按路径去重会跳过、标记补不上** → 缓解：`_ensure_registered` 改为「已存在但缺 `fixture` 标记时补写该键」的更新语义（而非纯 add）；spec 场景「复位确保夹具标记就位」覆盖此点。
- **[风险] 未来新增夹具项目忘记标记 → 告警重新泄漏** → 缓解：夹具供给脚本统一以 `fixture=True` 登记是既有夹具范式的自然延伸；本 SPEC 的 reset 契约（Requirement 4）将此固化为夹具供给的标准动作。
- **[风险] 缺少 `fixture` 字段的旧 `dashboard.yaml`（存量用户）** → 缓解：读侧 `p.get("fixture")` 缺省假，零迁移；不标记的项目行为完全不变。
- **[权衡] `/api/alerts` 缺省响应语义变更**（夹具告警不再出现） → 这是需求本身；显式查询保留保证验证依赖不破。
- **[风险] reset 清空 `admin_alerts.json` 与并发 seed 竞争** → 缓解：`--reset` 在验证 prepare 阶段、任何 seed 场景（cli 场景）之前执行，时序上先于 seed；且验证场景串行依赖 seed→api/web。

## Migration Plan

1. 实施 `Registry` 的 `fixture` 读写透出（D2）。
2. 实施读侧两处缺省分支过滤（D3）。
3. 实施夹具 `--reset` 复位告警 + 登记带标记（D4/D5）。
4. 人工/机制侧：下一次任一 SPEC 验证 `prepare` 运行时，`--reset` 自动把存量 `scheduling-showcase` 标为 `fixture: true` 并清空其 `admin_alerts.json`——存量告警随之消失。在此之前，可手工在 `dashboard.yaml` 该条目补 `fixture: true` 立即止血（可选）。
5. 回滚：删除读侧过滤即恢复原聚合行为（`fixture` 字段成为惰性数据，无副作用）。

## Open Questions

- 无（标识载体、过滤范围、复位方式均已在需求澄清阶段与用户确认）。
