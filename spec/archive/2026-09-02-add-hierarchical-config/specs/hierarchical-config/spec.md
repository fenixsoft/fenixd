## ADDED Requirements

### Requirement: 用户级与项目级配置层级与路径

系统 SHALL 支持两层配置：用户级配置位于 `~/.fenix/config.yaml`，项目级配置位于 `<project_root>/.fenix/config.yaml`，两文件均为 `.fenix/config.yaml` 命名，作用域由所在目录决定。用户级配置用于存放跨项目通用设置，项目级配置用于覆盖项目差异。

#### Scenario: 两层级路径解析

- **WHEN** 系统解析某项目 `<project_root>` 的配置
- **THEN** 用户级路径为 `~/.fenix/config.yaml`，项目级路径为 `<project_root>/.fenix/config.yaml`

### Requirement: 深度合并与继承语义

系统 SHALL 以用户级配置为基础、项目级配置为覆盖进行深度合并：字典逐层递归合并（项目级优先），标量与列表由项目级整体替换（不做元素级合并）。项目级未显式定义的键 SHALL 继承用户级的值。

#### Scenario: 项目级只覆盖个别键

- **WHEN** 用户级配置定义 `agents.max_concurrent: 4` 与 `gates.approve_mode: manual`，项目级配置仅定义 `agents.max_concurrent: 2`
- **THEN** 有效配置中 `agents.max_concurrent` 为 2（项目级覆盖），`gates.approve_mode` 为 manual（继承用户级）

#### Scenario: 列表整体替换

- **WHEN** 用户级配置 `llm.providers` 含 2 个 provider，项目级配置 `llm.providers` 含 1 个 provider
- **THEN** 有效配置中 `llm.providers` 恰为项目级的那 1 个 provider，不合并用户级 provider

#### Scenario: 无用户级配置时行为不变

- **WHEN** 用户级配置不存在，项目级配置为完整配置
- **THEN** 有效配置等于项目级配置，且与仅存在项目级配置时的历史行为一致

### Requirement: 有效配置解析 resolve_config

系统 SHALL 提供 `resolve_config(project_root)`：读取用户级与项目级配置（任一或全部缺失均允许，缺失按空 dict 兜底），深度合并后返回有效配置。若有效配置缺失 `project.name`，SHALL 以项目根目录名补齐。解析时 SHALL 对已存在键执行既有值级校验，顶层必填键缺失不再强制报错（由消费方以默认值兜底）。

#### Scenario: 用户级与项目级均缺失

- **WHEN** `~/.fenix/config.yaml` 与 `<project_root>/.fenix/config.yaml` 均不存在
- **THEN** `resolve_config` 返回含默认值兜底的最小有效配置，且 `project.name` 为 `<project_root>` 的目录名，不抛异常

#### Scenario: 仅用户级存在

- **WHEN** 仅 `~/.fenix/config.yaml` 存在
- **THEN** `resolve_config` 返回用户级配置，且 `project.name` 由项目根目录名补齐

#### Scenario: 项目级覆盖后仍通过校验

- **WHEN** 用户级配置合法，项目级配置覆盖某个键后整体仍合法
- **THEN** `resolve_config` 返回合并后的有效配置且通过校验

### Requirement: Daemon 使用有效配置启动

Daemon 启动时 SHALL 使用 `resolve_config(PROJECT_ROOT)` 加载有效配置，而非直接读取项目 `.fenix/config.yaml`。用户级/项目级配置文件缺失时 daemon SHALL 仍能正常启动并运行。

#### Scenario: 无任何配置文件时 daemon 可启动

- **WHEN** 用户级与项目级配置文件均不存在，daemon 执行初始化
- **THEN** daemon 使用默认值兜底的有效配置完成初始化，不因缺少配置文件而退出

### Requirement: Dashboard 配置 API 作用域化

Dashboard `/api/config` GET 与 POST SHALL 支持两种作用域：无 `project` 参数时读写用户级配置（`~/.fenix/config.yaml`），不再返回 `unknown project`；带 `project` 参数时读写项目级配置。带 `project` 的 GET SHALL 返回有效合并视图，并返回 `sources` 标注每个受管键（`llm` / `agents.models` / `agents.max_concurrent` / `gates.approve_mode`）来自用户级还是项目级，以及 `scope`（`user`/`project`）与 `raw_exists`（当前作用域文件是否存在）。

#### Scenario: 无项目请求配置

- **WHEN** 前端请求 `GET /api/config`（无 project 参数）
- **THEN** 返回用户级受管配置，`scope` 为 `user`，不返回 `unknown project` 错误

#### Scenario: 有项目请求配置返回合并视图与来源

- **WHEN** 前端请求 `GET /api/config?project=<name>`，其中 `agents.max_concurrent` 仅定义于用户级
- **THEN** 返回中 `agents.max_concurrent` 为用户级的值，`sources["agents.max_concurrent"]` 为 `user`

#### Scenario: 无项目保存配置到用户级

- **WHEN** 前端 `POST /api/config`（无 project 参数）提交受管键
- **THEN** 配置写入 `~/.fenix/config.yaml`，返回 `scope` 为 `user`

#### Scenario: 带项目保存配置到项目级

- **WHEN** 前端 `POST /api/config?project=<name>` 提交受管键
- **THEN** 配置写入 `<project_root>/.fenix/config.yaml`，返回 `scope` 为 `project`

### Requirement: Dashboard 配置页双作用域渲染

前端配置页 SHALL 支持用户模式与项目模式：进入配置菜单不选择项目时默认为用户模式（维护用户级配置，标题标注「用户级」，保存后提示写入 `~/.fenix/config.yaml`）；选择项目时为项目模式（显示有效合并值，对来自用户级的受管键显示「继承自用户级」标注，保存写入项目级文件并提示路径）。用户级配置文件不存在时 SHALL 提示保存后创建。

#### Scenario: 无项目进入配置页为用户模式

- **WHEN** 用户在未选择项目时点击配置菜单
- **THEN** 配置页以用户模式渲染，标题含「用户级」，保存请求不带 project 参数

#### Scenario: 项目模式显示继承标注

- **WHEN** 项目配置页中某受管键 `sources` 为 `user`
- **THEN** 页面在该键旁显示「继承自用户级」标注，且表单值为有效合并值

#### Scenario: 用户模式无配置文件提示

- **WHEN** `~/.fenix/config.yaml` 不存在且用户进入用户模式配置页
- **THEN** 页面提示用户级配置文件尚不存在、保存后创建

### Requirement: Registry 发现放宽

Registry 扫描与项目注册 SHALL 仅以 `STATE.md` 存在作为 Fenixd 项目识别条件，不再要求 `.fenix/config.yaml`，使配置完全继承用户级的项目也能被监控。

#### Scenario: 无项目配置的目录被发现

- **WHEN** 目录存在 `STATE.md` 但不存在 `.fenix/config.yaml`
- **THEN** Registry 扫描将其识别为 Fenixd 项目并出现在监控列表

#### Scenario: 注册仅需 STATE.md

- **WHEN** 调用 `add_project` 注册一个存在 `STATE.md` 但无 `.fenix/config.yaml` 的目录
- **THEN** 注册成功
