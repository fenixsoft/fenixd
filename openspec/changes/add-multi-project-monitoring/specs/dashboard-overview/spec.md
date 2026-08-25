## ADDED Requirements

### Requirement: 概览展示 daemon 健康徽标

Dashboard 跨项目概览视图的项目卡片 MUST 展示该项目 daemon 的健康状态：`daemon="running"` 显示「运行中」徽标（正向色），`daemon="stopped"` 显示「未运行」徽标（弱化/警示色）。卡片上自动发现的项目 MUST 继续带「自动」标记。所有被监控项目 MUST 在同一概览页面统一展示，任意项目可点击下钻到其 SPEC 列表。

#### Scenario: 概览卡片显示 daemon 状态
- **WHEN** 概览中有运行中与未运行两个项目
- **THEN** 两个项目卡片分别显示「运行中」与「未运行」徽标，且均可点击下钻

#### Scenario: 自动发现标记保留
- **WHEN** 某项目由默认扫描自动发现
- **THEN** 其卡片显示「自动」标记，且 daemon 徽标仍按其健康状态展示

### Requirement: 多项目状态自动跟随

概览视图 MUST 在既有 2 秒自动刷新周期内反映监控列表与 daemon 状态的变化：新启动 daemon 的项目（被发现或已注册）MUST 在服务端发现缓存（默认约 10s）与健康缓存（默认约 5s）过期后自动出现/更新，无需重启 Dashboard 服务或手动刷新。

#### Scenario: 新运行的项目自动出现在概览
- **WHEN** 一个已注册但 daemon 未运行的项目启动其 fenixd daemon，随后概览刷新
- **THEN** 该项目卡片自动从「未运行」更新为「运行中」，无需重启服务

#### Scenario: 新发现项目自动出现
- **WHEN** 主目录下新增一个满足条件的 Fenixd 项目并启动 daemon，随后概览刷新
- **THEN** 该项目自动出现在概览卡片中（带「自动」标记），无需手动注册或重启
