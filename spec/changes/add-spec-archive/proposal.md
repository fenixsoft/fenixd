# add-spec-archive — SPEC 归档能力（界面手动归档 / 归档查询 / 自动归档）

## Why

`spec/changes/` 下已完成 SPEC 不断累积（当前 108 个 change 目录，archive 为空），列表越来越长，活跃 SPEC 与历史 SPEC 混杂，影响浏览与检索效率。CLI 侧已有 `/fenix-archive` skill 与 `bin/fenix_archive.py` 归档命令（见 integrate-openspec-native spec-archive 能力），但 Dashboard 无归档入口、无归档查询、更无自动归档，归档能力对日常使用不可达。

## What Changes

- **界面手动归档**：spec 列表行「更多」菜单在「冻结 Spec」之后新增「归档 Spec」菜单项，仅对终态（done/pushed）SPEC 可用；调用后端归档端点，效果等同 `fenix_archive.py`：将 `spec/changes/<name>/` 移动到 `spec/archive/YYYY-MM-DD-<name>/`，STATE.md 条目原样保留。
- **归档查询切换**：spec 列表过滤区（「全部/仅需求/仅问题」Radio.Group 右侧）新增归档状态切换控件，默认展示未归档 SPEC，可切换查看已归档 SPEC；归档判定以目录存在性为准（活跃目录 `changes/<name>/` 不存在即视为已归档），CLI skill 与界面两条归档路径天然一致。
- **自动归档**：设置页「其他」新增「自动归档阈值」配置（`archive.auto_threshold`，默认 50，0 = 禁用）；daemon 主循环周期检查各项目已完成（done/pushed）SPEC 数量，超过阈值时按完成时间（STATE.md `updated` 字段）从最久开始自动归档，直到数量降至阈值以内。

## Capabilities

### New Capabilities

- `dashboard-spec-archive`: spec 列表界面手动归档（更多菜单项 + 归档 API + 确认交互）与已归档/未归档过滤切换（列表聚合的归档判定）。
- `auto-spec-archive`: 自动归档阈值配置（设置界面「其他」面板 + 配置键校验 + 热更新生效）与 daemon 周期检查执行（超阈值按 updated 从久到新归档，0 禁用）。

### Modified Capabilities

<!-- 无：CLI 归档命令（bin/fenix_archive.py）与 fenix-archive skill 行为不变；spec 右键/更多菜单为增量扩展，不改变 add-spec-context-menu 既有 Requirement 语义 -->

## Impact

- `core/dashboard/data.py`：新增 `archive_spec()`（复用 fenix_archive.py 的移动逻辑与命名规则）；`spec_summary()` 增加 `archived` 判定。
- `core/dashboard/server.py`：新增 `POST /api/spec-archive` 端点；`_api_specs` 返回值带 archived 字段。
- `core/dashboard/static/v3/src/pages/projects/list.tsx`：更多菜单新增「归档 Spec」（冻结之后，终态启用）；过滤区右侧新增归档切换控件；归档确认弹窗（对齐删除确认模式）。
- `core/dashboard/static/v3/src/services/dashboard.ts`：新增 `archiveSpec()`。
- `core/dashboard/static/v3/src/pages/settings/components/MiscSettingsPanel.tsx`：新增自动归档阈值输入（InputNumber，min=0）。
- `core/config.py`：`archive.auto_threshold` 校验（非负整数）。
- `fenixd.py`：主循环挂自动归档周期检查（低频，独立计时变量，对齐配置热更新/恢复复查模式）。
- 复用 `.fenix/bin/fenix_archive.py` 命名规则 `YYYY-MM-DD-<name>`；删除路径的 `archive/<name>-<Unix秒>` 命名不变。
- STATE.md 格式不变（归档不写 STATE.md）；被归档 SPEC 仍留在 STATE.md，daemon 调度扫描需跳过其目录已不在 changes/ 的条目。
