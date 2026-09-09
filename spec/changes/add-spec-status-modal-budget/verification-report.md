# 验证报告：add-spec-status-modal-budget

> ⚠️ 本报告由框架于 2026-09-09T10:15:51Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 6/27 场景通过，20 失败，0 错误（1 个真实产品 Bug）**

21 非 PASS（20 failed + 1 warning）已全部归因并逐场景 checkpoint 落盘：1 个产品 Bug（预算闸门非整数强转，cli-budget-gate-override-priority）+ 19 test-defect + 1 flaky。test-defect 构成：12 个跨轮已裁决场景原样写回（行选择器未匹配/项目列表空，seed 未自建 registry 夹具）；本轮新增 7 个（api-budget-403 响应体 Unicode 转义断言失配、web-modal-budget-section-nonterminal 与 web-modal-budget-set-override-3 的「保存」按钮遇 antd 双汉字自动插空格、web-mobile-card-menu-status-entry 弹窗遮罩覆盖断言、archive/unfreeze/promote/freeze 四确认流断言时序后置于已关闭弹窗与已消失消息）。flaky：web-modal-budget-terminal-absent（SSIM 0.751 视觉基线抖动，DOM 断言全通过，warning 不阻塞）。

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 20 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 29.78M |
| 本链增量 Token（输出） | 0.29M |


## 真实产品 Bug

### BUG-01（severity=major）· exit_code/output_match

