## ADDED Requirements

### Requirement: 依赖供给默认模式

验证 worktree 的 node_modules 供给，在 verify.yaml 未指定 `deps_mode` 且
项目 config 未设 `verify.deps_mode` 时，系统 SHALL 采用 **`hardlink`**
作为默认模式（原默认 `prefer-offline`），以共享 inode 方式供给依赖，
避免每个 serving worktree 实装一份 `node_modules`。

优先级链 MUST 保持为：`verify.yaml deps_mode` > `config verify.deps_mode`
> 代码默认（现为 `hardlink`）。

#### Scenario: 无任何显式配置时走 hardlink

- **WHEN** verify.yaml 无 `deps_mode` 且项目 config 无 `verify.deps_mode`
- **THEN** `resolve_deps_mode()` MUST 返回 `hardlink`

#### Scenario: 主树无 node_modules 时降级 prefer-offline

- **WHEN** 解析出的模式为 `hardlink` 但主树对应子目录不存在 `node_modules`
- **THEN** 供给 MUST 自动降级为 `prefer-offline`（`npm ci`），MUST NOT 失败

#### Scenario: 显式配置覆盖默认

- **WHEN** verify.yaml 显式声明 `deps_mode: prefer-offline`
- **THEN** 解析结果 MUST 为 `prefer-offline`，不受代码默认变更影响

### Requirement: 默认模式配置与界面一致

系统 SHALL 使代码默认值、配置模板、Dashboard 界面缺省与标注三处保持一致，
避免用户界面显示的「默认」与实际生效默认不一致。

- `.fenix/config.template.yaml` 的 `verify` 段 SHALL 显式列出
  `deps_mode: hardlink`。
- Dashboard `VerifyPanel` 在配置缺 `verify.deps_mode` 时的缺省选中项 MUST 为
  `hardlink`，且 MUST 在 `hardlink` 选项标注「默认」。

#### Scenario: 模板显式列出默认值

- **WHEN** 读取 `.fenix/config.template.yaml` 的 `verify` 段
- **THEN** MUST 存在 `deps_mode: hardlink`

#### Scenario: 界面缺省选中 hardlink

- **WHEN** 打开 Dashboard 设置页「验证契约」，配置中无 `verify.deps_mode`
- **THEN** 依赖供给模式 MUST 默认选中 `hardlink`，且该项标注含「默认」

#### Scenario: 既有偏好不被覆盖

- **WHEN** 项目 config 已有 `verify.deps_mode: prefer-offline`
- **THEN** 界面 MUST 选中 `prefer-offline`，MUST NOT 强制回落到新默认
