## Why

`status=blocked` 的 SPEC 目前无论处于哪种处置相位——admin/arbiter 处置 run 正在执行、仅告警挂起排队、还是等待人工介入——在 Dashboard SPEC 列表与详情页统一渲染为「阻塞」（`STATUS_META` 单标签）。人工无法从外部一眼分辨哪些阻塞真正需要自己介入、哪些 agent 正在自愈，triage 成本高。

## What Changes

- 后端 SPEC summary 新增处置相位判定字段 `blocked_phase`（后端单点判定，与既有 `frozen` 字段同模式）：
  - `repairing`：该 blocked SPEC 存在在飞处置 agent（`admin-` / `arbiter-` 前缀 run 处于非终态，或处置链 in_flight 区 `phase` 为 `admin`/`arbiter` 且未超既有 stale 超时口径的条目指向该 spec）；
  - `queued`：无在飞处置 run，但 agent 自愈队列已挂起该 spec 的待处置件（`admin_alerts.json` 中该 spec 的 pending disposition 记录——有唤起标记而无 final、待看护重派；或链状态文件 in_flight 区 `phase=deferred` 让行挂起条目。链派发队列是进程内 `queue.Queue` 无持久载体，不作为判定源）；
  - `null`：无 agent 处理迹象（含人工升级件、冻结转人工等待面）→ 维持「阻塞」。
- 前端 SPEC 列表页与详情页的状态标签按相位三态渲染：`repairing` → 「修复中」、`queued` → 「排队中」、其余 → 「阻塞」（维持现红 critical）。
- **显示层 only**：状态机、调度、筛选、状态计数、运维页处置链视图全部不变，真实状态恒为 `blocked`；人工升级件不计入「排队中」（那是等待人的面，必须保持「阻塞」以便人工识别）。

## Capabilities

### New Capabilities
- `blocked-disposition-display`: blocked SPEC 的处置相位显示契约——后端 `blocked_phase` 单点判定口径（repairing/queued/null）、前端列表与详情页三态标签渲染、字段缺席与数据源读取失败的容错回退。

### Modified Capabilities

（无——既有能力 `blocked-disposition-classification`（spec/archive 内，frozen/阻塞二分类契约）的需求不变，本能力是其外部显示面的纯增补；dashboard 双标签消费语义不受影响。）

## Impact

- `core/dashboard/data/summary.py`：spec summary builder 新增 `blocked_phase` 判定字段（复用既有 run 元数据 memo 与告警/链状态读路径，不加平行真相源）。
- `core/dashboard/static/src/services/dashboard.ts`：`SpecSummary` 类型新增字段；状态标签渲染辅助支持相位覆盖。
- `core/dashboard/static/src/pages/projects/list.tsx`：列表状态列三态渲染。
- `core/dashboard/static/src/pages/projects/detail.tsx`：详情页头部状态标签与 spec 切换下拉三态渲染。
- 测试：后端 `tests/test_dashboard_data.py` 域新增相位判定用例；前端 `core/dashboard/static/tests/` 新增三态渲染用例。
- 依赖面：仅读既有产物（run 目录、`admin_alerts.json`、链状态文件），无 schema/迁移、无新配置键。
