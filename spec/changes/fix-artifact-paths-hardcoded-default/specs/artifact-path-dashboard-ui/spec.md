## ADDED Requirements

### Requirement: 验证页签展示 has_build_artifacts 开关

Dashboard 设置页「验证」页签的「构建产物路径」卡片 SHALL 新增开关
`has_build_artifacts`（文案「项目存在构建产物」），并随三态呈现：

- **未裁决**（键缺省）：控件处于「未配置」态（antd `Switch` 无 indeterminate 语义，
  MUST 用三态控件如 `Radio.Group`，或以开关关 + 显式「尚未配置」文案区分），显示
  「尚未配置，可点下方『AI 起草』或手动填写」提示；路径列表可编辑；
  **注**：本卡片**不新增**「AI 起草」按钮（既有自动起草通路为 `ProjectProfilePanel.tsx`
  的「AI 起草验证契约」/ `POST /api/verify-yaml-autodraft`，只覆盖 verify.yaml；
  产物路径的起草由运行期信号 + Administrator 承担）。提示文案 MUST NOT 承诺本页面
  存在「AI 起草」入口——否则 Given 未实现的后端端点，文案即误导。
- **已声明有产物**（`true`）：开关为开，路径列表可编辑；
- **已声明无产物**（`false`）：开关为关，路径列表置灰/隐藏，显示「已声明本项目无
  构建产物」。

该开关 MUST 为项目级键：用户级作用域下只读（沿用既有产物路径卡片的作用域语义，
显示「请切换到对应项目编辑」）。

#### Scenario: 未裁决时显示待配置提示

- **WHEN** 项目配置中 `has_build_artifacts` 缺省，打开验证页签
- **THEN** 产物卡片 MUST 显示一个可区分「未配置」的控件态（三态控件，如
  `Radio.Group` 三选一：未配置 / 有产物 / 无产物）与「尚未配置」提示
- **AND** 路径列表 MUST 可编辑
- **AND** 「未配置」态 MUST NOT 被呈现为「无产物」——antd `Switch` 无
  indeterminate 语义（`SwitchProps` 仅 `checked?: boolean`），若使用 `Switch`
  承载，MUST 以文案区分两态，MUST NOT 声称开关处于未定态

#### Scenario: 关闭开关表示无产物

- **WHEN** 用户关闭 `has_build_artifacts` 开关并保存
- **THEN** 配置 MUST 写入 `worktree.has_build_artifacts=false`
- **AND** 卡片 MUST 置灰/隐藏路径列表并显示「已声明本项目无构建产物」

#### Scenario: 开启开关保留路径编辑

- **WHEN** 用户开启开关并填写 `dist/` 后保存
- **THEN** 配置 MUST 写入 `has_build_artifacts=true` 与
  `build_artifact_paths=["dist/"]`

#### Scenario: 用户级作用域只读

- **WHEN** 作用域为用户级，打开验证页签
- **THEN** 产物卡片 MUST 只读展示（含开关），MUST NOT 可写
- **AND** MUST 显示切换到项目级作用域的提示

### Requirement: 产物配置写入经后端校验

Dashboard 保存 `has_build_artifacts` 与 `build_artifact_paths` 时，后端 MUST 校验：

- `has_build_artifacts` MUST 为布尔（非布尔 MUST 被拒）；
- `build_artifact_paths` MUST 经 `validate_build_artifact_paths` 校验（沿用既有
  同口径：非法项被拒而非静默丢弃）；
- 两键 MUST 登记进 `config_admin.py` 的受管键、缺省字典与来源标注。

#### Scenario: 非法布尔值被拒

- **WHEN** POST 提交 `has_build_artifacts="yes"`（字符串）
- **THEN** 后端 MUST 返回 400 拒绝，MUST NOT 写入

#### Scenario: 非法路径项被拒

- **WHEN** POST 提交 `build_artifact_paths=["dist"]`（未以 / 结尾）
- **THEN** 后端 MUST 返回 400 并附合法形态提示（沿用 `validate_build_artifact_paths`）

#### Scenario: 两键登记进受管键回显

- **WHEN** 读取配置（`read_config` / `read_effective_config`）
- **THEN** `worktree.has_build_artifacts` 与 `worktree.build_artifact_paths`
  MUST 出现在回显与来源标注中

#### Scenario: 未裁决与已声明无产物在回显上可区分

- **WHEN** 项目配置文件未定义 `worktree.has_build_artifacts`，读取配置
- **THEN** 回显的 `worktree.has_build_artifacts` MUST 为 `None`（未裁决），
  MUST NOT 被缺省填充为 `false`
- **AND** 仅当配置显式写有 `false` 时回显才为 `false`——否则前端开关无法区分
  「未裁决」与「已声明无产物」两态（现有回显通路
  `worktree_config_view` 只返回 `build_artifact_paths`，MUST 一并扩展）
