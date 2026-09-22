## ADDED Requirements

### Requirement: 配置读取

系统 SHALL 以 `admin.code_review_fix.*` 段承载自动修复配置，段缺失或字段非法时 MUST 回退缺省值。

- `admin.code_review_fix.enabled`：总开关，缺省 `false`，严格 bool（非 bool 值 MUST 回退 `false`）。
- `admin.code_review_fix.batch_size`：每批条目数，缺省 `20`，MUST 为正整数（bool 与 ≤0 / 非整数 MUST 回退 `20`）。
- 读取器 MUST 为 `ConfigLoader.get_code_review_fix_config(config)`，形态对齐既有 `get_code_review_config`（段非 dict → 视为缺省）。
- 段缺失时 MUST NOT 报错，返回 `{"enabled": False, "batch_size": 20}`。

#### Scenario: 段缺失回退缺省

- **WHEN** `.fenix/config.yaml` 无 `admin.code_review_fix` 段
- **THEN** `get_code_review_fix_config` MUST 返回 `{"enabled": False, "batch_size": 20}`

#### Scenario: 非法批大小回退

- **WHEN** `admin.code_review_fix.batch_size` 为 `0`、`-3`、`true` 或 `"20"`
- **THEN** 生效值 MUST 为缺省 `20`，MUST NOT 被当作合作值使用

### Requirement: Dashboard 受管键读写

系统 SHALL 把 `admin.code_review_fix` 段接入 Dashboard 配置读写链路，逐条对齐既有 `admin.code_review` 的落点，缺任一落点即用户不可见或不生效。

- `_SOURCE_KEYS` MUST 含 `"admin.code_review_fix"`。
- MUST 定义缺省回显常量 `_DEFAULT_CODE_REVIEW_FIX = {"enabled": False, "batch_size": 20}`，并在 `read_config` 缺省段回显。
- `read_config` / `read_effective_config` MUST 经 `ConfigLoader.get_code_review_fix_config` 回显生效值。
- `_deep_merge_managed` MUST 支持该段的合并写入。
- `write_config` MUST 前置校验：`enabled` 严格 bool、`batch_size` 正整数，非法 MUST 明确失败（不静默忽略、不半写）。
- `_SYNC_PAGE_KEYS` 的 `quality` 页签 MUST 含该段（用户级同步）；`_SYNC_PAGE_KEYS` 的现行形态为「页签 → {配置段: [键名]}」映射（`core/dashboard/data/config_admin.py:1750-1800`，如 `"quality": {"verify": [...]}`、`"system": {"admin": [...]}`），故该段 MUST 以 `"admin": ["code_review_fix"]` 形态登记在 `quality` 页签下。
- 缺失该段时读侧 MUST 回显缺省，MUST NOT 500。

#### Scenario: 保存后回显

- **WHEN** 用户写入 `admin.code_review_fix: {enabled: true, batch_size: 30}`
- **THEN** 重新读取配置 MUST 回显 `enabled=true, batch_size=30`，`sources` MUST 标注为 `project`

#### Scenario: 非法值拒绝落盘

- **WHEN** 写入 `admin.code_review_fix: {batch_size: 0}`
- **THEN** 写入 MUST 失败（返回明确错误），配置 MUST 保持原值，MUST NOT 半写

### Requirement: 配置模板与文档

系统 SHALL 把新配置键同步到入库的模板与文档，MUST NOT 只落代码。

- `.fenix/config.template.yaml` MUST 含 `admin.code_review_fix` 段示例（`enabled: false` / `batch_size: 20`），形态 MUST 与既有 `admin.code_review` 一致——该文件（`git ls-files` 命中，入库交付）中的 admin 段以**整段注释**的惰性形态存在（`.fenix/config.template.yaml:341-350` 的 `# code_review:` / `#   enabled: false`），MUST NOT 写成未被注释的活配置（那会改变所有项目的生效缺省）。
- `docs/help/09-config.md` 的「Dashboard 设置页与配置键映射」表 MUST 含 `admin.code_review_fix.enabled` 与 `admin.code_review_fix.batch_size`，并 MUST 有专节说明语义与缺省。

#### Scenario: 模板含新键

- **WHEN** 检查 `.fenix/config.template.yaml`
- **THEN** MUST 含 `admin.code_review_fix` 段的 `enabled` 与 `batch_size` 说明

#### Scenario: 映射表含新键

- **WHEN** 检查 `docs/help/09-config.md` 的映射表
- **THEN** MUST 含 `admin.code_review_fix.enabled` 与 `admin.code_review_fix.batch_size` 两行

### Requirement: 设置页「自动修复代码问题」开关与批大小

设置页「质量」页签 SHALL 在「周期性代码审查」开关下方提供「自动修复代码问题」开关与批大小输入。

- 开关 MUST 绑定 `code_review_fix_enabled`（bool），回填自 `config.code_review_fix?.enabled === true`。
- 批大小 MUST 绑定 `code_review_fix_batch_size`（数值输入，合法范围 1–1000），回填自 `config.code_review_fix?.batch_size`（缺失回退 20）。
- 保存时必须经**同一个** `<Form>` 实例提交（`code_review_fix: {enabled, batch_size}`），MUST NOT 因控件脱管而提交恒缺省值。
- 开关与批大小 MUST 位于「周期性代码审查」之下（2026-09-22 起并入同一「代码质量」卡片、渲染在其后；原独立卡片约束作废）。
- 前端 service 类型 MUST 含 `CodeReviewFixConfig { enabled?, batch_size? }` 与 `ConfigData.code_review_fix?`。

#### Scenario: 开关可开启并持久化

- **WHEN** 用户在「质量」页签打开「自动修复代码问题」并保存
- **THEN** 配置 MUST 持久化为 `admin.code_review_fix.enabled: true`，重进设置页 MUST 回显为开

#### Scenario: 批大小可改

- **WHEN** 用户把批大小从 20 改为 50 并保存
- **THEN** 配置 MUST 持久化为 `admin.code_review_fix.batch_size: 50`，编排选批 MUST 按 50 条一批

#### Scenario: 开关位于周期性代码审查下方

- **WHEN** 打开设置页「质量」页签
- **THEN** 「自动修复代码问题」开关 MUST 渲染在「周期性代码审查」之后（同一「代码质量」卡片内）
