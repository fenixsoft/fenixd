## Deliverables

```yaml
- path: core/dashboard/data/adjudication_choices.py
  kind: new
- path: core/admin_store.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/dashboard/routes/alert_routes.py
  kind: modify
- path: core/dashboard/data/__init__.py
  kind: modify
- path: core/pm_engine/budget.py
  kind: modify
- path: core/pm_engine/family.py
  kind: modify
- path: core/pm_engine/spec_review.py
  kind: modify
- path: core/pm_engine/verification/judge_gate.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/pm_engine/dispatch/fast_track.py
  kind: modify
- path: core/agent_runner/token_budget.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/overview/components/AlertBanner.tsx
  kind: modify
- path: agents/administrator.md
  kind: modify
- path: tests/test_adjudication_choices.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 裁决选项注册表与存储层

- [x] 1.1 新建 `core/dashboard/data/adjudication_choices.py`：静态注册表常量与 `choices_for(signal_type)` 查询函数，覆盖 proposal 信号表全部 8 类（每选项含 id/label/desc/action 四字段，id 同信号内唯一）；未注册信号返回空元组
- [x] 1.2 `core/dashboard/data/__init__.py` 导出注册表查询函数（对齐兄弟模块导出范式）
- [x] 1.3 `core/admin_store.py` 告警记录兼容可选 `choices` 字段：append 写入、去重路径不因新字段误判状态变化、读取路径无字段时按无选项处理（不抛异常）

## 2. 桶 2 信号发射点接线

- [x] 2.1 `core/pm_engine/budget.py`：实现预算耗尽冻结告警与 token_budget 告警写记录时携 `choices=choices_for(signal_type)`
- [x] 2.2 `core/pm_engine/family.py`：验证失败升级闸门冻结告警携 choices（continue_auto_fix 语义选项）
- [x] 2.3 `core/pm_engine/spec_review.py`：评审否决达上限（spec-review-rejected）冻结告警与评审器失败上限（spec-review-incomplete）告警各携对应 choices
- [x] 2.4 `core/pm_engine/verification/judge_gate.py`：judge 重跑上限告警携 choices
- [x] 2.5 `core/pm_engine/dispatch/queue.py` 与 `core/pm_engine/dispatch/fast_track.py`：同因重派熔断告警携 choices
- [x] 2.6 `core/agent_runner/token_budget.py`：token 预算告警携 choices（ignore/freeze_stop_loss/raise_budget）
- [x] 2.7 `core/worktree_manager/mergeback.py`：配置裁决类（build_artifact_paths_missing，`kind=SIGNAL`）发射携 choices（消费通道见 registry 消费通道约定，不经前端告警区渲染）；`core/admin_monitor.py` 仅作桶 0 确认：确认 stale_code/transient_break_storm/run_infra_failure/run_cancelled 发射路径不携带 choices

## 3. 三个新裁决动词

- [x] 3.1 `core/dashboard/data/admin_actions.py` 新增 `reset_verification`：前置校验（冻结/blocked 且属验证链信号）→ 删 `.fenix/verify-progress/<spec>/` 场景与进度文件（按 spec 名精确匹配，禁通配）→ 清 judge 重跑与验证失败轮计数 → 解冻并按 `resolve_env_blocked_reset_path` 推进（testing 直通道或 ready）→ 返回执行步骤明细
- [x] 3.2 `core/dashboard/data/admin_actions.py` 新增 `force_advance`：前置校验（冻结/blocked）→ 解冻 → 经 `update_spec` 显式豁免通道（updates 携 frozen=False+status；`blocked→done` 不在 VALID_TRANSITIONS，不走 transition）推进到 target_status（缺省 done）并清 error → 留痕标注「人工豁免推进」与 note
- [x] 3.3 `core/dashboard/data/admin_actions.py` 新增 `skip_review_gate`：前置校验（reviewing+frozen 且属评审器失败冻结）→ 解冻推进 ready → 留痕「人工授权跳过评审」；评审否决类冻结拒绝

## 4. alert-resolve 端点

- [x] 4.1 `core/dashboard/routes/alert_routes.py` 新增 `POST /api/alert-resolve`：校验告警存在且未 handled → 校验 choice_id（记录内 choices 优先，缺失回退注册表）→ 执行映射动作 → mark_handled → 落 disposition 留痕（choice_id/note/动作摘要）；任一步失败返回结构化错误且不标记 handled，错误含已执行步骤说明
- [x] 4.2 Administrator 处置记录消费：结构化字段 `choice_id`/`suggested_choice`（可选键，缺省 None 兼容），choice_id 非空时走与人工 resolve 相同的动作映射执行路径

## 5. 前端选择题交互

- [x] 5.1 `core/dashboard/static/src/services/dashboard.ts` 新增 `resolveAlert(project, alertId, choiceId, note)` 与 `AlertItem` 类型的 `choices?` 字段
- [x] 5.2 `core/dashboard/static/src/pages/projects/detail.tsx` 告警区：带 choices 告警渲染 Select 下拉+note 输入+执行按钮（loading 防重），成功转已处理态并提示留痕已写入，失败展示错误与已执行步骤且恢复可交互；无 choices 告警保持「知道了」
- [x] 5.3 abandon 与 skip_review_gate 选项执行前二次确认（Popconfirm/Modal 说明后果）
- [x] 5.4 `core/dashboard/static/src/pages/overview/components/AlertBanner.tsx` 同步选择题交互（overview 横幅形态）
- [x] 5.5 `npm run build` 重建 dist 并确认零报错（移动端 screen-xs 作用域回归自查）

## 6. Administrator 契约

- [x] 6.1 `agents/administrator.md` 增补 choices 消费契约段：处置先读注册表、结论优先表达为 choice_id+依据、注册表未覆盖时自由处置并回填 suggested_choice 建议

## 7. 测试

- [x] 7.1 新建 `tests/test_adjudication_choices.py`：注册表完整性（8 类信号选项集、未注册空集、字段四件套）；告警记录 choices 写入与无字段兼容；三个新动词的前置校验拒绝/成功路径/留痕断言；alert-resolve 端点闭环（成功/非法 choice/重复处置/动作失败不假成功）；发射点逐信号断言（注册表覆盖的 signal_type 写告警必含 choices；build_artifact_paths_missing 断言 mergeback SIGNAL 记录携 choices）
- [x] 7.2 存量测试回归：`pytest tests/test_dashboard_api.py tests/test_transient_backoff.py` 及受影响模块测试全绿（对齐测试目录既有命名与 fixture 范式，basetemp 遵循 conftest 约定）

## 验证修复（原地打回第 1 轮）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/add-human-adjudication-choices/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
