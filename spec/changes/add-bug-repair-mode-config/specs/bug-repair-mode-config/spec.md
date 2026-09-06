# bug-repair-mode-config 能力增量（add-bug-repair-mode-config）

> `admin.bug_repair_mode`：验证失败修复方式的显式配置——参数定义、校验、缺省语义、Dashboard 系统页签 UI 与热更新生效。

## ADDED Requirements

### Requirement: admin.bug_repair_mode 参数定义与缺省

配置 MUST 提供 `admin.bug_repair_mode` 参数，取值限 `inplace`（原地打回）或 `derive`（派生 fix-* 子 SPEC）。参数未配置时 MUST 缺省为 `inplace`。配置校验 MUST 拒绝非法取值（非字符串或非上述两个枚举值），拒绝方式与既有 `admin.*` 参数护栏一致。

#### Scenario: 未配置时缺省原地修复

- **WHEN** 配置中不存在 `admin.bug_repair_mode` 键
- **THEN** 有效配置返回 `inplace`，验证失败处置走原地打回路径

#### Scenario: 非法取值被校验拒绝

- **WHEN** 配置写入 `admin.bug_repair_mode: "always"`
- **THEN** 配置校验报错并指明 `admin.bug_repair_mode` 非法，配置不生效

#### Scenario: 显式配置 derive 生效

- **WHEN** 配置写入 `admin.bug_repair_mode: "derive"`
- **THEN** 有效配置返回 `derive`，验证失败处置走派生 fix 链路径

### Requirement: 系统页签展示与修改

Dashboard 设置页系统页签 MUST 展示「验证失败修复方式」配置项：未配置时显示缺省值「原地打回」，修改后写入 `admin.bug_repair_mode` 并持久化。前端类型定义 MUST 与后端配置结构同步（防 TS 类型缺失复发）。

#### Scenario: 页面展示缺省值

- **WHEN** 配置未设置 `admin.bug_repair_mode`，用户打开设置页系统页签
- **THEN** 配置项显示「原地打回」（inplace 缺省），而非空白或未定义

#### Scenario: 修改并持久化

- **WHEN** 用户在系统页签将该配置项改为「派生 fix SPEC」并保存
- **THEN** `admin.bug_repair_mode` 写入 `derive`，刷新页面后仍显示「派生 fix SPEC」

### Requirement: 配置热更新生效

`admin.bug_repair_mode` MUST 随既有配置热更新机制（30s mtime 检测）生效：下一次 bug-found 事件按最新有效值分流，MUST NOT 在引擎初始化时缓存该值。

#### Scenario: 运行中切换模式

- **WHEN** daemon 运行中配置由 `derive` 改为 `inplace`（或未配置）
- **THEN** 下一次验证失败的处置按原地打回执行，无需 daemon 重启
