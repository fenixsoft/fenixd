# llm-model-assignment Spec

## ADDED Requirements

### Requirement: 快速分配入口与分配模板

系统 SHALL 在设置页「Agent 模型分配」页签提供「快速分配」入口（按钮，位于「模型分配」标题区域），点击打开快速分配弹窗。弹窗 SHALL 提供与单角色分配同语义的模板编辑器：

- 角色默认模型（可选，留空表示不写角色级缺省模型）；
- 一组 provider + 模型候选链行（至少一行；每行 provider 必选、模型可留空；行序即候选回退顺序）。

应用时系统 SHALL 将 `ConfigLoader.KNOWN_AGENT_TYPES` 中的全部已知 Agent 角色（当前 13 个）的 `agents.models` 分配整体覆盖为该模板：每个角色获得相同的角色级缺省模型与相同顺序的候选链，原有各角色的分配 MUST 被替换而非合并。写入的配置形态 MUST 与单角色保存一致（经 `serialize_models_patch` 规范化：单行且无元素级模型时写 provider 名字符串，否则写数组）。模板未含任何有效 provider 行时 MUST 禁止应用（按钮 disabled 或应用时报错），且 MUST NOT 发起写入。MUST NOT 修改 `agents.subagent_model_override` 及其他 agents 配置键。

#### Scenario: 快速分配整体覆盖全部角色

- **WHEN** 用户在用户级作用域打开快速分配弹窗，模板为角色默认模型留空 + 单行 provider `volc-engine`（模型留空），点击应用
- **THEN** 用户级配置 `agents.models` 中全部 13 个已知角色均为 `volc-engine`（字符串形态），原各角色分配被覆盖

#### Scenario: 多行候选链按序写入

- **WHEN** 模板为两行：`volc-engine` + 模型 `deepseek-v4-pro`、`bigmodel.cn` + 模型留空，应用到某目标
- **THEN** 该目标每个角色的候选链按行序写为 `[{provider: "volc-engine", model: "deepseek-v4-pro"}, "bigmodel.cn"]`（或等价规范形态），且角色级缺省模型仅在填写时写入

#### Scenario: 无有效 provider 行禁止应用

- **WHEN** 弹窗中模板没有任何有效 provider 行（全部为空）
- **THEN** 应用被阻止（按钮 disabled 或提示错误），不发出快速分配请求、不写任何配置

### Requirement: 快速分配的作用域选择

弹窗 SHALL 提供作用域目标选择，且 MUST 至少选择一个目标：

- **本作用域**：当前设置页作用域——用户级写入用户级配置 `~/.fenix/config.yaml`；项目级写入当前项目的项目级配置 `<project_root>/.fenix/config.yaml`。
- **指定项目**：可多选已注册项目（来自 dashboard 项目列表），对每个选中项目写入其项目级配置，与当前页作用域无关。

指定项目选择 MUST 去重；同一目标 MUST 只写一次。未选择任何目标时 MUST 禁止应用。

#### Scenario: 本作用域用户级写入

- **WHEN** 当前设置页作用域为用户级，用户选择「本作用域」并应用快速分配
- **THEN** 写入用户级配置文件，用户级 `agents.models` 被整体覆盖，项目级配置不受影响

#### Scenario: 本作用域项目级写入

- **WHEN** 当前设置页作用域为项目 A 的项目级，用户选择「本作用域」并应用
- **THEN** 写入项目 A 的项目级配置文件，其他项目配置不变

#### Scenario: 指定多个项目批量写入

- **WHEN** 用户选择「指定项目」并多选项目 A、B（当前作用域为用户级），应用快速分配
- **THEN** 项目 A、B 各自的项目级 `agents.models` 均被整体覆盖；用户级配置不变

#### Scenario: 未选择目标禁止应用

- **WHEN** 弹窗中既未勾选「本作用域」也未选择任何项目
- **THEN** 应用被阻止且无任何写入

### Requirement: 指定项目 provider 自动补齐

写入指定项目（或项目级本作用域目标）前，系统 SHALL 校验模板候选链引用的每个 provider 名是否存在于该目标项目自身的 `llm.providers` 定义中。若缺失，系统 SHALL 从快速分配请求携带的 provider 定义（来源为当前作用域的有效 `llm.providers` 列表）按名称复制完整定义（name/baseurl/apikey 及可选 model/sdk_model）追加到该项目 `llm.providers` 后再写入；项目既有 provider 定义 MUST 保留、同名定义 MUST NOT 被覆盖。若当前作用域也不存在该 provider 定义、无法补齐，则该项目写入 MUST 失败并返回明确错误（指明缺失 provider 名），MUST NOT 落盘非法配置，其他目标不受影响。自动补齐与快速分配 MUST 在同一目标写入内完成，最终配置 MUST 通过既有配置校验（provider 引用校验与 Agent 模型校验）。

#### Scenario: 目标项目缺 provider 自动补齐并成功写入

