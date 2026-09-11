# settings-system-tab — 设置页系统页签

## ADDED Requirements

### Requirement: 系统页签展示 admin 配置

设置页 SHALL 新增「系统」页签（SystemPanel），展示并允许编辑以下 `admin.*` 键，每项 MUST 附一句话注解（文案见 design.md 注解表）：

| 键 | 控件 |
|---|---|
| `admin.enabled` | Switch |
| `admin.interval_minutes` | 数字输入（正数） |
| `admin.escalation_cooldown_minutes` | 数字输入（非负数） |
| `admin.merge_breaker_threshold` | 数字输入（正整数） |
| `admin.shutdown_drain_seconds` | 数字输入（非负整数，0=快速停机） |

#### Scenario: 页签展示与注解
- **WHEN** 用户打开设置页的「系统」页签
- **THEN** 5 个配置项按注解表渲染（注解文案与 design.md 注解表一致）

### Requirement: admin 段读写回显闭环

`read_config`（`core/dashboard/data.py`）SHALL 将 admin 段纳入受管白名单，返回 5 个键的当前值（含各键缺省值）；设置页保存 SHALL 经既有 `write_config` 通道写回项目级 `.fenix/config.yaml` 并刷新回显。白名单扩展 MUST NOT 改变既有 llm/agents/verify 段的返回结构。

#### Scenario: 保存后回显一致
- **WHEN** 用户在系统页签修改 `shutdown_drain_seconds` 为 300 并保存
- **THEN** `.fenix/config.yaml` 的 `admin.shutdown_drain_seconds` 变为 300，重新打开页签回显 300（读路径含白名单 admin 段）

#### Scenario: 既有段回显零回归
- **WHEN** read_config 扩展 admin 段后，设置页其他页签（验证/自省/模型）加载数据
- **THEN** llm/agents/verify 段的返回结构与字段与扩展前一致，现有测试全绿

### Requirement: 写入校验

保存时 SHALL 校验：布尔键为 bool；`interval_minutes` 为正数；`escalation_cooldown_minutes` 为非负数；`merge_breaker_threshold` 为正整数；`shutdown_drain_seconds` 为非负整数；非法输入 MUST 拒绝保存并返回明确错误信息（沿用现有 config 写入校验的错误返回形态）。

#### Scenario: 非法值拒绝
- **WHEN** 用户将 `interval_minutes` 填为 `-1` 或 `abc` 并保存
- **THEN** 保存被拒绝，界面提示「须为正数」类明确错误，配置文件不被写入

### Requirement: 模板默认值修正

新项目配置模板 `.fenix/config.template.yaml` 的 `admin.shutdown_drain_seconds` 默认值 SHALL 由 1800 改为 0（快速停机 + interrupted 标记续做兜底；对 1-2 小时级 implementer/planner 在飞场景避免每次重启等满排水窗口）。注释同步更新，说明 0 的语义与 resume 兜底路径。

#### Scenario: 新项目开箱即得快速停机
- **WHEN** fenix-init 为新项目渲染 config.yaml
- **THEN** `admin.shutdown_drain_seconds` 为 0，supervisor 强杀等待回退 60s 窗口且 daemon 不排水（秒级退出），无缺省错配

### Requirement: 文档更新

`docs/help/08-config.md` SHALL 补充 admin 段 6 个键的说明（含排水窗口的「daemon 排水/supervisor 强杀等待=值+120s」双侧行为与 0 值语义），与模板注解一致。

#### Scenario: 文档与实现一致
- **WHEN** 实现合入后查阅 docs/help/08-config.md
- **THEN** admin 段 6 键均有说明，shutdown_drain_seconds 描述双侧行为与 0 值语义
