## ADDED Requirements

### Requirement: SPEC 详情页下拉切换入口
SPEC 详情页头部标题区的 SPEC 名称旁 SHALL 展示一个下拉箭头按钮，点击后展开下拉面板。当项目下除当前 SPEC 外不存在其他 SPEC，或下拉数据不可用时，该箭头按钮 MUST NOT 展示。

#### Scenario: 存在其他 SPEC 时展示下拉箭头
- **WHEN** 用户打开某项目下 SPEC 的详情页，且该项目下存在至少一个其他 SPEC
- **THEN** SPEC 名称旁展示下拉箭头按钮，点击后展开下拉面板

#### Scenario: 无其他 SPEC 时不展示下拉箭头
- **WHEN** 用户打开 SPEC 详情页，且该项目下除当前 SPEC 外无其他 SPEC
- **THEN** SPEC 名称旁不展示下拉箭头按钮

### Requirement: 下拉面板行内容
下拉面板 SHALL 以表格形式列出 SPEC，每行展示 SPEC 名称与状态标签。状态标签 SHALL 与 SPEC 列表页使用同一状态语义（statusMeta）。

#### Scenario: 下拉行展示名称与状态
- **WHEN** 用户展开下拉面板
- **THEN** 面板中每行显示该 SPEC 的名称和对应的状态标签

### Requirement: 下拉排除当前 SPEC
下拉面板 MUST NOT 包含当前正在查看的 SPEC。

#### Scenario: 当前 SPEC 不出现在下拉中
- **WHEN** 用户展开下拉面板
- **THEN** 列表中不包含当前详情页对应的 SPEC 名称

### Requirement: 选中后切换 SPEC 详情页
用户在下拉面板中选择某个 SPEC 后，系统 SHALL 收起下拉面板并跳转至该 SPEC 的详情页（`/projects/:name/:spec`），页面数据随路由参数变化自动加载。

#### Scenario: 选择目标 SPEC 完成切换
- **WHEN** 用户在下拉面板中点击某个其他 SPEC
- **THEN** 下拉面板收起，页面路由变为该 SPEC 的详情页并加载其数据

### Requirement: 下拉数据加载降级
下拉列表 SHALL 复用现有 `GET /api/specs?project=` 接口获取数据。接口失败时详情页主体功能 MUST NOT 受影响。

#### Scenario: 下拉数据加载失败时静默降级
- **WHEN** 下拉列表接口请求失败
- **THEN** 下拉箭头不展示（或展开后显示加载失败提示），SPEC 详情页主体内容与交互保持正常
