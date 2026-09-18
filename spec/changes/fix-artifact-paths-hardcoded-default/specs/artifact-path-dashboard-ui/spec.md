## ADDED Requirements

### Requirement: 验证页签展示 has_build_artifacts 开关

Dashboard 设置页「验证」页签的「构建产物路径」卡片 SHALL 新增开关
`has_build_artifacts`（文案「项目存在构建产物」），并随三态呈现：

- **未裁决**（键缺省）：开关处于 indeterminate/未定状态，显示「尚未配置，可点下方
  『AI 起草』或手动填写」提示；路径列表可编辑；
- **已声明有产物**（`true`）：开关为开，路径列表可编辑；
- **已声明无产物**（`false`）：开关为关，路径列表置灰/隐藏，显示「已声明本项目无
  构建产物」。

该开关 MUST 为项目级键：用户级作用域下只读（沿用既有产物路径卡片的作用域语义，
显示「请切换到对应项目编辑」）。

#### Scenario: 未裁决时显示待配置提示

- **WHEN** 项目配置中 `has_build_artifacts` 缺省，打开验证页签
- **THEN** 产物卡片 MUST 显示开关（未定态）与「尚未配置」提示
- **AND** 路径列表 MUST 可编辑

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
