## Why

用户不定时收到**夹具项目** `scheduling-showcase` 的人工升级告警（如 2026-09-18 08:25 的 `evo-merge-back-wip-overlap-gate-575976`「merge-back 被 WIP 重叠闸门阻塞」横幅）。该告警并非框架在夹具里真实产生的运行事件，而是 fenixd **自身验证链**的 seed 场景（`seed-mergeback-overlap-alert-fixture` 等）经 `AdminStore.append` 往夹具 `.fenix/admin_alerts.json` **有意写入的验证数据**——为了验证 `/api/alerts` 与运维记录页能正确展示某类信号。

问题出在读侧口径与写侧用途不匹配：

1. **写侧**：seed 场景向夹具写入的是 `handled=false`、`severity=major/critical` 的真实告警记录（这是验证所需，不能改小），且夹具 `--reset` 只复位 `STATE.md`/`config.yaml`，**从不清理 `admin_alerts.json`**，记录跨轮永久累积。
2. **读侧**：`scheduling-showcase` 早已登记进 dashboard 全局监控配置（`~/.config/fenixd/dashboard.yaml`），是验证链正常运转的**必需基础设施**（29 个 api/web/cli 场景依赖它）。而 `/api/alerts` 的缺省分支（供顶部人工告警横幅）**跨所有被监控项目聚合未处理告警**——于是验证噪音被当成真实人工告警呈现给用户。

用户明确要求：夹具项目应带**标识**，读侧跨项目聚合时**跳过**它，避免假告警；但 `?project=<name>` **显式查询**必须仍返回夹具记录（api/web 验证场景依赖该消费路径）。同时夹具供给脚本 `--reset` 应一并复位告警文件，防止跨轮累积。

## What Changes

- 引入**夹具项目标识**：`~/.config/fenixd/dashboard.yaml` 的项目条目新增 `fixture: true` 字段（registry 显式字段），作为「该项目是验证夹具、其数据为验证噪音」的权威标记。
- `Registry` 支持读写与透出该字段：`discover()` 返回的每个项目 dict 增加 `fixture` 布尔；`add_project()` 支持写入 `fixture`；新增/复用设置该标记的接口供夹具供给脚本调用。自动扫描发现的项目 `fixture` 缺省为假。
- **跨项目聚合读侧过滤**：`/api/alerts` 与 `/api/admin-activities` 的**缺省（跨项目聚合）分支**MUST 跳过 `fixture=true` 的项目，使其告警/处置记录不进入人工告警横幅与跨项目运维记录聚合视图。`?project=<name>` **显式查询分支保留原行为**，夹具记录仍可被显式读取（验证场景不回归）。
- **夹具供给脚本复位告警文件**：`bin/fixture_scheduling_showcase.py --reset` 除复位 `STATE.md`/`config.yaml` 外，一并把夹具 `.fenix/admin_alerts.json` 复位到空基线（或移除），并确保夹具以 `fixture: true` 登记进 registry。
- 存量夹具项目（`scheduling-showcase` 已在监控列表）在实施后 MUST 被标记为 `fixture: true`；实施前的遗留 seed 告警记录随 `--reset` 清理。

## Capabilities

### New Capabilities

- `fixture-project-governance`: 夹具项目标识的权威语义；`Registry` 对 `fixture` 字段的读写与透出（`discover()` 项目 dict 含 `fixture` 布尔、`add_project` 支持写入、`~/.config/fenixd/dashboard.yaml` 条目接受该键）；**跨项目聚合读侧对夹具项目的过滤口径**（缺省聚合跳过、显式查询保留）；以及夹具供给脚本的复位契约（复位告警基线 + 标记夹具）。

### Modified Capabilities

（无——`fixture` 字段属新增能力，不改动既有 `project-discovery` 的要求语义。）

## Impact

- **代码**：
  - `core/dashboard/registry.py`（项目发现/注册 schema 扩展 `fixture` 字段）
  - `core/dashboard/routes/alert_routes.py`（`/api/alerts`、`/api/admin-activities` 缺省聚合分支过滤夹具）
  - `bin/fixture_scheduling_showcase.py`（`--reset` 复位告警文件 + 以 `fixture=true` 登记）
  - `~/.config/fenixd/dashboard.yaml`（存量 `scheduling-showcase` 条目补 `fixture: true`，由夹具脚本实施时写入）
- **接口**：`/api/alerts`、`/api/admin-activities` 缺省响应语义变更（夹具项目永不出现于跨项目聚合）；显式 `?project=` 分支不变。
- **依赖**：无新增外部依赖。
- **非目标**：不改写侧 seed 场景（验证数据必须保持真实形态）；不移除夹具项目出监控列表（它是验证链必需基础设施）；不改 overview/项目列表卡片（夹具卡片仍可见，用户仍可进入查看）；不新增独立 UI 开关（`fixture` 字段由夹具供给脚本机械化写入，非用户手工配置项）。
