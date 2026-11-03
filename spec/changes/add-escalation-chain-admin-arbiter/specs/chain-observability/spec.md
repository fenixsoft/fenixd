# chain-observability Spec

## ADDED Requirements

### Requirement: 时间轴全链节点

SPEC 运行时间轴 SHALL 将处置链各角色记录作为一等节点：Admin 处置 run 节点（既有）之外，Admin 每次尝试的配额计数事件、Admin→Arbiter 转单事件（附 handoff_reason 摘要）、Arbiter 每次尝试（含拍板/复现计数）、复现事件、链终点上升件均 SHALL 在时间轴可见。arbiter 节点台账联查（既有 `_arbiter_ledger_index`/`_arbiter_node_payload`）保留并扩展到链事件；联查 MUST fail-open（文件缺失/条目损坏/未命中静默省略）。spec=null 信号（无归属 spec）MUST NOT 挂 SPEC 时间轴，落处置链视图归组。

#### Scenario: Admin 转单事件可见

- **WHEN** Admin 处置产出 `handoff: arbiter` 转单
- **THEN** 该 spec 时间轴出现转单节点（含 handoff_reason 摘要与去向 Arbiter 标识）

#### Scenario: 复现事件与配额计数可见

- **WHEN** 同签名第 2 次拍板后问题第 3 次复现上升
- **THEN** 时间轴可辨析各次拍板节点与复现上升节点（配额轨迹可回放）

### Requirement: Dashboard 自动化处置链视图

Dashboard SHALL 新增自动化处置链视图：展示链上在办件（Admin/Arbiter 当前 run 与等待队列）、各签名配额水位（已用/上限）、近期上升件；spec=null 信号按主体键归组于此视图。视图 MUST 只读（不提供链上人工干预入口——人工裁决入口收敛于上升件 choices）。与既有 alert/activities 页数据单源（`admin_alerts.json`/arbiter ledger/链状态文件），MUST NOT 引入平行真相源。

#### Scenario: 在办与队列可见

- **WHEN** 链上有 1 件在 Arbiter 处置、2 件排队
- **THEN** 处置链视图显示在办件（run 标识/已耗时）与队列深度，人工队列不含这三件

#### Scenario: spec=null 信号归组

- **WHEN** 蒸馏重试欠账类无 spec 信号入链
- **THEN** 该件按主体键在处置链视图可见（不在任何 SPEC 时间轴）

### Requirement: 链配置设置界面

新配置项——Admin 尝试配额、Arbiter 复现配额、复位窗天数、黑名单信号清单——SHALL 在 Dashboard 设置页提供编辑界面并经既有配置热更新（30s mtime）生效；配置键归属 `core/config.py` 单源校验。遵循「新增配置必须带 Dashboard 界面」项目惯例。

#### Scenario: 配额配置热更新

- **WHEN** 用户在设置页将 Arbiter 复现配额从 2 改为 3 保存
- **THEN** 30s 内 daemon 原地重载生效，无需重启（既有热更新机制）
