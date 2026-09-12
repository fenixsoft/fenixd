# stale-code-selfheal Spec（delta）

## MODIFIED Requirements

### Requirement: stale_code_selfheal 配置与界面

系统 MUST 支持 `stale_code_selfheal` 配置节，含 `enabled`（布尔，缺省 `true`）与 `idle_confirm_seconds`（整数秒，缺省 `120`）。配置缺失或键非法时 MUST 回退缺省值且不使 daemon 启动失败。配置 MUST 走既有 30s 配置热更新，改动 MUST 在下一检测周期生效而无需重启 daemon。

Dashboard 设置页 MUST 提供该节的可读写界面（遵循「新增配置项必须带界面」的既有约束），展示项 MUST 与配置文件键一一对应。该界面 MUST 位于设置页**「自进化」页签**（原「自愈」页签改名，见 `suggested-improvements-ui`）下的**第一张卡片**，标题为「代码陈旧自愈」；同一页签下的第二张卡片为「建议改进项」，两者互不影响。改名 MUST NOT 改变本节的配置键、缺省值、语义与面板控件（开关 + 连续空闲秒数输入）。

#### Scenario: 缺省值生效

- **WHEN** 配置文件中不存在 `stale_code_selfheal` 节
- **THEN** 自愈按 `enabled: true`、`idle_confirm_seconds: 120` 运行

#### Scenario: 非法值回退不中断

- **WHEN** `idle_confirm_seconds` 被写成非整数或负数
- **THEN** daemon 回退到缺省 120 秒，不抛异常、不中断主循环

#### Scenario: 热更新立即生效

- **WHEN** 用户在运行中的 daemon 上把 `enabled` 改为 `false`
- **THEN** 下一检测周期起不再触发自愈，无需重启 daemon

#### Scenario: 设置页「自进化」页签下可读写该节

- **WHEN** 用户在 Dashboard 设置页进入「自进化」页签查看第一张卡片
- **THEN** 卡片标题为「代码陈旧自愈」，界面展示 `enabled` 与 `idle_confirm_seconds` 的当前值，修改保存后写回配置文件

#### Scenario: 页签改名不影响自愈行为

- **WHEN** 页签文案由「自愈」改为「自进化」后，daemon 命中陈旧状态
- **THEN** 陈旧检测、告警与空闲自愈触发行为与改名前的规格逐条一致（本 SPEC 不改该 spec 的其余 requirement）
