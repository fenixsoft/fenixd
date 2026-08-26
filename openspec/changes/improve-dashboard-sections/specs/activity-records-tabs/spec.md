## ADDED Requirements

### Requirement: 运维记录按项目分页签展示

运维记录页跨项目视图（`activities/`）MUST 以页签形式按项目组织，替代现有平铺分段：页签栏 MUST 包含「全部」页签与每个有运维记录的项目名页签（按项目名排序）。默认激活「全部」页签，其内容仍按项目分段聚合展示全部记录；点击项目页签 MUST 仅展示该项目的运维记录。页签切换 MUST 为纯前端状态（不改变 URL hash），当前项目页签选择在页面内刷新/SSE 重绘后保持。单项目模式（`activities/<project>`）MUST 保持不变，仍只展示该项目记录。

#### Scenario: 跨项目视图按项目页签分组
- **WHEN** 项目 A 与项目 B 各有运维记录，用户打开 `activities/`
- **THEN** 页签栏显示「全部」「A」「B」，默认展示「全部」聚合内容

#### Scenario: 点击项目页签仅显示该项目
- **WHEN** 用户在 `activities/` 点击项目 B 页签
- **THEN** 页面仅展示 B 的运维记录卡片，不包含 A 的记录，URL 仍为 `activities/`

#### Scenario: 单项目路由保持
- **WHEN** 用户访问 `activities/B`
- **THEN** 页面仅展示 B 的运维记录，不显示页签栏

### Requirement: 处置记录保留换行展示

运维记录中的处置记录（disposition）MUST 多行内容按换行展示，不得压缩为单行。数据层写入新处置记录时，若 `actions_taken`/`summary` 为列表结构，MUST 以换行符（`\n`）连接各条目（每条目独立一行），而非以分号连接。前端渲染处置记录的活动卡片 MUST 对 summary、action_taken（处置）、recommended_action（建议）及旧记录降级回退区均保留换行（`white-space: pre-wrap` 与 `word-break: break-word`）。对历史已写入的单行/分号分隔记录，MUST NOT 强行拆分（避免误拆叙述性分号），按原样换行展示。

#### Scenario: 列表型动作以换行落盘
- **WHEN** Administrator 处置产生多条动作（`actions_taken` 为列表）
- **THEN** 落盘的 `action_taken` 字段以 `\n` 连接各动作，每条独立一行

#### Scenario: 多行处置内容按换行显示
- **WHEN** 某处置记录的 summary 或 action_taken 含换行符
- **THEN** 活动卡片中该字段按原始换行逐行显示，不合并为一行

#### Scenario: 旧单行记录不被误拆
- **WHEN** 历史记录中 `action_taken` 为含分号的单行叙述文本
- **THEN** 活动卡片原样显示该文本（分号不作为换行分隔符处理）
