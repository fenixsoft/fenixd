# Proposal: 配置分级（用户级 + 项目级深度合并与继承）

## Why

当前 fenixd 配置严格按项目存储：`ConfigLoader.load()` 强制读取项目 `.fenix/config.yaml` 且要求 `project/schedule/agents/...` 等必填键；Dashboard 的 `/api/config` 无 `project` 参数即返回 `unknown project`。用户在多项目间维护重复的 LLM Provider / 模型分配 / 并行度等通用设置，且在不选项目进入配置页时直接报错。配置应分级：用户级存放通用信息，项目级仅覆盖差异，未覆盖项继承用户级。

## What Changes

- 新增**用户级配置文件** `~/.fenix/config.yaml`（与项目级同名 `.fenix/config.yaml`），存放跨项目通用配置。
- **深度合并语义**：项目级配置按字典逐层覆盖用户级配置，未覆盖的键继承用户级；列表整体替换，不做元素级合并。项目级优先。
- `ConfigLoader` 新增**有效配置解析** `resolve_config(project_root)`：深合并（用户级或空，项目级或空），任一文件缺失都允许（内置默认兜底）；`project` 键仅项目级需要，缺失时用项目根目录名补齐，`REQUIRED_KEYS` 校验相应放宽。
- **Daemon 加载**改为 `resolve_config(PROJECT_ROOT)`，消除对项目级配置文件存在的硬性依赖。
- **Dashboard `/api/config`**：无 `project` 时读写用户级配置（消除 `unknown project`）；带 `project` 时返回**有效合并视图**并标注每个受管键的来源层级（用户级 / 项目级），新增 `scope`（`user`/`project`）与 `raw_exists` 字段。
- **Dashboard 前端**：配置页无项目 → 用户模式（维护用户级配置）；有项目 → 项目模式（显示合并值 + 「继承自用户级」badge）；保存写入当前作用域文件并提示路径。
- **Registry 发现放宽**：目录仅需存在 `STATE.md` 即识别为 Fenixd 项目（不再强制 `.fenix/config.yaml`）。
- 向后兼容：无用户配置时合并结果等于项目配置，现有项目行为不变；受管键仍为 `llm` / `agents.models` / `agents.max_concurrent` / `gates.approve_mode`。

## Capabilities

### New Capabilities
- `hierarchical-config`: 配置分级加载与继承——用户级/项目级配置文件的解析、深度合并、有效配置解析与校验放宽，以及 Dashboard 分级配置编辑（无项目维护用户级，有项目显示有效合并视图并标注来源）。

### Modified Capabilities
<!-- 无既有 specs，全部为新增 -->

## Impact

- `core/config.py`：新增合并与解析逻辑，放宽 `project` 键必填校验。
- `fenixd.py`：启动配置加载改走 `resolve_config`。
- `core/dashboard/server.py`：`/api/config` GET/POST 支持无项目（用户级）与带项目（合并视图 + 来源标注）。
- `core/dashboard/data.py`：`read_config`/`write_config` 支持作用域（用户/项目）与来源标注。
- `core/dashboard/static/app.js`：配置页用户模式/项目模式渲染与保存。
- `core/dashboard/registry.py`：扫描与注册放宽为仅需 `STATE.md`。
- `tests/`：新增 merge/resolve、用户级读写、来源标注、registry 放宽测试。
