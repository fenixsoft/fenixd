# fixture-project-governance 增量规格

## ADDED Requirements

### Requirement: 夹具项目标识的读写与透出

系统 MUST 支持在 dashboard 全局监控配置 `~/.config/fenixd/dashboard.yaml` 的项目条目上携带布尔字段 `fixture`，作为「该项目是验证夹具、其数据为验证噪音」的权威标记。

- `Registry.discover()` 返回的每个项目 dict MUST 含 `fixture` 布尔键：显式配置 `fixture: true` 的项目为真；未配置该键的项目、以及 `scan_dirs` 自动扫描发现的项目 MUST 缺省为假。
- `Registry.add_project(path, name=None, fixture=False)` MUST 支持把 `fixture` 标记写入配置条目；对已存在的同路径条目，再次注册 MUST 跳过（不重复添加、不静默改标记）。
- `Registry.mark_fixture(path, fixture=True)` MUST 按规范化路径定位配置条目并写入/更新 `fixture` 键后写回，作为**显式更新既有条目标记**的唯一途径；目标路径不在配置中时 MUST 返回未变更提示且不抛异常。`add_project` 对已存在同路径条目的「跳过」语义与之不冲突——跳过指不重复添加，改标记须经 `mark_fixture` 显式发起（供给脚本对存量夹具条目补标记即走此路径）。
- `fixture` 只标记来源，MUST NOT 改变项目的发现、监控、daemon 生命周期或可见性语义（夹具项目仍出现在项目列表与 overview 卡片中）。

#### Scenario: 显式标记夹具项目
- **WHEN** 调用 `Registry.add_project('/root/scheduling-showcase', fixture=True)`
- **THEN** 配置 `projects` 中该项目条目含 `fixture: true`
- **AND** `Registry.discover()` 返回的该项目 dict 含 `fixture: true`

#### Scenario: 未标记与自动扫描项目缺省非夹具
- **WHEN** 配置中某项目条目不含 `fixture` 键，且另有仅由 `scan_dirs` 扫描发现的项目
- **THEN** 两者在 `discover()` 结果中的 `fixture` 取值均为假

#### Scenario: 存量条目补写夹具标记
- **WHEN** 配置中 `scheduling-showcase` 条目已存在但不含 `fixture` 键，调用 `Registry.mark_fixture('/root/scheduling-showcase')`
- **THEN** 该条目被写入 `fixture: true`，且 `Registry.discover()` 返回的该项目 dict 含 `fixture: true`
- **AND** 对不在配置中的路径调用 `mark_fixture` 返回未变更提示且不抛异常

#### Scenario: 夹具标记不影响项目可见性
- **WHEN** 某夹具项目（`fixture: true`）被 `discover()`
- **THEN** 该项目仍出现在返回列表中（带 `exists` / `discovered` 等既有字段）
- **AND** `/api/projects/overview` 仍返回该项目卡片

### Requirement: 跨项目告警聚合跳过夹具项目

`GET /api/alerts` 的**缺省（跨项目聚合）分支** MUST 跳过 `fixture: true` 的项目：夹具项目的未处理升级告警、已解决告警与其摘要 MUST NOT 出现在响应的 `alerts` / `resolved` / `projects` 中，`total_unhandled` 亦 MUST NOT 计入夹具项目。

`GET /api/alerts?project=<name>` 的**显式查询分支** MUST 保留原行为：对被显式点名的项目（含夹具项目）返回其全部告警、摘要与处置记录，不受 `fixture` 标记影响。

#### Scenario: 缺省聚合不出现夹具项目告警
- **GIVEN** 夹具项目 `scheduling-showcase`（`fixture: true`）的 `admin_alerts.json` 含一条 `handled=false`、`severity=major` 的升级告警
- **WHEN** 请求 `GET /api/alerts`（不带 `project` 参数）
- **THEN** 响应的 `alerts`、`resolved`、`projects` 中均不含任何 `scheduling-showcase` 条目
- **AND** `total_unhandled` 不计入该夹具告警

#### Scenario: 显式查询夹具项目仍返回记录
- **GIVEN** 夹具项目 `scheduling-showcase`（`fixture: true`）含一条 seed 写入的升级告警
- **WHEN** 请求 `GET /api/alerts?project=scheduling-showcase`
- **THEN** 响应含该项目的完整告警列表与摘要（记录逐字保留，含 spec/severity/evidence 字段）

#### Scenario: 非夹具项目告警不受影响
- **GIVEN** 存在 `fixture: false` 项目含未处理告警，与夹具项目并存
- **WHEN** 请求 `GET /api/alerts`（不带 `project` 参数）
- **THEN** 非夹具项目的告警照常出现在 `alerts` 与 `total_unhandled` 中

### Requirement: 跨项目运维记录聚合跳过夹具项目

`GET /api/admin-activities` 的**缺省（跨项目聚合）分支** MUST 跳过 `fixture: true` 的项目：夹具项目的处置活动 MUST NOT 出现在响应的 `projects` 数组中。带 `?project=<name>` 的显式查询分支 MUST 保留原行为，仍可返回夹具项目的处置记录。

#### Scenario: 缺省聚合不出现夹具项目处置记录
- **GIVEN** 夹具项目 `scheduling-showcase`（`fixture: true`）含 seed 写入的 disposition 记录
- **WHEN** 请求 `GET /api/admin-activities`（不带 `project` 参数）
- **THEN** 响应的 `projects` 数组中不含 `scheduling-showcase` 分组

#### Scenario: 显式查询夹具项目处置记录仍返回
- **WHEN** 请求 `GET /api/admin-activities?project=scheduling-showcase`
- **THEN** 响应含该项目的处置活动列表（含 seed 记录）

### Requirement: 夹具供给脚本复位告警基线并标记夹具

`bin/fixture_scheduling_showcase.py --reset` MUST 在既有复位动作（重建 `spec/changes/` 目录、写回 `STATE.md`/`config.yaml` 基线、登记 registry）之外：

- 把夹具项目 `.fenix/admin_alerts.json` 复位到空基线（写空数组或移除文件后由读取层返回空集），使上一轮 seed 写入的告警/处置记录不跨验证轮次累积；
- 确保夹具以 `fixture: true` 登记进全局 registry（`add_project(ROOT, fixture=True)`）。

复位 MUST 幂等：连续多次 `--reset` 后夹具状态一致。

#### Scenario: 复位清除上一轮 seed 告警
- **GIVEN** 夹具 `admin_alerts.json` 含上一轮验证 seed 写入的升级告警
- **WHEN** 执行 `python3 bin/fixture_scheduling_showcase.py --reset`
- **THEN** 夹具 `admin_alerts.json` 被复位为空基线（`AdminStore.read_all()` 返回空列表或仅基线内容）

#### Scenario: 复位确保夹具标记就位
- **WHEN** 执行 `--reset` 且 registry 中夹具条目原先未带 `fixture` 标记
- **THEN** registry 中该项目条目被标记 `fixture: true`

#### Scenario: 复位幂等
- **WHEN** 连续执行两次 `--reset`
- **THEN** 第二次执行后夹具 `admin_alerts.json` 仍为空基线，registry 中夹具标记仍为真，不产生重复项目条目
