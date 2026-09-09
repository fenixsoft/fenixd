# add-spec-status-modal-budget 任务清单

## Deliverables

```yaml
- path: core/pm_engine/budget.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx
  kind: new
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: tests/test_per_spec_impl_budget.py
  kind: new
- path: tests/test_dashboard_budget_api.py
  kind: new
- path: tests/test_dashboard_data.py
  kind: modify
```

## 1. 后端：per-spec 预算覆盖机制

- [x] 1.1 `core/pm_engine/budget.py`：抽出预算夹紧纯函数（int 归一 + 1-10 夹紧，模块级可导出）；`_impl_run_budget` 签名改为 `(spec_name: str | None = None)`——spec_name 非空时优先读 STATE 条目 `impl_run_budget_override`（可解析整数→夹紧使用；None/非法/缺失→回退），回退链保持现状（全局 config → DEFAULT_IMPL_RUN_BUDGET）
- [x] 1.2 `core/pm_engine/budget.py`：三处 `_impl_run_budget()` 调用点（`_increment_impl_run_budget_used`、`_exempt_dead_run_budget`、`_check_impl_budget_exhausted`）补传 spec_name；确认耗尽冻结文案与 impl_budget_exhausted 告警 evidence 中的 budget 输出为有效预算
- [x] 1.3 `core/dashboard/data.py`：新增 `set_spec_budget(project_root, spec, budget)`——404 not found / budget=null 清除（属性置 null）/ 1-10 整数写入 `impl_run_budget_override` / 终态 done/pushed 拒绝（terminal 标记）/ 经 `StateMachine.update_spec` 写入，返回形状对齐 `set_spec_start_after`
- [x] 1.4 `core/dashboard/data.py`：`spec_summary` 新增 `budget_used`（`_impl_run_budget_used` 容错读，缺省 0）、`budget_override`（覆盖属性容错读，非法视为 null）、`budget_effective`（引用 budget.py 夹紧纯函数按「覆盖>全局>缺省」同源解析，全局 config 经 dashboard 侧既有 config 读取器）

## 2. 后端：预算设置 API

- [x] 2.1 `core/dashboard/server.py`：新增 `POST /api/spec-budget?project=<name>&spec=<name>` 路由与处理函数（模式对齐 `_api_spec_priority`）——body `{"budget": int|null}`；缺键/非整数（含 bool、浮点、字符串数字）/越界 → 400；spec 不存在 → 404；终态 → 403；成功 → 200 `{ok: true, budget: <值|null>}`；模块 docstring 端点清单同步
- [x] 2.2 确认修改预算不触碰 `_impl_run_budget_used`（只写覆盖属性，已用计数归对账组件管辖），在 `set_spec_budget` docstring 注明该边界

## 3. 前端：服务层与菜单收敛

- [x] 3.1 `core/dashboard/static/src/services/dashboard.ts`：新增 `setSpecBudget(project, spec, budget: number | null)`，模式对齐 `setSpecStartAfter`
- [x] 3.2 `core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx`（新建）：受控 Modal 组件（props：project/spec/open/onClose/summary/onDone），按状态条件渲染四区块——归档区（done/pushed，确认文案与 archiveSpec 调用对齐现 handleArchiveSpec）；冻结区（非终态：未冻结→冻结确认按钮 freezeSpec；已冻结→模式展示含定时目标时间与冻结原因 + 立即解冻 + 永久↔定时切换 setSpecFreezeConfig）；晋升区（drafted，确认与 lint 违规明细展示对齐现 handlePromoteSpec）；预算区（非终态：used/effective 展示、1-10 覆盖输入预填、保存 setSpecBudget、恢复跟随全局=null）；区块分隔清晰、多确认操作防误触（danger 态二次点击或 Modal.confirm 分层取其一）
- [x] 3.3 `core/dashboard/static/src/pages/projects/list.tsx`：`specMenuItems` 收敛为「修改状态/呼叫 Admin 介入/调整优先级/设置拾取时间/分隔线/删除 SPEC」（已归档视图分支保持仅删除）；移除「晋升 ready」「冻结 SPEC/解冻 SPEC」「冻结管理」「归档 SPEC」菜单项与对应孤儿处理函数、孤儿「冻结管理」Modal；`onSpecMenu` 新增 status 分支挂载 SpecStatusModal；桌面 Table 与移动端 SpecCardList 共用不变

## 4. 测试

- [x] 4.1 `tests/test_per_spec_impl_budget.py`（新建）：夹紧纯函数边界（0/11/非整数/bool）；覆盖优先解析（覆盖生效/缺失回退全局/全局缺失回退缺省/覆盖非法回退）；三调用点日志与耗尽判定按有效预算（告警 evidence budget=有效值）；覆盖只影响目标 spec
- [x] 4.2 `tests/test_dashboard_budget_api.py`（新建）：/api/spec-budget 全分支——200 设置/清除、400 缺键与非法值矩阵、404、403 终态、STATE.md 只写覆盖属性不动 used
- [x] 4.3 `tests/test_dashboard_data.py`：`set_spec_budget` 返回形状与写盘断言；`spec_summary` 三预算字段（覆盖/无覆盖/非法覆盖三态，与闸门口径一致）

## 5. 验证与收尾

- [x] 5.1 全量跑新增与相关既有测试（test_dashboard_freeze / test_spec_scheduling / test_spec_archive 回归），零失败
- [x] 5.2 前端构建通过（`core/dashboard/static` 下 build/type-check 零错误）；dist 由框架 merge 后自动重建，不提交
- [x] 5.3 场景核对：对照 specs/per-spec-impl-budget 与 specs/spec-status-actions-modal 全部 Scenario 逐条自验（含移动端卡片菜单入口）

## 验证修复（第 1 轮失败）

- [x] 先复核失败有效性：逐条核对 `spec/changes/add-spec-status-modal-budget/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [x] 修复后重跑验证确认通过
