## MODIFIED Requirements

### Requirement: 归档操作后端语义

系统 SHALL 提供 `POST /api/spec-archive?project=<name>&spec=<name>`：将该 SPEC 的 `spec/changes/<name>/` 目录移动到 `spec/archive/YYYY-MM-DD-<name>/`（与 `bin/fenix_archive.py` 同一命名规则）。归档移动成功后系统 SHALL 迁出该 SPEC 的 STATE.md 条目至归档清单 `.fenix/STATE.archive.md`（`archived_by=ui`）；迁出失败 SHALL 降级为响应中的告警字段，不回滚目录移动。非终态 SPEC SHALL 拒绝归档；目标归档路径已存在时 SHALL 返回错误且不覆盖；不存在的 spec SHALL 返回 404 语义错误。归档成功后 SHALL 发出项目活动事件（供活动页/概览展示）。

#### Scenario: 归档终态 SPEC 成功

- **WHEN** 对 status=pushed 的 SPEC 调用归档 API
- **THEN** `spec/changes/<name>/` 移动为 `spec/archive/YYYY-MM-DD-<name>/`，STATE.md 中该条目迁出至归档清单（含 archived_at 与 archived_by=ui），响应含 ok 与归档路径

#### Scenario: 非终态 SPEC 被拒绝

- **WHEN** 对 status=implementing 的 SPEC 调用归档 API
- **THEN** 返回错误说明仅终态可归档，目录、STATE.md 与清单均不变

#### Scenario: 目标已存在不覆盖

- **WHEN** `spec/archive/YYYY-MM-DD-<name>/` 已存在时再次归档同名 SPEC
- **THEN** 返回错误提示，原目录不被覆盖，条目不迁出

#### Scenario: 迁出失败归档仍成功

- **WHEN** 归档移动成功但条目迁出失败（清单写入异常）
- **THEN** 响应仍为归档成功，含迁出告警字段；条目保留在 STATE.md，等待存量回填下一轮迁出

### Requirement: 列表归档判定以目录存在性为准

spec 列表 API（`GET /api/specs`）SHALL 为每个 SPEC 返回 `archived` 布尔字段：活跃目录 `spec/changes/<name>/` 不存在，且（活跃 STATE.md 或归档清单 `.fenix/STATE.archive.md`）有该条目，即判定为已归档（无论归档由界面、CLI skill、daemon 自动归档还是手动移动产生）。条目已迁出（仅清单有）的 SPEC SHALL 继续返回且 archived=true；活跃 STATE.md 与清单均无条目的名称 SHALL NOT 返回。

#### Scenario: 界面归档迁出后判定为已归档

- **WHEN** 通过归档 API 归档某 SPEC（条目已迁出清单）后请求 spec 列表
- **THEN** 该 SPEC 仍返回且 archived=true

#### Scenario: 自动归档迁出后判定为已归档

- **WHEN** daemon 自动归档迁出某 SPEC 条目后请求 spec 列表
- **THEN** 该 SPEC 仍返回且 archived=true，与界面归档行为一致

#### Scenario: 双源均无条目不返回

- **WHEN** 某名称仅存在归档目录但 STATE.md 与清单均无条目（软删除残留）
- **THEN** spec 列表不返回该名称