- **WHEN** 项目 B 的项目级配置没有 `volc-engine` 的 provider 定义，用户以模板引用 `volc-engine` 对项目 B 应用快速分配
- **THEN** 项目 B 的项目级 `llm.providers` 追加来自当前作用域的 `volc-engine` 完整定义，项目 B 的 `agents.models` 全部角色写入该模板，写入成功

#### Scenario: 项目既有 provider 定义保留不覆盖

- **WHEN** 项目 B 已定义 `volc-engine`（与当前作用域同名但 baseurl 不同），对其应用快速分配
- **THEN** 项目 B 的 `volc-engine` 定义保持原值不变，仅 `agents.models` 被覆盖

#### Scenario: 无法补齐的项目单独失败

- **WHEN** 快速分配请求的 provider 定义集合中不存在模板引用的 provider `foo`（如当前作用域配置不完整）
- **THEN** 引用 `foo` 的目标项目写入失败并返回缺失 provider 的错误；其他可补齐目标照常成功；失败目标配置 MUST 不被部分写入

#### Scenario: 补齐后仍校验不通过则整体失败

- **WHEN** 目标项目写入前的合并配置无法通过既有配置校验（如 provider 定义缺 baseurl/apikey 或 agents.models 形态非法）
- **THEN** 该项目写入失败并返回校验错误，不落盘

### Requirement: 应用结果、界面刷新与提示

快速分配 SHALL 逐目标写入并返回逐目标结果：每个目标含成功/失败状态、失败原因与写入路径；单个目标失败 MUST NOT 阻止其他目标写入（部分成功）。请求级非法输入（目标为空、模板非法、项目名未注册）MUST 以 400 拒绝且不写任何目标。

应用期间弹窗与提交按钮 MUST 进入 loading/disabled 状态，防重复提交。结果反馈 MUST：全部成功时提示成功的目标数量；存在失败时逐项展示失败目标与原因，MUST NOT 以单一成功提示掩盖失败。应用前若当前设置页面板存在未保存修改且目标包含本作用域，SHALL 提示「快速分配将覆盖全部角色的模型分配，并丢弃当前未保存的修改」，用户取消则 MUST NOT 写入。写入成功后沿用既有口径提示「配置已保存，重启 daemon 后生效」（多目标时按目标说明）。

若本作用域写入成功，配置页 SHALL 重新加载配置并展示新的模型分配（表单回填新值），并清除该面板的已保存判脏状态；若仅写入指定项目、本作用域未写入，当前页面表单 SHALL 保持不变（不重载、不覆盖用户正在编辑的内容）。

#### Scenario: 本作用域成功后面板刷新

- **WHEN** 用户以用户级作用域应用快速分配成功
- **THEN** 配置页重新加载用户级配置，模型分配表单回填为新模板，面板判脏状态被清除，提示重启 daemon 后生效

#### Scenario: 未保存修改先确认

- **WHEN** 模型分配面板存在未保存修改，用户应用包含本作用域的快速分配
- **THEN** 弹出覆盖/丢弃确认；用户取消则不发起写入，面板内容保持不变

#### Scenario: 部分失败逐项展示

- **WHEN** 快速分配目标含项目 A、B，项目 B 因 provider 无法补齐失败
- **THEN** 结果反馈展示「项目 A 成功、项目 B 失败（原因）」，项目 A 已落盘，MUST NOT 只提示「保存成功」

#### Scenario: 仅指定项目时不重载当前表单

- **WHEN** 当前作用域为用户级（面板有用户未保存的编辑），用户仅对指定项目应用快速分配成功
- **THEN** 当前用户级表单内容保持不变，不触发当前页面配置重载

#### Scenario: 重复提交防护

- **WHEN** 用户点击应用后请求未返回
- **THEN** 提交按钮处于 loading/disabled，重复点击不会发出第二个请求

### Requirement: 快速分配弹窗的界面约束

快速分配弹窗 SHALL 遵循 `DESIGN.md`（界面设计宪法）：静态渲染、无动画/过渡/装饰动效；颜色取值来自 `theme.ts` 单源；字号/圆角/间距沿用既有设置页规范；空值显示「—」。弹窗 MUST 在移动端可完整滚动并可达应用/取消操作，MUST NOT 压缩或改变既有面板信息结构。该功能 MUST NOT 引入偏离 DESIGN.md 的设计（若引入，MUST 在 design.md 中写偏离声明段）。

#### Scenario: 移动端可操作

- **WHEN** 在移动端视口打开快速分配弹窗并编辑模板
- **THEN** 弹窗内容可滚动、应用与取消按钮可达并可点击，无横向溢出

#### Scenario: 静态渲染与主题单源

- **WHEN** 打开快速分配弹窗
- **THEN** 弹窗不使用 CSS 动画/过渡/装饰动效，颜色来自 `theme.ts` 主题变量（代码检查可见）