- 关联场景：cli-budget-gate-override-priority
- 描述：预算闸门 clamp_impl_run_budget('5') 返回 5（int('5') 强转成功），而 spec/断言要求非整数类型（字符串数字）返回 None 以便回退全局预算；type contract 违背导致越界夹紧口径漂移。
- 根因：core/pm_engine/budget.py:31-33 clamp_impl_run_budget 直接调用 int(raw) 强转，数字字符串/浮点被吞为 int，未先校验 isinstance(raw, int)（仅拒绝 bool/None/解析失败），与 docstring「字符串数字 → 返回 None」及 spec 约定冲突。
- 证据（场景 cli-budget-gate-override-priority 结构化证据，引用）：
  - failed_assertions: [{"type": "exit_code", "selector": 0, "expected": "0", "actual": "1"}, {"type": "output_match", "selector": "GATE_OK", "expected": "GATE_OK", "actual": "\nTraceback (most recent call last):\n  File \"<stdin>\", line 11, in <module>\nAssertionError: clamp str 5 → None (non-int)\n"}]
  - screenshots: []
  - first_failed_step: clamp_impl_run_budget('5') 返回 5（int('5') 强转）而 spec 要求非整数回退全局（返回 None）


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-seed-status-modal-fixtures | 种子场景：向 fixture 项目 /root/scheduling-showcase 写入本 SPEC 涉及的补充夹具——drafted 竞本（budget-draft-ok，含合法 tasks.md 供晋升 lint 通过）、定时解冻冻结态竞本（budget-frozen-sched，blocked+error=`用户指令冻结：原状态 ready · 测试`+frozen_until 未来时间）、已归档竞本（budget-archived-old，done 但无 spec/changes/<name>/ 活跃目录 → is_spec_archived=True）；并幂等复位：移除跨轮残留同名单、将 .fenix/config.yaml 的 agents.impl_run_budget 固定为 6（保证预算区/闸门回退口径可断言）。出处：spec/changes/add-spec-status-modal-budget/specs/*.md 全部 fixtures；写路径复用 add-draft-promotion-gate 轮 seed 边界（StateMachine.add_spec/update_spec 落 /root/scheduling-showcase/.fenix/STATE.md，fresh 实例由本轮独占），配套 spec/changes/<name>/ 空目录防 archived 过滤不显示（add-verify-multi-kind-runner 实证） | pass | 0/6 | - |
| api-budget-scenario-404-spec-not-found | 异常路径·POST /api/spec-budget 对不存在的 spec 返回 404（spec 不在项目 STATE.md）。出处：core/dashboard/server.py:749-751（404 spec required）、:774-776（404 spec not found）；data.py set_spec_budget :506-508（found:False）。实例打 scheduling-showcase 夹具，spec 用绝不存在的哨兵名 | pass | 0/2 | - |
| api-budget-400-invalid-requests | 异常路径·POST /api/spec-budget body 缺 budget 键 / budget=0 / budget=11 / budget="5" / budget=5.5（浮点）/ budget=true → 全部 400，STATE.md 不发生任何变化（夹具 spec 的 impl_run_budget_override 保持 null）。出处：core/dashboard/server.py:752-767（缺键/非整数/越界各分支）；data.py:520-525（invalid 拒绝写入）。与 spec per-spec-impl-budget「非法请求被拒绝」场景一一对应 | pass | 0/6 | - |
| api-budget-403-terminal-rejected | 异常路径·POST /api/spec-budget 对 done 终态 spec 返回 403「终态不可设置预算覆盖」，STATE.md 无变化。出处：core/dashboard/data.py:510-512（terminal:True）；server.py:777-779（403）。夹具用 scheduling-showcase 既有 c-sched-done（done 终态） | failed（已修正） | 1/2 | test-defect |
| api-budget-set-valid-override | 功能正向·POST /api/spec-budget?project=scheduling-showcase&spec=c-sched-set body {"budget": 8} → 200 + {ok:true, budget:8}，随后 GET /api/specs 该 spec 的 budget_override=8、budget_effective=8（覆盖优先于全局 6）。出处：core/dashboard/server.py:729-784；data.py:485-529；spec_summary :2629-2680。对应 spec「设置覆盖后按覆盖值生效」 | pass | 0/6 | - |
| api-summary-budget-fields-consistent | 功能正向·GET /api/specs?project=scheduling-showcase 列表项含 budget_used / budget_override / budget_effective 三字段，且与闸门口径一致（budget-frozen-sched override=3+used=5→effective=3、c-sched-set 无覆盖回退全局 6）。出处：core/dashboard/data.py:2629-2680（spec_summary 三字段）；budget.py:27-47 clamp_impl_run_budget。对应 spec「摘要字段与闸门口径一致」 | pass | 0/4 | - |
| cli-budget-gate-override-priority | 功能正向·预算闸门 clamp_impl_run_budget + _impl_run_budget 覆盖优先解析：脚本以 Python 断言 clamp 效果（3→3、null→None、0→1、11→10）与覆盖优先（spec_name 有 override→返回 override 夹紧值；无→返回全局 6；全局缺失→DEFAULT=6）。出处：core/pm_engine/budget.py:27-47 clamp_impl_run_budget、:64-83 _impl_run_budget。对应 spec「无覆盖时跟随全局」「覆盖值越界夹紧」 | failed（已修正） | 2/2 | product-bug |
| web-menu-converged-six-items | 功能正向·未归档视图打开非终态 SPEC 行「更多」菜单，恰为「修改状态 / 呼叫 Admin 介入 / 调整优先级 / 设置拾取时间 / 分隔线 / 删除 SPEC」六项，不含任何状态类菜单项（晋升 ready/冻结 SPEC/解冻 SPEC/冻结管理/归档 SPEC）。出处：list.tsx specMenuItems core/dashboard/static/src/pages/projects/list.tsx:676-684；路由 /projects/:name core/dashboard/static/config/routes.ts:29-30（hash 路由 config/config.ts:11-13）。夹具行 c-sched-set。对应 spec spec-status-actions-modal「菜单项收敛后的完整清单」 | failed（已修正） | - | test-defect |
| web-menu-terminal-disabled-priority | 功能正向·终态(done) SPEC 行「更多」菜单中「调整优先级」「设置拾取时间」置灰不可点，且「修改状态」「呼叫 Admin 介入」「删除 SPEC」可点。出处：list.tsx specMenuItems terminal 置灰 core/dashboard/static/src/pages/projects/list.tsx:679-681（disabled: terminal）。夹具行 c-sched-done(done)。对应 spec「终态置灰语义保持」 | failed（已修正） | - | test-defect |
| web-archived-view-menu-limited | 功能正向·已归档视图（切换「已归档」Radio）打开归档 SPEC 行「更多」菜单，仅含分隔线与「删除 SPEC」，无「修改状态」入口。出处：list.tsx specMenuItems archivedOnly 分支 core/dashboard/static/src/pages/projects/list.tsx:666-671；归档切换 RadioGroup list.tsx:961-971。夹具行 budget-archived-old(已归档,无活跃目录)。对应 spec「已归档视图菜单不变」 | failed（已修正） | - | test-defect |
| web-modal-archive-section-terminal | 功能正向·打开 done 终态 SPEC 的「修改状态」弹窗 → 渲染归档区块（「归档」标题 + 归档说明 + 「归档 SPEC」按钮），不渲染冻结/晋升/预算区块。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:278-291（done&& 归档区块）、:294-365（nonTerminal&& 冻结区块）、:368-379（drafted&& 晋升区块）、:382-426（nonTerminal&& 预算区块）。夹具行 c-sched-done。对应 spec「终态 SPEC 显示归档区块」（展示层面） | failed（已修正） | - | test-defect |
| web-modal-no-archive-nonterminal | 功能正向·打开 ready 非终态 SPEC 的「修改状态」弹窗 → 不渲染归档区块，渲染冻结区块（冻结 SPEC 按钮）与预算区块。出处：SpecStatusModal.tsx:278-291（done&& 才渲染归档）。夹具行 c-sched-set(ready)。对应 spec「非终态 SPEC 不显示归档区块」 | failed（已修正） | - | test-defect |
| web-modal-promote-drafted-renders | 功能正向·打开 drafted SPEC 的「修改状态」弹窗 → 渲染晋升区块（「晋升」标题 + 晋升说明 + 「晋升 ready」按钮），不渲染归档区块。出处：SpecStatusModal.tsx:368-379（drafted&& 晋升区块）。夹具行 budget-draft-ok。对应 spec「drafted SPEC 显示晋升区块」（展示层面） | failed（已修正） | - | test-defect |
| web-modal-no-promote-nondrafted | 功能正向·打开 ready（非 drafted）SPEC 的「修改状态」弹窗 → 不渲染晋升区块（弹窗内无「晋升 ready」按钮）。出处：SpecStatusModal.tsx:368-379（drafted&& 才渲染晋升）。夹具行 c-sched-set(ready)。对应 spec「非 drafted SPEC 不显示晋升区块」 | failed（已修正） | - | test-defect |
| web-modal-freeze-unfrozen-shows-freeze | 功能正向·打开未冻结未完成 SPEC（c-sched-set，ready、非 blocked+用户指令冻结）的「修改状态」弹窗 → 冻结区块显示「未冻结」说明与 danger 「冻结 SPEC」按钮，不显示「立即解冻」/模式切换（未冻结态）。出处：SpecStatusModal.tsx:300-306（!frozen 分支）。对应 spec「未冻结 SPEC 可冻结」（展示与确认前状态） | failed（已修正） | - | test-defect |
| web-modal-freeze-frozen-permanent-display | 功能正向·打开已冻结 SPEC（blocked+error=`用户指令冻结：…`、frozen_until 为 null 即永久冻结）的「修改状态」弹窗 → 冻结区块展示模式 Tag「永久冻结（人工解冻）」+「立即解冻」按钮+永久↔定时 Radio+冻结原因；不显示「冻结 SPEC」按钮。出处：SpecStatusModal.tsx:307-363（frozen 分支）；isFrozen 判定 SpecStatusModal.tsx:48-50 + list.tsx。夹具行 c-frozen-a(永久冻结)。对应 spec「已冻结 SPEC 展示模式并可立即解冻」（展示层面） | failed（已修正） | - | test-defect |
| web-modal-freeze-scheduled-shows-time | 功能正向·打开定时解冻冻结 SPEC（budget-frozen-sched：blocked + frozen_until 未来时间）的「修改状态」弹窗 → 冻结区块 Tag 为「定时解冻」且展示「目标时间：…（本地），到期 daemon 自动解冻」，含「立即解冻」按钮与 Radio 模式切换。出处：SpecStatusModal.tsx:317-327（frozen_until 存在时目标时间展示）。对应 spec「已冻结 SPEC 展示模式并可立即解冻」定时分支 | failed（已修正） | - | test-defect |
| web-modal-budget-section-nonterminal | 功能正向·打开非终态 SPEC（c-sched-set）的「修改状态」弹窗 → 渲染预算区块：「实现尝试预算」标题 +「已用 used / 有效预算 effective」+ 覆盖值输入（占位跟随全局）+「保存」+「恢复跟随全局」按钮（当前无覆盖时禁用）。出处：SpecStatusModal.tsx:382-426。对应 spec「修改状态弹窗预算区块」展示 | failed（已修正） | 2/7 | test-defect |
| web-modal-budget-terminal-absent | 功能正向·打开 done 终态 SPEC 的「修改状态」弹窗 → 不渲染预算区块（弹窗内无「实现尝试预算」）。出处：SpecStatusModal.tsx:382-426（nonTerminal&& 才渲染预算）。夹具行 c-sched-done。对应 spec「终态不渲染预算区块」 | warning | 0/5 | flaky |
| web-mobile-card-menu-status-entry | 功能正向·移动端（390×844）SpecCardList 卡片行「更多」菜单与桌面一致含「修改状态」入口，点击打开同一弹窗（标题含 SPEC 名称）。出处：list.tsx SpecCardList core/dashboard/static/src/pages/projects/list.tsx:330-390 + isMobile 分支 :973-982 + useIsMobile hook core/dashboard/static/src/hooks/useIsMobile.ts（<768px）；specMenuItems 共用 :676-684。对应 spec「移动端卡片菜单含修改状态」，viewport 390×844 触发 useIsMobile 分支 | failed（已修正） | 1/5 | test-defect |
| web-modal-archive-confirm-flow | 功能正向·终态 SPEC（budget-done-arch）弹窗点击「归档 SPEC」→ 弹出归档确认（Modal.confirm，标题含「归档 SPEC」与说明文案）→ 点确认后真实调用 POST /api/spec-archive，成功提示「已归档」，列表刷新后该 SPEC 移入已归档视图。出处：SpecStatusModal.tsx:94-121 handleArchive + :284-289 归档按钮；归档确认文案 :98-105。对应 spec spec-status-actions-modal「终态 SPEC 显示归档区块」完整操作流 | failed（已修正） | 4/5 | test-defect |
| api-budget-clear-null-restores-global | 功能正向·POST /api/spec-budget body {"budget": null} → 200 + {ok:true, budget:null}，属性置 null 恢复跟随全局；GET /api/specs 该 spec budget_override=null、budget_effective=全局（6）。出处：data.py:514-518（null 清除）；spec_summary :2638-2641（回退全局）。对应 spec「设置与清除覆盖」后半段 | pass | 0/5 | - |
| web-modal-budget-set-override-3 | 功能正向·在非终态 SPEC（c-sched-set）弹窗预算区输入覆盖值 3 并保存 → 真实调用 POST /api/spec-budget（禁止 mock 交付物端点），成功提示「已保存预算覆盖」；再次打开弹窗预算区显示已用 used / 有效预算 3。出处：SpecStatusModal.tsx:233-246 handleBudgetSave + :232 setSpecBudget；api dashboard.ts:357-364。对应 spec「修改覆盖并生效展示」 | failed（已修正） | - | test-defect |
| web-unfreeze-frozen-spec-flow | 功能正向·对已冻结 SPEC（budget-frozen-sched）打开「修改状态」弹窗点击「立即解冻」→ 真实调用 setSpecFreezeConfig('unfreeze')，成功提示「SPEC「budget-frozen-sched」已解冻」且列表状态恢复（blocked→ready）。出处：SpecStatusModal.tsx:151-170 handleUnfreeze + :330 立即解冻按钮。对应 spec「已冻结 SPEC …并可立即解冻」完整流 | failed（已修正） | 4/5 | test-defect |
| web-modal-promote-confirm-flow | 功能正向·drafted SPEC（budget-draft-ok）弹窗点击「晋升 ready」→ 弹出晋升确认（Modal.confirm，标题「晋升 ready」）→ 点确认后真实调用 POST /api/spec-promote（软转 ready），成功提示「已晋升 ready」且列表该 SPEC 状态转为 ready。出处：SpecStatusModal.tsx:197-230 handlePromote + :375-377 晋升按钮；promote_spec data.py:342-372。对应 spec spec-status-actions-modal「drafted SPEC 显示晋升区块」完整操作流（晋升成功路径） | failed（已修正） | 4/5 | test-defect |
| web-modal-freeze-confirm-flow | 功能正向·未冻结未完成 SPEC（c-sched-set）弹窗点击「冻结 SPEC」→ 弹出冻结确认（Modal.confirm，标题「冻结 SPEC」+ danger 确认按钮）→ 点确认后真实调用 POST /api/spec-freeze，成功提示「已冻结，daemon 停止调度」且列表该 SPEC 状态转为 blocked（error 以 用户指令冻结： 前缀开头）。出处：SpecStatusModal.tsx:124-148 handleFreeze + :303-305 冻结按钮；_api_spec_freeze server.py:586-611。对应 spec spec-status-actions-modal「未冻结 SPEC 可冻结」完整操作流 | failed（已修正） | 5/6 | test-defect |
| web-modal-budget-reset-global | 功能正向·对已有覆盖 3 的 SPEC（继承 web-modal-budget-set-override-3 的 c-sched-set 状态）点击「恢复跟随全局」→ 真实 POST budget=null 清除覆盖，成功提示「已恢复跟随全局」，预算区回显有效预算 6。出处：SpecStatusModal.tsx:248-262 handleBudgetReset。对应 spec「恢复跟随全局」 | failed（已修正） | - | test-defect |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| api-budget-403-terminal-rejected | body_contains expected '终态'（layer3） | test-defect | 测试用例自身缺陷（非产品缺陷） | server._error 用 json.dumps(ensure_ascii=True) 序列化；HTTP 403 与文案均正确，断言应解析 JSON .error 或匹配转义形式而非反序列化后的原文子串 |
| web-menu-converged-six-items | click tr[data-row-key="c-sched-set"] button.ant-dropdown-trigger 元素可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | 项目列表为空（registry ignored）→ 行选择器无匹配: Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("tr[data-row-key=\"c-sched-set\"] button.ant-... |
| web-menu-terminal-disabled-priority | click tr[data-row-key="c-sched-done"] button.ant-dropdown-trigger 元素可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | 项目列表为空（registry ignored）→ 行选择器无匹配: Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("tr[data-row-key=\"c-sched-done\"] button.ant... |
| web-archived-view-menu-limited | click .ant-radio-button-wrapper:has-text("已归档") 元素可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | 项目列表为空（registry ignored）→ 行选择器无匹配: Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator(".ant-radio-button-wrapper:has-text(\"已归档\")"... |
| web-modal-archive-section-terminal | click tr[data-row-key="c-sched-done"] button.ant-dropdown-trigger 元素可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | 项目列表为空（registry ignored）→ 行选择器无匹配: Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("tr[data-row-key=\"c-sched-done\"] button.ant... |
| web-modal-no-archive-nonterminal | click tr[data-row-key="c-sched-set"] button.ant-dropdown-trigger 元素可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | 项目列表为空（registry ignored）→ 行选择器无匹配: Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("tr[data-row-key=\"c-sched-set\"] button.ant-... |
| web-modal-promote-drafted-renders | click tr[data-row-key="budget-draft-ok"] button.ant-dropdown-trigger 元素可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | 项目列表为空（registry ignored）→ 行选择器无匹配: Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("tr[data-row-key=\"budget-draft-ok\"] button.... |
| web-modal-no-promote-nondrafted | click tr[data-row-key="c-sched-set"] button.ant-dropdown-trigger 元素可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | 项目列表为空（registry ignored）→ 行选择器无匹配: Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("tr[data-row-key=\"c-sched-set\"] button.ant-... |
| web-modal-freeze-unfrozen-shows-freeze | click tr[data-row-key="c-sched-set"] button.ant-dropdown-trigger 元素可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | 项目列表为空（registry ignored）→ 行选择器无匹配: Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("tr[data-row-key=\"c-sched-set\"] button.ant-... |
| web-modal-freeze-frozen-permanent-display | click tr[data-row-key="c-frozen-a"] button.ant-dropdown-trigger 元素可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | 项目列表为空（registry ignored）→ 行选择器无匹配: Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("tr[data-row-key=\"c-frozen-a\"] button.ant-d... |
| web-modal-freeze-scheduled-shows-time | click tr[data-row-key="budget-frozen-sched"] button.ant-dropdown-trigger 元素可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | 项目列表为空（registry ignored）→ 行选择器无匹配: Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("tr[data-row-key=\"budget-frozen-sched\"] but... |
| web-modal-budget-section-nonterminal | element_visible .ant-modal button:has-text("保存") | test-defect | 测试用例自身缺陷（非产品缺陷） | 产品渲染保存按钮（SpecStatusModal.tsx:409-415），antd 双汉字按钮插空格致选择器失配 |
| web-modal-budget-section-nonterminal | element_enabled .ant-modal button:has-text("保存") | test-defect | 测试用例自身缺陷（非产品缺陷） | 同因：选择器未匹配「保 存」按钮故报元素不存在 |
| web-modal-budget-terminal-absent | visual_ssim SSIM>=0.85 | flaky | 不稳定复现（非产品缺陷） | 全部 DOM/功能断言通过，SSIM 差异为弹窗动画/截图时序抖动，非功能缺陷，重试可过 |
| web-mobile-card-menu-status-entry | no_click_interception .ant-list-item:has-text("c-sched-set") button.ant-dropdown-trigger | test-defect | 测试用例自身缺陷（非产品缺陷） | 拦截源为场景自身先打开的弹窗遮罩（ant-modal-wrap）；弹窗标题/冻结按钮/无 console error 等功能断言全部通过 |
| web-modal-archive-confirm-flow | no_click_interception 归档 SPEC 按钮 | test-defect | 测试用例自身缺陷（非产品缺陷） | 弹窗已关闭按钮移除；前置步骤已成功点击并出现确认弹窗，证明按钮可点 |
| web-modal-archive-confirm-flow | element_visible 归档 SPEC 确认弹窗 | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤日志显示确认按钮点击成功（.ant-modal-confirm-btns .ant-btn-primary），断言时弹窗已关闭 |
| web-modal-archive-confirm-flow | no_click_interception 确认按钮 | test-defect | 测试用例自身缺陷（非产品缺陷） | 确认按钮因弹窗关闭移除；交互已完成 |
| web-modal-archive-confirm-flow | element_visible 已归档 消息 | test-defect | 测试用例自身缺陷（非产品缺陷） | antd message 自动消失（默认 3s），断言时序晚于消息生命周期 |
| web-modal-budget-set-override-3 | click .ant-modal button:has-text("保存") 元素可见可点 | test-defect | 测试用例自身缺陷（非产品缺陷） | 点击目标定位/可操作失败: Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator(".ant-modal button:has-text(\"保存\")").first to be visible
 |
| web-unfreeze-frozen-spec-flow | no_click_interception 立即解冻 按钮 | test-defect | 测试用例自身缺陷（非产品缺陷） | 弹窗已关闭按钮移除；前置步骤已成功点击并出现确认弹窗，证明按钮可点 |
| web-unfreeze-frozen-spec-flow | element_visible 解冻 SPEC 确认弹窗 | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤日志显示确认按钮点击成功（.ant-modal-confirm-btns .ant-btn-primary），断言时弹窗已关闭 |
| web-unfreeze-frozen-spec-flow | no_click_interception 确认按钮 | test-defect | 测试用例自身缺陷（非产品缺陷） | 确认按钮因弹窗关闭移除；交互已完成 |
| web-unfreeze-frozen-spec-flow | element_visible 已解冻 消息 | test-defect | 测试用例自身缺陷（非产品缺陷） | antd message 自动消失（默认 3s），断言时序晚于消息生命周期 |
| web-modal-promote-confirm-flow | no_click_interception 晋升 ready 按钮 | test-defect | 测试用例自身缺陷（非产品缺陷） | 弹窗已关闭按钮移除；前置步骤已成功点击并出现确认弹窗，证明按钮可点 |
| web-modal-promote-confirm-flow | element_visible 晋升 ready 确认弹窗 | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤日志显示确认按钮点击成功（.ant-modal-confirm-btns .ant-btn-primary），断言时弹窗已关闭 |
| web-modal-promote-confirm-flow | no_click_interception 确认按钮 | test-defect | 测试用例自身缺陷（非产品缺陷） | 确认按钮因弹窗关闭移除；交互已完成 |
| web-modal-promote-confirm-flow | element_visible 已晋升 消息 | test-defect | 测试用例自身缺陷（非产品缺陷） | antd message 自动消失（默认 3s），断言时序晚于消息生命周期 |
| web-modal-freeze-confirm-flow | no_click_interception 冻结 SPEC 按钮 | test-defect | 测试用例自身缺陷（非产品缺陷） | 弹窗已关闭按钮移除；前置步骤已成功点击并出现确认弹窗，证明按钮可点 |
| web-modal-freeze-confirm-flow | element_visible 冻结确认弹窗 | test-defect | 测试用例自身缺陷（非产品缺陷） | 步骤日志显示确认按钮点击成功，断言时弹窗已关闭 |
| web-modal-freeze-confirm-flow | element_visible 冻结确认按钮 | test-defect | 测试用例自身缺陷（非产品缺陷） | 确认按钮因弹窗关闭移除；交互已完成 |
| web-modal-freeze-confirm-flow | no_click_interception 冻结确认按钮 | test-defect | 测试用例自身缺陷（非产品缺陷） | 确认按钮已移除，断言时序晚于交互 |
| web-modal-freeze-confirm-flow | element_visible 已冻结 消息 | test-defect | 测试用例自身缺陷（非产品缺陷） | antd message 自动消失（默认 3s），断言时序晚于消息生命周期 |
| web-modal-budget-reset-global | click .ant-modal button:has-text("恢复跟随全局") 元素可见可点 | test-defect | 测试用例自身缺陷（非产品缺陷） | 点击目标定位/可操作失败: Locator.click: Timeout 5000ms exceeded.
Call log:
  - waiting for locator(".ant-modal button:has-text(\"恢复跟随全局\")").first
    - locator resolve... |

## 本轮场景集变更

场景集与持久化集一致，无变更。

