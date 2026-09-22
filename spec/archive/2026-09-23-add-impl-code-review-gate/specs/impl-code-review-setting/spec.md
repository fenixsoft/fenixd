## ADDED Requirements

### Requirement: 配置键 `verify.impl_code_review` 的语义

系统 SHALL 提供布尔配置键 `verify.impl_code_review`，控制「实现阶段末尾的代码
质量审查」是否启用。该键 MUST 位于既有的 `verify` 配置节内，与
`verify.static_scope` / `verify.deps_mode` 同级。

- 缺省值 MUST 为 `false` —— 未配置、类型非法（非 bool）时一律按未启用处理
  （fail-open，脏值不启用审查，MUST NOT 因此中断派发）。
- 该键 MUST 支持两级作用域：用户级配置文件设为默认，项目级同名键覆盖之；
  解析 MUST 与既有 `verify.*` 键同源同优先级（项目级 > 用户级 > 代码缺省）。

#### Scenario: 未配置时审查不启用

- **WHEN** 用户级与项目级 config 均无 `verify.impl_code_review`
- **THEN** 读取器 MUST 返回 `false`，实现阶段 MUST 表现为「无此功能」——提示词
  零注入、产物硬门零校验

#### Scenario: 项目级开启覆盖用户级未设

- **WHEN** 用户级无该键、项目级 `verify.impl_code_review: true`
- **THEN** 该项目下派发的实现 run MUST 进入审查收尾流程

#### Scenario: 项目级显式关闭覆盖用户级开启

- **WHEN** 用户级 `verify.impl_code_review: true`、项目级同键为 `false`
- **THEN** 该项目 MUST 按未启用处理，MUST NOT 注入审查任务

#### Scenario: 非法值按未启用处理

- **WHEN** 配置中该键的值为字符串 `"yes"` 或数字 `1`（非 bool）
- **THEN** 读取器 MUST 返回 `false`，MUST NOT 抛出异常中断派发

### Requirement: 设置页「验证」页签的开关读写

Dashboard 设置页「验证」页签 SHALL 提供该配置键的开关控件，并 MUST 与既有
`verify` 节读写链路同源，保证「界面写入的值能被读回、界面显示的值即实际生效值」。

- 保存开关时 MUST 随既有 `verify` patch 一并提交（与 `static_scope` /
  `deps_mode` 同一个 `verify` 对象），MUST NOT 单独另立配置节。
- 服务端读路径 MUST 回显该键；写路径 MUST 合并该键；来源标注 MUST 登记该键，
  使前端「继承自用户级」标注与其它 `verify.*` 键行为一致。
- 开关关闭（`false`）为缺省呈现态；配置缺失时界面 MUST 显示为关闭，MUST NOT
  显示为「未知」或空值。

#### Scenario: 保存后可读回

- **WHEN** 在项目级作用域打开开关并保存
- **THEN** 重新加载配置 MUST 返回 `verify.impl_code_review: true`，界面 MUST
  显示为已打开

#### Scenario: 用户级默认在项目级呈现

- **WHEN** 用户级设为 `true`、项目级未设置
- **THEN** 项目级设置页 MUST 显示开关为打开，且来源标注 MUST 指示其继承自用户级

#### Scenario: 关闭开关被持久化

- **WHEN** 将已开启的开关关闭并保存
- **THEN** 配置文件 MUST 写入 `false`（而非删除该键），重新读取 MUST 返回 `false`

### Requirement: 配置模板一致性

`.fenix/config.template.yaml` 的 `verify` 段 SHALL 列出该键并附说明注释，使模板
与代码默认值、界面缺省三者口径一致。

#### Scenario: 模板列出该键

- **WHEN** 读取 `.fenix/config.template.yaml` 的 `verify` 段
- **THEN** MUST 存在 `impl_code_review` 键，其值 MUST 为 `false`，且相邻注释
  MUST 说明其作用（实现阶段末尾的代码质量审查开关）
