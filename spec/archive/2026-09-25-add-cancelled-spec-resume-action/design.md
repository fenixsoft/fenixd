# Design — add-cancelled-spec-resume-action

## Context

2026-09-21 实证：fix-impl-code-review-writepath 的实现 run 被 Dashboard 取消后，daemon 写
`{error: "run 被人工取消：…", _cancelled_hold: true}`，status 保持原态。此后恢复链
（`recover_interrupted` state_machine ~1227 显式跳过）、stuck 检测、孤儿恢复全部豁免，
SPEC 永久悬置。恢复的唯一合法出口是「显式复位」——人工执行过一次，需要
`update_spec` 一次性携带 status（自动清 hold）+ branch + implementer_run +
`_recovery_resume: true` + 计数归零 + `write_scheduling_kick`，缺任何一项都有后果：

- 漏 `_recovery_resume`/branch → dispatch 入口「新轮次派发清除旧锚点」→ 从 main 克隆
  新分支，保留分支上的已提交成果脱钩（fenixd-resume-preserved-branch-recipe 事故实证）；
- 漏 scheduling_kick → 等 30 分钟 poll_interval 周期扫描。

冻结终止路径（`unfreeze_spec` + `_frozen_hold`）已有同构的「解冻续做」接线
（`_resolve_preserved_branch` 共享判定），本 spec 把取消保持态补齐为对称的界面出口。

## Goals / Non-Goals

**Goals:**
- 取消保持态 SPEC 可在 Dashboard 一键恢复，默认走保留分支续做，不丢已提交成果；
- 恢复动作对无锚点/零提交/载体不可用的 SPEC 降级普通重派并如实告知；
- 界面可见该状态（摘要/详情下发 `cancelled_hold`）。

**Non-Goals:**
- 不改 daemon 派发与恢复链本体（`_recovery_resume` 消费、`_resolve_preserved_branch`
  判定均为既有单点，只做接线）；
- 不做批量恢复、不做「取消 run」入口位置调整（run 页已有）；
- 不处理 `_frozen_hold`（解冻续做已有既有路径，语义不同不合并）。

## Decisions

### D1. 动作落点：dashboard admin action + POST 路由（对齐 freeze-config 家族）

`resume_cancelled_spec(project_root, spec)` 放 `core/dashboard/data/admin_actions.py`，
路由 `POST /api/spec-resume` 挂 `spec_routes.py` + `base.py` 路由表——与
`spec-unfreeze` / `spec-activate` 同层同型。复用 `parse_state` + `StateMachine` +
就地构造 `WorktreeManager`。

**保持态判据 MUST 用归一化布尔读值，禁止裸真值判定**：dashboard 侧
`core/dashboard/data/state.py:parse_state` **只**对 `frozen` 归一化（`state.py:37-46`），
`_cancelled_hold` 不在其中；STATE.md 实际序列化为 Python 字面量
（本仓库 `.fenix/STATE.md:140` 即 `- _cancelled_hold: False`），故
`entry.get("_cancelled_hold")` 在 dashboard 读路径上常是真值字符串 `"False"`——
裸 `bool()` 会把**每条带该字段的非保持 SPEC** 判成保持态。因此：
- 入口判定与摘要字段 MUST 经同一归一化（`str(v).strip().lower() in ("true","1","yes")`，
  与 `parse_state` 对 `frozen` 的口径逐字一致），或把 `_cancelled_hold` 直接登记进
  `core/dashboard/data/state.py` 的归一化表（选后者时该文件须进 Deliverables）；
  参照 `is_spec_frozen` 的防御式写法（`entry.get("frozen") is True`）。
- `StateMachine` 侧（`state_machine.py:357-359`）已归一化该字段，但 dashboard 独立
  进程走的是 dashboard 解析器，两者不可互推。

**WorktreeManager 构造失败（载体工具不可用）时 MUST NOT 走降级清锚点**：该情形下
三层保留判定根本未运行，「无可保留分支」没有依据，而清 `branch`/`implementer_run`
会把仍可续做的保留分支从 STATE 脱钩（正是本 SPEC 要消除的事故面）。该情形 MUST
fail-closed 拒绝：`{ok: False, reason: "worktree 管理器不可用，无法判定保留分支"}`，
STATE 零变更、可重试——与 `unfreeze_spec` 先例实际行为一致（其 wm 为 None 时
跳过续做判定，但**不清锚点**）。`degraded` 仅当共享判定**真正运行过**并给出
「无锚点 / 零提交 / 载体不可用」结论时才成立。

### D2. 保留判定复用 `_resolve_preserved_branch`，禁止平行副本

调用 `StateMachine._resolve_preserved_branch(spec, entry, project_root, wm,
context="Cancel-hold resume")`。判定通过（分支在册 + `rev-list main..branch` 非空 +
`resolve_resume_site` 三态载体可用）→ 写保留续做集：

```
{status: ready, error: "Recovered from cancelled hold (resume preserved branch)",
 branch: <解析分支>, implementer_run: <原锚点>, _recovery_resume: True,
 tester_run: None, _retry_count: 0,
 _merge_fp: None, _merge_streak: 0,
 _redispatch_same_cause_streak: 0, _redispatch_cause_fp: None}
```

