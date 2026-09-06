# add-timeline-admin-events — Design

## Context

- `get_spec_timeline`（`core/dashboard/data.py:2381`）目前产出两类节点：`state`（日志 Transition 行 + update_spec 直写重建）与 `run`（`.fenix/runs/` 产物）。排序经 `_timeline_sort_key`（秒截断时间 + kind 次序：state=0, run=1），前向状态折叠经 `_collapse_timeline`。
- admin 运维记录持久化在 `.fenix/admin_alerts.json`（`core/admin_store.py` AdminStore，三类 kind：signal/escalation/disposition），全量记录 100% 携带 `spec` 字段；`get_admin_activities` 已实现「同 admin_run_id 归并（最终处置覆盖 pending）」语义，供运维记录页使用。
- 前端 SPEC 详情时间轴在 `detail.tsx` `renderTimeline`（:736），按 `item.kind` 分支渲染 antd Timeline。

## Goals / Non-Goals

**Goals**
- 时间轴下发该 spec 关联的 escalation + disposition 事件，与既有节点统一排序。
- 前端紧凑卡片渲染（标题行 + 一句话摘要），不重复运维记录页的全文职责。

**Non-Goals**
- 不改运维记录页（admin-activity-view 已归档能力，行为不变）。
- 不在时间轴卡片渲染 summary markdown 四段全文、不做 mark-handled 等交互（仍走运维记录页）。
- 不新增 API 端点（复用 `GET /api/spec-detail` 的 `timeline[]`）。

## Decisions

### D1 — 数据读取复用 AdminStore，不新开文件 IO
时间轴侧调用 `AdminStore(project_root).read_all()`（既有带锁、容错读，异常返回 `[]`），新加私有 helper（如 `_admin_events_for_spec(project_root, spec_name)`）负责过滤 `spec` 字段匹配 + `kind in {escalation, disposition}` + pending 归并。
*备选*：直接 `json.load` 文件——绕过锁与容错，弃；走 `get_admin_activities`——其内置置顶/handled 关联等页面语义，时间轴用不上且耦合，弃。

### D2 — pending 归并采用轻量版 best_by_run 语义
按 `admin_run_id` 分组：组内存在非 pending 最终处置 → 仅保留最新最终处置；否则保留 pending。无 `admin_run_id` 的记录独立成节点（与运维记录页归并语义一致但不引入置顶/_pin 概念）。
*备选*：pending 与最终都展示——时间轴上「处置中 → 已解决」是同一次介入，双节点噪音且误导为两次事件，弃。

### D3 — 排序：`_timeline_sort_key` kind 次序扩展为 state=0, admin=1, run=2
语义依据：同秒内的真实顺序是「状态转移（如 testing→bug-found）→ admin 处置完成 → 触发重派的 run 启动」。run 节点 started 是秒级截断、必然晚于同秒的 state（既有注释结论），admin 夹在两者之间。现有 `kind_rank = 0 if state else 1` 需改为显式映射，state/run 相对次序不变，既有行为零漂移。
*备选*：admin 排最尾（rank=1 之后）——同秒 admin 处置会出现在重派 run 之后，因果倒置，弃。

### D4 — 折叠逻辑零改动
`_collapse_timeline` 只缓冲 `kind=="state"` 且无 reason 的节点，遇任何其它 kind 冲刷缓冲——admin 节点天然打断连续前向转移折叠，无需修改。

### D5 — 前端渲染分支与降级
`renderTimeline` 的 `timeline.map` 中在 state 分支后新增 `kind==="admin"` 分支：severity 着色映射复用运维记录页既有配色（critical 红 / major 橙 / 其余灰）；description 用 `Typography.Text` ellipsis 截断。未知 kind 落到既有 run 默认分支之前的显式守卫（state/admin/run 之外不渲染卡片体），避免脏数据崩渲染。
*备选*：后端把 admin 事件伪装成 state 节点——字段语义不符，前端无从区分标签，弃。

### D6 — 归档 spec 的 admin 事件可见性
admin 记录不过期、不随 spec 归档清理：历史 SPEC（已 pushed）的时间轴同样能回看其运维事件，与 run 节点的 include_archive 语义对齐，无需额外处理。

## Risks / Trade-offs

- [D3 改 `_timeline_sort_key` kind 次序，既有测试可能断言 run rank=1] → 全量回归 `tests/test_dashboard_data.py` 时间轴用例；state/run 相对次序不变，预期零失败。
- [admin_alerts.json 单文件 289KB 且持续增长，时间轴每次详情请求全量读] → AdminStore 读已是既有路径（运维记录页同代价）；spec 过滤在内存做，量级（<千条）不构成瓶颈；若未来膨胀再引入游标/缓存，本期不做。
- [旧记录缺 `spec`/`signal_type` 等字段] → 过滤端强制 `spec` 匹配（缺失即跳过）；前端对缺字段渲染降级（Tag 不显示、摘要空缺），不崩。
- [description 过长撑爆时间轴] → 前端 ellipsis 单行截断；全文仍在运维记录页。

## Migration Plan

纯增量字段（`timeline[]` 新增 `kind="admin"` 元素），无迁移。回滚 = revert 两文件改动，旧数据不受影响。

## Open Questions

（无——范围、详略、归并语义已与用户确认：告警+处置都展示、标题行+一句话摘要、pending 被最终记录替代、fast-track 执行。）
