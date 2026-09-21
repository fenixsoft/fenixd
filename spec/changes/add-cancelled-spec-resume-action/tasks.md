# Tasks — add-cancelled-spec-resume-action

## Deliverables

```yaml
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/dashboard/data/summary.py
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

- [ ] 1.1 `core/dashboard/data/admin_actions.py` 新增 `resume_cancelled_spec(project_root, spec)`：入口校验（不存在 → found:False；终态 done/pushed → terminal 拒绝；`frozen` 结构化或文本前缀命中 → 冻结拒绝；`_cancelled_hold` 非 true → 幂等拒绝附原因），全部拒绝路径 STATE 零变更
- [ ] 1.2 命中分支：调 `StateMachine._resolve_preserved_branch`（context="Cancel-hold resume"）解析保留分支；通过则单次原子写 `{status: ready, error: 恢复留痕, branch, implementer_run, _recovery_resume: True, _retry_count: 0, _redispatch_same_cause_streak: 0, _redispatch_cause_fp: None}`
- [ ] 1.3 降级分支：判定不通过时 WARNING 留痕并原子写 `{status: ready, error: 降级留痕, branch: None, implementer_run: None}`（不置 `_recovery_resume`），返回 `degraded: true` + 原因
- [ ] 1.4 成功（含降级）后调 `core.signals.write_scheduling_kick`；写入失败回传 `warning` 字段不回滚 STATE；返回形状对齐 spec-activate 家族（`{ok, found, spec, degraded?, warning?, reason?}`）

## 2 摘要字段下发

- [ ] 2.1 `core/dashboard/data/summary.py` 列表摘要组装处新增 `"cancelled_hold": bool(entry.get("_cancelled_hold")) if entry else False`，注释说明为取消保持态前端渲染判据
- [ ] 2.2 `spec_detail` 响应透传同名字段（同口径取值），与列表摘要零漂移

## 3 路由接线

- [ ] 3.1 `core/dashboard/routes/spec_routes.py` 新增 `_api_spec_resume`（POST `/api/spec-resume?project=&spec=`），错误语义对齐 spec-activate：project/spec 缺失 404、终态 403、幂等拒绝 200+`{ok:false, reason}`、成功 200+`{ok:true, spec, degraded?, warning?}`
- [ ] 3.2 `core/dashboard/routes/base.py` 路由表注册 POST `/api/spec-resume` 条目

## 4 前端

- [ ] 4.1 `core/dashboard/static/src/services/dashboard.ts` 新增 `resumeSpec` 封装（POST `/api/spec-resume`，透传 ok/degraded/warning/reason）
- [ ] 4.2 `SpecStatusModal.tsx` 新增「恢复运行」区块：渲染条件 `summary?.cancelled_hold && nonTerminal`；文案含保留分支续做/降级全新重派双语义与「消耗一次实现尝试预算」提示；Modal.confirm 确认后调用端点，成功/降级/拒绝分支分别 message 反馈并刷新
- [ ] 4.3 `npm run build` 重建 dashboard 产物（dist 为 gitignored 运行时产物，随构建刷新）

## 5 测试与回归

- [ ] 5.1 新增 `tests/test_cancelled_spec_resume.py`：命中（STATE 落点逐字段断言：ready/branch/_recovery_resume/hold 清除/计数归零 + kick 文件存在）、降级（degraded:true、无 `_recovery_resume`、锚点清空）、非保持态幂等拒绝（STATE 零变更）、冻结拒绝、终态拒绝
- [ ] 5.2 `python3 -m pytest tests/test_cancelled_spec_resume.py tests/test_cancel_holdstate_recovery.py -q` 全绿（与既有取消保持测试无回归冲突）