收口字段集对齐既有续做先例 `_recovery_preserve_spec`（`state_machine.py:1610-1620`
写 `tester_run: None` + `_merge_fp: None` + `_merge_streak: 0` + `_retry_count: 0`
+ `_redispatch_*`）。MUST 与先例同集，避免「恢复续做」两种入口产出不同 STATE 形状：
残留 `tester_run` 会让恢复后的轮次被误读为在飞验证锚点，残留 `_merge_streak`
会被 `admin_monitor._detect_merge_streak`（`admin_monitor.py:1475-1481`）当作
merge-back 反复失败而误告警。

status 在 updates 中即由 `update_spec` 自动清 `_cancelled_hold`（既有 D4 语义，
`state_machine.py:728`），不单独写。判定**运行过且**不通过 → 降级集：
`{status: ready, error: <降级留痕>, branch: None, implementer_run: None}`
（不置 `_recovery_resume`）+ WARNING 留痕 + 返回 `degraded: true` + 原因。
载体工具不可用（wm 构造失败）不是降级理由，MUST 按 D1 末尾 fail-closed 拒绝。

### D3. 即时唤醒：write_scheduling_kick 直用

复用 `core.signals.write_scheduling_kick`（与 `activate_spec` 同一通路）。写入失败
如实回传 warning，STATE 已变更不回滚（语义对齐 spec-activate 的 D3 诚实回报）。
`scheduling_kick` 目录不存在时由写入方创建。

### D4. 前端：摘要字段 + 弹窗区块

- `summary.py` 列表摘要组装处新增 `"cancelled_hold": <归一化布尔>`——**MUST NOT 写
  `bool(entry.get("_cancelled_hold"))`**：dashboard 解析器只归一化 `frozen`
  （`core/dashboard/data/state.py:37-46`），文本 `False` 是**真值字符串**，裸 `bool()`
  会把存量条目误标为保持态（本仓库 `.fenix/STATE.md:140/182/226/269/696` 即为
  `- _cancelled_hold: False`）。归一化口径与 `parse_state` 对 `frozen` 逐字一致
  （`str(v).strip().lower() in ("true","1","yes")`），或先把 `_cancelled_hold` 登记进
  `state.py` 归一化表（该文件随之进 Deliverables）。`spec_detail` 同步透传同口径值。
- `_ENTRY_SIG_KEYS`（`summary.py:437-449`）MUST 增列 `_cancelled_hold`：该白名单是
  `_entry_fingerprint` 的唯一取值源，摘要缓存按指纹判定失效；`spec_summary` 新增读取
  该字段后不登记即违反其自身「宁多勿漏：与实际读 entry 的字段一一对应」的契约，
  会出现「仅保持标记变化」时返回陈旧摘要。
- `dashboard.ts` 新增 `resumeSpec(project, spec)` API 封装（POST `/api/spec-resume`），
  并在既有 `SpecSummary` 接口（`dashboard.ts:243-262`，`frozen?: boolean` 处）新增
  `cancelled_hold?: boolean`——弹窗以 `SpecSummary` 为 props 类型（`SpecStatusModal.tsx:47-53`），
  缺该字段声明时 `summary?.cancelled_hold` 直接 TS2339、`npm run build` 失败。
- `SpecStatusModal.tsx` 新增区块，渲染条件：`summary?.cancelled_hold && nonTerminal`
  （`nonTerminal` 为既有派生变量）。确认文案明示「将复位 ready、按保留分支续做、
  消耗一次实现尝试预算；无保留分支时全新重派」。降级返回走独立 message 提示。

### D5. 测试

- 后端：`tests/test_cancelled_spec_resume.py`（新增）——命中/降级/非保持态幂等拒绝/
  冻结拒绝/终态拒绝/STATE 落点断言（frozen spec 的 status 更新剥离依赖既有保护，
  本动作对冻结态在入口即拒绝）。mock WorktreeManager 同既有 dashboard action 测试范式。
- MUST 含两条负例：① STATE 文本写作 `_cancelled_hold: False`（大写 F，同存量条目）
  时摘要 `cancelled_hold` 为 `false`、动作幂等拒绝——防裸真值判定回归；
  ② WorktreeManager 构造失败时动作拒绝且 STATE 逐字段零变更（不得降级清锚点）。
- 前端构建产物不进测试断言（dist 运行时重建）。

## Risks / Trade-offs

- **误触恢复烧预算**：恢复=立即派发实现 run。缓解：确认弹窗文案明示预算消耗；预算
  闸门在 dispatch 前置检查（`_check_impl_budget_exhausted`），耗尽时 spec 落 blocked
  并告警，不在动作内重复实现。
- **保留分支陈旧**（取消后主树已前进）：续做分支落后 main。既有 repair/re-merge 机制
  兜底，本 spec 不额外处理（与重启恢复续做同语义、同风险面，非新增）。
- **与 daemon 并发写 STATE**：动作经 StateMachine flock + 原子 rename，与 daemon
  写侧同锁；`_resolve_preserved_branch` 全程只读。风险与既有 spec-unfreeze 等同。
