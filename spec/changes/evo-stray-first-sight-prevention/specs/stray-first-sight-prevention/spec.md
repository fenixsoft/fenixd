# spec: stray-first-sight-prevention

## ADDED Requirements

### Requirement: 盘点首现提示

untracked 散件盘点在目录型产物集合首次出现（首现登记无该目录记录；去重键为目录路径，MUST NOT 采用随集合内容漂移的条目集指纹）且未被 .gitignore 覆盖（由上游散件清单豁免已 ignore 路径保证）时，MUST 发出一次 info 级首现提示信号（kind=maintree_untracked_stray_first_sight），evidence 携带目录清单、体积与预防性 .gitignore 条目草案（含成因注释）；集合低于既有 entry 阈值时同样提示。

#### Scenario: 新目录首现
- WHEN 主树出现新的未跟踪产物目录集合，登记表无其指纹记录且路径无 ignore 覆盖
- THEN 发出 maintree_untracked_stray_first_sight 一次，evidence 含条目清单、总体积与 gitignore 草案行

#### Scenario: 低于阈值集合也提示
- WHEN 首现集合条目数低于既有 info 档 entry 阈值（5）
- THEN 仍发出首现提示（below_threshold 早退不适用于首现判定），但不启动升级时钟

#### Scenario: 同目录不重复提示
- WHEN 同一目录已存在于首现登记且未复位（含集合内容增长、跨阈值档切换导致的指纹漂移）
- THEN 后续盘点不再发首现提示，既有 stale/escalated 语义不受影响

#### Scenario: 复位后再现
- WHEN 目录消失触发登记表复位后目录再次出现
- THEN 视为新首现，再次提示（复发场景正是提示价值所在）

#### Scenario: 已覆盖目录不提示
- WHEN 产物路径已被 .gitignore 规则覆盖
- THEN 不计为首现、不发提示（已 ignore 路径在 _untracked_stray_entries 豁免①②上游排除，不入散件清单）

### Requirement: 首现提示不升级不唤起

首现提示 MUST NOT 启动 24 小时滞留升级时钟、MUST NOT 进入 STORED_SIGNAL_TYPES 自动唤起收录（消费面是告警面板与后续评审/处置的背景信息，不制造新一轮 admin run）；既有升级路径（滞留 24 小时或体积超阈值）行为不变。

#### Scenario: 升级路径不回归
- WHEN 首现集合持续滞留达 24 小时或体积超阈值
- THEN 既有 maintree_untracked_stray_escalated 升级照常触发，首现提示的存在不改变升级判定

#### Scenario: 提示不自动唤起
- WHEN maintree_untracked_stray_first_sight 发出
- THEN 该 kind 不在 STORED_SIGNAL_TYPES 收录内，不派发 admin 处置 run

### Requirement: 登记与排除

首现登记 MUST 复用既有未跟踪散件持久化机制（同持久化文件 .fenix/stray_untracked_registry.json 承载，读写与字段适配同步，跨 daemon 重启保持），去重键为目录路径；目录整轮不再贡献散件条目即复位（同既有 absent 复位模式）；排除集沿用既有散件判定名单（.fenix/、系统临时目录等），不另立名单。

#### Scenario: 跨重启不重复提示
- WHEN 首现登记后 daemon 重启
- THEN 同目录不因重启而再次提示

### Requirement: 交付落盘覆盖检查点

implementer 交付契约（agents/implementer.md）MUST 要求：交付引入运行时落盘路径（日志、dump、产物目录）且落在仓库树内时，同提交追加对应 .gitignore 覆盖或将默认落盘路径移出仓库树，并在提交前以 git status 自查零 untracked 产物。

#### Scenario: 交付带落盘路径
- WHEN 交付的工具或服务在仓库树内产生运行时落盘
- THEN 同提交包含对应 .gitignore 覆盖（或落盘路径默认在仓库外），提交前 git status 无该产物条目