## MODIFIED Requirements

### Requirement: 产物前缀判定的默认作用域

系统 SHALL 提供构建产物路径判定器，其判定集合 MUST 完全由配置驱动。框架 MUST NOT
内置任何项目路径作为默认判定集合——原 `DEFAULT_ARTIFACT_PREFIXES` 常量与
`_is_build_artifact_path()` 的默认语义（「static 根下任一层级含 dist 目录」）
MUST 被移除。

未配置 `worktree.build_artifact_paths` 且未声明 `worktree.has_build_artifacts`
时，判定集合 MUST 为空——`is_artifact()` 对任意路径 MUST 返回假（「未裁决」语义，
见 `artifact-path-declaration` 能力），MUST NOT 回退到任何内置路径。

框架自身仓库的产物路径（如 `core/dashboard/static/dist/`）MUST 与该仓库的其它
项目一样，通过配置显式声明，不再享有硬编码的默认豁免。

#### Scenario: 未配置时 dashboard 产物不再被判为真

- **WHEN** 判定路径 `core/dashboard/static/v3/dist/assets/a.js`，且未配置
  `has_build_artifacts` / `build_artifact_paths`
- **THEN** 判定 MUST 为假（原默认前缀集合已移除）
- **AND** 该路径 MUST 按语义内容处理

#### Scenario: 显式配置后 dashboard 产物判定为真

- **WHEN** 配置 `has_build_artifacts: true` 与
  `build_artifact_paths: ["core/dashboard/static/"]`
- **THEN** 判定路径 `core/dashboard/static/dist/assets/a.js` MUST 为真

#### Scenario: 未配置下根级 dist 仍判定为假

- **WHEN** 判定路径 `dist/index.html`，且未配置任何产物键
- **THEN** 判定 MUST 为假

### Requirement: 项目级产物前缀与通配配置

系统 SHALL 支持通过配置 `worktree.build_artifact_paths`（字符串列表）声明产物
判定集合。配置项 MUST 支持两种形态：

1. **目录前缀**：不含 `*` 且 MUST 以 `/` 结尾 —— 路径以该串开头即判定为产物；
2. **文件通配**：含 `*` —— 以 `fnmatch.fnmatchcase` 匹配**完整相对路径**
   （MUST NOT 只匹配 basename）。

配置项 MUST 经规范化后生效，非法项 MUST 被丢弃并记 WARNING，MUST NOT 使判定器
构造失败：

- 非字符串项（数字/None/嵌套结构）MUST 丢弃；
- 不含 `*` 且未以 `/` 结尾的项 MUST 丢弃（防 `dist` 误匹配 `dists/`）；
- 绝对路径或含 `..` 路径段的项 MUST 丢弃（仓库外/越界路径非本项目产物）；
- 全部项非法或配置为空列表 → 判定集合 MUST 为空（MUST NOT 回退任何默认集合）。

#### Scenario: 目录前缀生效

- **WHEN** 配置 `has_build_artifacts: true` 与
  `worktree.build_artifact_paths: ["dist/"]`，判定路径 `dist/index.html`
- **THEN** 判定 MUST 为真

#### Scenario: 文件通配生效且限定完整路径

- **WHEN** 配置 `worktree.build_artifact_paths: ["fenix-newtab-*.zip"]`，判定
  路径 `fenix-newtab-v1.0.0.zip`
- **THEN** 判定 MUST 为真

#### Scenario: 通配不匹配任意深度的同名文件

- **WHEN** 配置 `worktree.build_artifact_paths: ["*.zip"]`，判定路径
  `src/vendor/pkg.zip`
- **THEN** 判定 MUST 为假。`*` MUST NOT 跨 `/`：`fnmatch.fnmatchcase` 的 `*`
  语义是「匹配任意字符（含 `/`）」，故实现 MUST 在其之上追加约束——模式**不含**
  `/` 时 MUST NOT 命中含 `/` 的路径（本场景）；模式**含** `/` 时按完整相对路径
  匹配（可命中多层路径）

#### Scenario: 未以斜杠结尾的前缀被丢弃

- **WHEN** 配置 `worktree.build_artifact_paths: ["dist"]`
- **THEN** 该项 MUST 被丢弃并记 WARNING，判定集合 MUST 为空——路径
  `dists/a.js` MUST NOT 被判为产物

#### Scenario: 越界路径被丢弃

- **WHEN** 配置 `worktree.build_artifact_paths: ["../other-repo/dist/", "/abs/dist/"]`
- **THEN** 两项 MUST 均被丢弃，判定集合 MUST 为空（MUST NOT 回退默认集合）

#### Scenario: 配置形态非法时判定变空而非报错

- **WHEN** `worktree.build_artifact_paths` 的值为字符串（非列表）或 `[123, None]`
- **THEN** 判定器构造 MUST NOT 抛异常，判定集合 MUST 为空（MUST NOT 回退任何
  内置默认集合）
