# 方案评审门（reviewing 状态与晋升分流）
<!-- knowledge: capability=spec-review-gate rev=2
     sources=spec/archive/2026-09-19-add-spec-review-gate,spec/archive/2026-10-11-evo-fix-spec-review-infra-attribution-bridge -->

drafted 晋升前的方案评审门：`reviewing` 第 11 状态、评审模式开关、跳过白名单与四条晋升通道的同语义分流。

## 规则

- 状态机第 11 个状态 `reviewing`，纳入 `SpecStatus` 枚举与 `ALL` 列表；`VALID_TRANSITIONS` 相关边：`drafted → [ready, reviewing]`、`reviewing → [ready, blocked]`、`blocked → [ready, reviewing]`，既有 `blocked → ready` 边保留；对 `reviewing` 的非法转移（如 `reviewing → implementing`）被拒绝并记 ERROR，状态不被改写。
- 配置键 `gates.spec_review_mode`，枚举 `auto` / `never`，缺省 `auto`；配置校验拒绝非枚举值并在加载时报错，错误信息指出合法取值；纳入 Dashboard 受管配置键白名单（读侧 sources 标注与写侧提取两处），支持设置页读写与配置热更新（30s mtime 原地重载）。
- `auto`：默认全量评审，命中跳过白名单者除外；`never`：完全关闭评审——候选 SPEC 晋升行为直通 `ready`，不派发评审 run、不写评审相关 error。
- 跳过白名单（`auto` 下）：以下四项**全部命中**才跳过评审直通 `ready`——
  1. `.spec.yaml` 的 `mode` 为 `fast-track`；
  2. `specs/` 下能力目录数 ≤ 1；
  3. `tasks.md` 的 Deliverables 声明段条目数 ≤ 3；
  4. SPEC 名不以 `evo-` 开头（**硬否决项**：即使前三项全中，`evo-` SPEC 仍进评审）。
  字段缺失保守取「不跳过」：`mode` 缺失或无法解析、无 Deliverables 声明段时该条件视为不满足。
- 晋升链接入：共享晋升函数 `promote_drafted` 在软化与两道 lint 之后执行跳过判定，返回值给出下一状态（`next_status` ∈ `ready` / `reviewing`），调用方依此 transition。全部四条通道覆盖同一判定——PM Engine 自动晋升（`_on_spec_drafted`）、Dashboard `POST /api/spec-promote`、CLI `promote`、`/fenix-ready` skill；任一通道不得绕过判定直写 `ready`。
- `gates.promote_mode: manual` 的晋升闸口语义不受影响：manual 时 SPEC 停留 drafted 不晋升、不派发、不写 error；人工放行后同样经过评审判定。lint 违规的 SPEC 停留 drafted 并写 error，不进入 `reviewing`。
- 事件与调度接入：`_status_to_event` 映射 `reviewing → spec_reviewing`；engine 事件处理器表注册 `_on_spec_reviewing`；`check_scheduling_deadlines` 对 `reviewing` 走评审派发路径；`_recover_one` 对 `reviewing` 做评审派发恢复。四条晋升触发路径（`spec_drafted` 事件、`start_after` 到期唤起、full_scan recovery re-trigger、外部 drafted 写入 / scheduling_kick）在分流判定「需评审」时均能进入 `reviewing` 并被派发。
- 重派竞态被阻断：SPEC 已处 `reviewing` 且评审 run 在飞时，PM Engine 不重复派发第二个评审 run（判据见 spec-concurrency-governance 能力）。
- `reviewing` 属中断态，与 `implementing` / `testing` 同口径：daemon 重启时回退到 `drafted`，清空评审 run 引用并重置评审尝试计数，重新进入晋升链（软化与两道 lint 幂等，分流重新判定——若此时命中白名单则直通 ready）；回退不丢失评审者对 SPEC 目录已作出的修补。
- 评审 run 经派发队列异步执行，不占用实现并发槽位；在飞并发受可配上限约束（缺省 2-3，批量晋升时保留队列削峰，见 [spec-review-infra-attribution](spec-review-infra-attribution.md)）；在飞登记与实现派发顺延的并发治理见 spec-concurrency-governance 能力。

## 溯源

- 2026-09-19 2026-09-19-add-spec-review-gate（spec/archive/2026-09-19-add-spec-review-gate） — 新增评审门：reviewing 状态与转移边、spec_review_mode 配置、四条全中跳过白名单（evo- 硬否决）、晋升链四通道分流、事件/调度/恢复接入、中断回退与并发闸门
- 2026-10-11 evo-fix-spec-review-infra-attribution-bridge（spec/archive/2026-10-11-evo-fix-spec-review-infra-attribution-bridge） — 废除「不设评审并发上限」，改为可配在飞上限（缺省 2-3）
