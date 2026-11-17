## ADDED Requirements

### Requirement: blocked SPEC 处置相位判定字段（后端单点）
SPEC summary SHALL 新增 `blocked_phase` 字段，由后端单点判定（与既有 `frozen` 字段同模式），取值域为 `repairing` / `queued` / `null`。判定口径：

- `repairing`：该 blocked SPEC 存在在飞处置 agent——`admin-<spec>-` 或 `arbiter-<spec>-` 前缀 run 处于非终态（复用既有 run 元数据终态/新鲜度口径），或链状态文件 in_flight 区 `phase` 为 `admin`/`arbiter` 且未超既有 stale in_flight 超时口径（与 `reap_stale_inflight` 同源 started_at 判据）的条目指向该 spec；
- `queued`：无在飞处置 run，但 agent 自愈队列已挂起该 spec 的待处置件——判定只认有持久载体的挂起形态：`admin_alerts.json` 中该 spec 的 pending disposition 记录（有唤起标记而无 final、待看护重派，经既有 `merge_dispositions_by_run` 归并单点判定），或链状态文件 in_flight 区 `phase=deferred` 让行挂起条目。链派发队列是进程内 `queue.Queue`（无持久落盘），MUST NOT 作为判定源；
- `null`：以上皆无——含人工升级件、冻结转人工等待面。

MUST NOT 引入平行真相源：判定只读既有产物（run 目录、`admin_alerts.json`、链状态文件）。**人工升级件（升级 kind 告警）MUST NOT 计入 `queued`**——等待人的面必须保持「阻塞」。本字段是显示层判定，MUST NOT 影响状态机、调度、筛选与计数的任何行为。

#### Scenario: 在飞处置 run 判定为 repairing
- **WHEN** 某 SPEC `status=blocked` 且存在 `admin-<spec>-*` 或 `arbiter-<spec>-*` 前缀的非终态 run（或链在办件指向该 spec）
- **THEN** summary 的 `blocked_phase` 为 `"repairing"`

#### Scenario: 仅挂起待处置件判定为 queued
- **WHEN** 某 SPEC `status=blocked`、无任何在飞处置 run，且 `admin_alerts.json` 存在该 spec 的 pending disposition 记录（有唤起标记而无 final），或链状态文件 in_flight 区存在该 spec 的 `phase=deferred` 让行挂起条目
- **THEN** summary 的 `blocked_phase` 为 `"queued"`

#### Scenario: 等待人工面维持 null
- **WHEN** 某 SPEC `status=blocked`（含 frozen 冻结转人工）且无在飞处置 run、无 agent 自愈队列挂起件（仅有人工升级 kind 告警或无任何告警）
- **THEN** summary 的 `blocked_phase` 为 `null`

#### Scenario: 数据源读取失败容错回退
- **WHEN** 告警/链状态文件缺失、损坏或读取异常
- **THEN** 判定 fail-open 降级（在飞 run 证据仍可用时按其判定，否则 `null`），MUST NOT 使 `/api/specs` 调用链 500

#### Scenario: 状态机零影响
- **WHEN** 任意 SPEC 的 `blocked_phase` 取任意值
- **THEN** STATE.md 真实状态、daemon 调度、列表筛选选项与状态计数全部不受影响（计数仍按真实 `blocked` 统计）

### Requirement: 列表页与详情页三态标签渲染
SPEC 列表页与详情页 SHALL 在 `status=blocked` 时按 `blocked_phase` 覆盖状态标签渲染：`repairing` → 「修复中」、`queued` → 「排队中」、`null`/字段缺席/非法值 → 「阻塞」。三态 tone MUST 可区分：「修复中」「排队中」MUST NOT 沿用「阻塞」的 critical 红（修复中为进行中语义蓝、排队中为等待语义橙）。`status != blocked` 的其他状态渲染 MUST 完全不变。筛选下拉、状态计数页签、`STATUS_META` 键域 MUST NOT 新增键（真实状态值域不变）。

#### Scenario: 修复中显示
- **WHEN** 列表页或详情页渲染 `status=blocked` 且 `blocked_phase="repairing"` 的 SPEC
- **THEN** 状态标签显示「修复中」（进行中蓝系 tone），不显示「阻塞」

#### Scenario: 排队中显示
- **WHEN** 列表页或详情页渲染 `status=blocked` 且 `blocked_phase="queued"` 的 SPEC
- **THEN** 状态标签显示「排队中」（等待橙系 tone）

#### Scenario: 字段缺席或非法值回退阻塞
- **WHEN** summary 中 `blocked_phase` 缺席、为 `null` 或非值域值（存量前端缓存/增量 patch 竞态）
- **THEN** `status=blocked` 的 SPEC 按「阻塞」critical 红渲染，行为与现状一致

#### Scenario: 详情页切换下拉同语义
- **WHEN** 详情页 spec 快速切换下拉渲染 blocked SPEC 列表项
- **THEN** 状态标签与主列表三态语义一致（同一渲染辅助，无平行实现）
