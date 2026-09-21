# Tasks — add-cancelled-spec-resume-action

## Deliverables

```yaml
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/dashboard/data/summary.py
  kind: modify
- path: core/dashboard/data/state.py
  kind: modify
- path: core/dashboard/routes/spec_routes.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx
  kind: modify
- path: tests/test_cancelled_spec_resume.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1 后端恢复动作

- [ ] 1.1 `core/dashboard/data/admin_actions.py` 新增 `resume_cancelled_spec(project_root, spec)`：入口校验（不存在 → found:False；终态 done/pushed → terminal 拒绝；`frozen` 结构化或文本前缀命中 → 冻结拒绝；`_cancelled_hold` 非 true → 幂等拒绝附原因），全部拒绝路径 STATE 零变更。保持态判据 MUST 走归一化布尔（`str(v).strip().lower() in ("true","1","yes")`，或把 `_cancelled_hold` 登记进 `core/dashboard/data/state.py` 归一化表），MUST NOT 裸真值判定——dashboard 解析器只归一化 `frozen`，文本 `False` 是真值字符串，裸判定会误纳非保持态 SPEC 并强置 ready
- [ ] 1.2 命中分支：调 `StateMachine._resolve_preserved_branch`（context="Cancel-hold resume"）解析保留分支；通过则单次原子写 `{status: ready, error: 恢复留痕, branch, implementer_run, _recovery_resume: True, tester_run: None, _retry_count: 0, _merge_fp: None, _merge_streak: 0, _redispatch_same_cause_streak: 0, _redispatch_cause_fp: None}`（收口字段集与 `state_machine.py:1610-1620` 续做先例同集）
- [ ] 1.3 降级分支：**仅在共享判定真正运行过**且不通过时 WARNING 留痕并原子写 `{status: ready, error: 降级留痕, branch: None, implementer_run: None}`（不置 `_recovery_resume`），返回 `degraded: true` + 原因；WorktreeManager 构造失败（判定未运行）MUST 拒绝 `{ok:false, reason:"worktree 管理器不可用，无法判定保留分支"}` 且 STATE 零变更（MUST NOT 降级清锚点丢保留分支）
- [ ] 1.4 成功（含降级）后调 `core.signals.write_scheduling_kick`；写入失败回传 `warning` 字段不回滚 STATE；返回形状对齐 spec-activate 家族（`{ok, found, spec, degraded?, warning?, reason?}`）

## 2 摘要字段下发

- [ ] 2.1 `core/dashboard/data/summary.py` 列表摘要组装处新增 `"cancelled_hold": <归一化布尔>`（MUST NOT 用 `bool(entry.get("_cancelled_hold"))`：文本 `False` 为真值字符串，存量条目 `.fenix/STATE.md:140` 即 `- _cancelled_hold: False`），注释说明为取消保持态前端渲染判据
- [ ] 2.2 `spec_detail` 响应透传同名字段（同口径取值），与列表摘要零漂移
- [ ] 2.3 `core/dashboard/data/state.py`：把 `_cancelled_hold` 登记进 `parse_state` 归一化表（与 `frozen` 同分支同口径，`state.py:37-46`），使 dashboard 读路径不再依赖调用方各自归一
- [ ] 2.4 `summary.py` `_ENTRY_SIG_KEYS`（`summary.py:437-449`）增列 `_cancelled_hold`，维持「与实际读 entry 的字段一一对应」的缓存指纹契约

## 3 路由接线

- [ ] 3.1 `core/dashboard/routes/spec_routes.py` 新增 `_api_spec_resume`（POST `/api/spec-resume?project=&spec=`），错误语义对齐 spec-activate：project/spec 缺失 404、终态 403、幂等拒绝 200+`{ok:false, reason}`、成功 200+`{ok:true, spec, degraded?, warning?}`
- [ ] 3.2 `core/dashboard/routes/base.py` 路由表注册 POST `/api/spec-resume` 条目

## 4 前端

- [ ] 4.1 `core/dashboard/static/src/services/dashboard.ts` 新增 `resumeSpec` 封装（POST `/api/spec-resume`，透传 ok/degraded/warning/reason），并在 `SpecSummary` 接口（`dashboard.ts:243-262`）新增 `cancelled_hold?: boolean`——弹窗 props 即该类型，缺声明时 `summary?.cancelled_hold` 编译失败
- [ ] 4.2 `SpecStatusModal.tsx` 新增「恢复运行」区块：渲染条件 `summary?.cancelled_hold && nonTerminal`；文案含保留分支续做/降级全新重派双语义与「消耗一次实现尝试预算」提示；Modal.confirm 确认后调用端点，成功/降级/拒绝分支分别 message 反馈并刷新
- [ ] 4.3 `npm run build` 重建 dashboard 产物（dist 为 gitignored 运行时产物，随构建刷新）

## 5 测试与回归

- [ ] 5.1 新增 `tests/test_cancelled_spec_resume.py`：命中（STATE 落点逐字段断言：ready/branch/_recovery_resume/hold 清除/tester_run 清空/计数归零 + kick 文件存在）、降级（degraded:true、无 `_recovery_resume`、锚点清空）、非保持态幂等拒绝（STATE 零变更）、冻结拒绝、终态拒绝
- [ ] 5.2 负例①：STATE 文本写作 `_cancelled_hold: False`（大写 F，同存量条目）时摘要 `cancelled_hold` 为 `false` 且动作幂等拒绝；负例②：WorktreeManager 构造失败时动作拒绝、STATE 逐字段零变更（MUST NOT 降级清锚点）
- [ ] 5.3 `python3 -m pytest tests/test_cancelled_spec_resume.py tests/test_cancel_holdstate_recovery.py tests/test_dashboard_freeze.py -q` 全绿（与既有取消保持/冻结测试无回归冲突）
