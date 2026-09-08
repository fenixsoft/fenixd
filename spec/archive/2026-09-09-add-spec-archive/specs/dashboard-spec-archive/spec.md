## ADDED Requirements

### Requirement: 更多菜单提供「归档 Spec」入口

spec 列表（桌面表格与移动端卡片共用）每行的「更多」菜单 SHALL 在「冻结 Spec / 解冻 Spec」项之后提供「归档 Spec」菜单项；该菜单项仅对终态 SPEC（status 为 done 或 pushed）启用，非终态 SHALL 置灰禁用。

#### Scenario: 终态 SPEC 显示可用归档项

- **WHEN** 某 SPEC 状态为 done 或 pushed，用户打开其「更多」菜单
- **THEN** 「归档 Spec」出现在「冻结 Spec」项之后且可点击

#### Scenario: 非终态 SPEC 归档项置灰

- **WHEN** 某 SPEC 状态为 implementing、testing 等非终态，用户打开其「更多」菜单
- **THEN** 「归档 Spec」可见但禁用，点击无效果

### Requirement: 归档操作后端语义

系统 SHALL 提供 `POST /api/spec-archive?project=<name>&spec=<name>`：将该 SPEC 的 `spec/changes/<name>/` 目录移动到 `spec/archive/YYYY-MM-DD-<name>/`（与 `bin/fenix_archive.py` 同一命名规则），且不修改 STATE.md 条目。非终态 SPEC SHALL 拒绝归档；目标归档路径已存在时 SHALL 返回错误且不覆盖；不存在的 spec SHALL 返回 404 语义错误。归档成功后 SHALL 发出项目活动事件（供活动页/概览展示）。

#### Scenario: 归档终态 SPEC 成功

- **WHEN** 对 status=pushed 的 SPEC 调用归档 API
- **THEN** `spec/changes/<name>/` 移动为 `spec/archive/YYYY-MM-DD-<name>/`，STATE.md 中该条目原样保留，响应含 ok 与归档路径

#### Scenario: 非终态 SPEC 被拒绝

- **WHEN** 对 status=implementing 的 SPEC 调用归档 API
- **THEN** 返回错误说明仅终态可归档，目录与 STATE.md 均不变

#### Scenario: 目标已存在不覆盖

- **WHEN** `spec/archive/YYYY-MM-DD-<name>/` 已存在时再次归档同名 SPEC
- **THEN** 返回错误提示，原目录不被覆盖

### Requirement: 前端归档确认与结果反馈

点击「归档 Spec」SHALL 先弹出确认框（说明 SPEC 将移入归档目录、可随时在「已归档」视图查看）；确认后调用归档 API，成功则提示并刷新列表（该 SPEC 从未归档视图消失），失败则展示错误原因。

#### Scenario: 确认后归档并刷新

- **GIVEN** 某 done 状态 SPEC
- **WHEN** 用户点击「归档 Spec」→ 确认
- **THEN** 列表刷新后该 SPEC 不再出现在默认（未归档）视图，切换到已归档视图可见

#### Scenario: 取消归档无副作用

- **WHEN** 用户在确认框取消
- **THEN** 目录与 STATE.md 均不变，列表不变

### Requirement: 列表归档判定以目录存在性为准

spec 列表 API（`GET /api/specs`）SHALL 为每个 SPEC 返回 `archived` 布尔字段：STATE.md 有条目且 `spec/changes/<name>/` 活跃目录不存在即判定为已归档（无论归档由界面、CLI skill 还是手动移动产生）。已删除 SPEC（STATE.md 无条目）不返回。

#### Scenario: 界面归档后判定为已归档

- **WHEN** 通过归档 API 归档某 SPEC 后请求 spec 列表
- **THEN** 该 SPEC 条目仍返回且 archived=true

#### Scenario: CLI skill 归档后同样判定为已归档

- **WHEN** 用户通过 /fenix-archive skill（仅移动目录、不写 STATE.md）归档某 SPEC 后请求 spec 列表
- **THEN** 该 SPEC 条目仍返回且 archived=true，与界面归档路径行为一致

### Requirement: 列表归档视图切换控件

spec 列表过滤区 SHALL 在「全部/仅需求/仅问题」切换控件右侧提供归档状态切换控件（对齐该 Radio.Group 的交互形态），选项为「未归档 / 已归档」，默认「未归档」；列表数据 SHALL 按所选归档状态过滤。已归档视图下的 SPEC 行 SHALL 隐藏调度相关操作（调整优先级、冻结/解冻、归档），保留查看文档等只读能力。

#### Scenario: 默认仅显示未归档

- **WHEN** 用户进入 spec 列表页
- **THEN** 列表只显示 archived=false 的 SPEC，切换控件当前值为「未归档」

#### Scenario: 切换查看已归档

- **WHEN** 用户将归档切换控件切到「已归档」
- **THEN** 列表只显示 archived=true 的 SPEC，显示其归档前状态与信息

#### Scenario: 已归档视图操作收敛

- **WHEN** 用户在已归档视图打开某行「更多」菜单
- **THEN** 菜单不含调整优先级、冻结/解冻、归档项（删除保留与否依实现，但不提供调度类操作）
