# 验证报告：add-verify-contract-autodraft

> ⚠️ 本报告由框架于 2026-09-08T09:13:32Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 10/23 场景通过，13 失败，0 错误（0 个真实产品 Bug）**

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 13 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 27.94M |
| 本链增量 Token（输出） | 0.39M |

## 真实产品 Bug

> 判定为 bug-found 但结果文件未携带结构化 bug 列表，以下为 report.json 中的失败场景明细。


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-healthy-contract-exit-0 | 健康契约（prepare/serve/ready 三段可执行）→ CLI 退出码 0，输出三段通过结果（源码: bin/fenix_verify_contract.py:68-85） | failed（已修正） | 5/5 | product-bug |
| cli-missing-contract-exit-1 | 契约文件不存在 → CLI 退出码 1，输出「不存在」错误（源码: bin/fenix_verify_contract.py:57-63） | pass | 0/2 | - |
| cli-invalid-yaml-exit-1 | 契约 YAML 解析失败（格式错误）→ CLI 退出码 1，输出解析错误（源码: core/verify_contract.py:302-327） | pass | 0/2 | - |
| cli-prepare-failure-exit-2 | prepare 脚本失败（exit 1）→ CLI 退出码 2，输出 prepare 失败详情（源码: core/verify_contract.py:364-373） | pass | 0/3 | - |
| cli-serve-root-not-exist-exit-3 | serve.root 指向不存在目录 → CLI 退出码 3，输出 serve 失败详情（源码: core/verify_contract.py:384-388） | failed（已修正） | 3/3 | product-bug |
| cli-ready-probe-fail-exit-4 | ready 就绪探针超时（静态服务返回 404 而非期望 200）→ CLI 退出码 4，输出 ready 失败详情（源码: core/verify_contract.py:433-438） | failed（已修正） | 3/3 | product-bug |
| cli-invalid-serve-kind-exit-5 | serve.kind 非法值（非 static/command）→ CLI 退出码 5，输出无效格式（源码: core/verify_contract.py:343-354） | pass | 0/3 | - |
| cli-pure-cli-contract-valid | 纯 cli 契约（无 serve 段）→ valid=True、prepare 通过、serve/ready 通过、CLI 退出码 0（源码: core/verify_contract.py:106-114） | pass | 0/3 | - |
| cli-default-cwd-no-args | 不带参数运行 → 以当前工作目录（CWD）为项目根进行校验（源码: bin/fenix_verify_contract.py:44-49） | failed（已修正） | 2/2 | product-bug |
| cli-signal-missing-contract | 契约不存在且 commands.start 为占位符 → 产生 verify_contract_missing 信号、spec 不被打回 plan（源码: core/pm_engine/verification.py:525-564） | failed（已修正） | 2/4 | test-defect |
| cli-signal-parse-error | 契约 YAML 解析失败（按无契约回退）→ 仍产生 verify_contract_missing 信号并标注 parse_error=是（源码: core/pm_engine/verification.py:535-539） | failed（已修正） | 2/4 | test-defect |
| cli-no-signal-on-prepare-failure | 契约存在但 prepare 构建失败 → 返回 prepare 失败（打回 plan 路径），不产生 verify_contract_missing 信号（源码: core/pm_engine/verification.py:493-496） | pass | 0/3 | - |
| web-autodraft-btn-visible-no-contract | 无契约时 Settings 项目级页面显示「AI 自动生成」按钮（源码: ProjectProfilePanel.tsx:217-232） | failed（已修正） | - | test-defect |
| web-autodraft-btn-visible-with-contract | 有效契约时「AI 自动生成」按钮仍可见，点击弹出覆盖确认弹窗（源码: ProjectProfilePanel.tsx:233-249） | failed（已修正） | - | test-defect |
| web-autodraft-dispatch-success | 无契约时点击「AI 自动生成」→ 确认 → 按钮进入 loading 状态 → 成功提示「已提交 AI 起草请求」（源码: ProjectProfilePanel.tsx:122-140） | failed（已修正） | - | test-defect |
| web-autodraft-overwrite-confirm | 有契约时点击「AI 自动生成」→ 弹出「⚠️ 覆盖现有契约」弹窗 → 确认 → dispatched 成功（源码: ProjectProfilePanel.tsx:233-249） | failed（已修正） | - | test-defect |
| web-autodraft-cancel-no-effect | 点击「AI 自动生成」→ 弹窗后点取消 → 无 API 调用、无 loading 状态（源码: ProjectProfilePanel.tsx:218-232 Popconfirm cancelText） | failed（已修正） | - | test-defect |
| web-placeholder-command-shows-autodraft | config commands.start 为占位符 echo 时（equivalent 无契约路径），Settings 项目级页面显示「AI 自动生成」按钮（源码: ProjectProfilePanel.tsx:217-232 渲染条件 yamlExists） | failed（已修正） | - | test-defect |
| api-autodraft-missing-project | POST /api/verify-yaml-autodraft 不带 project 参数 → 400 错误（源码: server.py:1222） | pass | 0/2 | - |
| api-autodraft-missing-contract-dispatched | POST /api/verify-yaml-autodraft project=X 无契约 → status=dispatched（源码: server.py:1238-1259） | pass | 0/3 | - |
| api-autodraft-existing-contract-skipped | POST /api/verify-yaml-autodraft project=X 有契约无 overwrite → status=skipped（源码: server.py:1229-1237） | pass | 0/3 | - |
| api-autodraft-overwrite-dispatched | POST /api/verify-yaml-autodraft project=X 有契约+overwrite=true → status=dispatched（源码: server.py:1238-1259） | pass | 0/3 | - |
| web-autodraft-reload-after-dispatch | autodraft 成功后点「重新加载」→ textarea 显示新契约内容（源码: ProjectProfilePanel.tsx:250-256） | failed（已修正） | - | test-defect |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| cli-signal-missing-contract | json_output path=reachable expected=false actual=true | test-defect | 测试用例自身缺陷（非产品缺陷） | fixture 将 test_scenarios.json 写入 CWD（f/.fenix/verify-progress/spec-a/），但代码从 project_root 解析路径（f/.fenix/verify-progress/spec-a/），路径不一致导致文件未找到，_ensure_app_reac... |
| cli-signal-missing-contract | json_output path=count expected=1 actual=0 | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上：文件未找到导致代码走 line 431 early return，跳过 line 525-564 信号写入逻辑 |
| cli-signal-parse-error | json_output path=reachable expected=false actual=true | test-defect | 测试用例自身缺陷（非产品缺陷） | fixture 将 test_scenarios.json 写入 CWD（f/.fenix/verify-progress/spec-a/），但代码从 project_root 解析路径（f/.fenix/verify-progress/spec-a/），路径不一致导致文件未找到，_ensure_app_reac... |
| cli-signal-parse-error | json_output path=count expected=1 actual=0 | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上：文件未找到导致代码走 line 431 early return，跳过 line 525-564 信号写入逻辑 |
| web-autodraft-btn-visible-no-contract | click .ant-select-item-option:nth-child(2) 选择项目 | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景假设 dashboard 项目下拉展开后第 2 项可点，实际 5000ms 未出现（element_not_found_or_not_actionable）；项目选择失败使 project state 未建立，后续 verify-yaml-section/autodraft 断言无法执行——场景对项目下拉行为... |
| web-autodraft-btn-visible-with-contract | click .ant-select-item-option:nth-child(2) 选择项目 | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景假设 dashboard 项目下拉展开后第 2 项可点，实际 5000ms 未出现（element_not_found_or_not_actionable）；项目选择失败使 project state 未建立，后续 verify-yaml-section/autodraft 断言无法执行——场景对项目下拉行为... |
| web-autodraft-dispatch-success | click .ant-select-item-option:nth-child(2) 选择项目 | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景假设 dashboard 项目下拉展开后第 2 项可点，实际 5000ms 未出现（element_not_found_or_not_actionable）；项目选择失败使 project state 未建立，后续 verify-yaml-section/autodraft 断言无法执行——场景对项目下拉行为... |
| web-autodraft-overwrite-confirm | click .ant-select-item-option:nth-child(2) 选择项目 | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景假设 dashboard 项目下拉展开后第 2 项可点，实际 5000ms 未出现（element_not_found_or_not_actionable）；项目选择失败使 project state 未建立，后续 verify-yaml-section/autodraft 断言无法执行——场景对项目下拉行为... |
| web-autodraft-cancel-no-effect | click .ant-select-item-option:nth-child(2) 选择项目 | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景假设 dashboard 项目下拉展开后第 2 项可点，实际 5000ms 未出现（element_not_found_or_not_actionable）；项目选择失败使 project state 未建立，后续 verify-yaml-section/autodraft 断言无法执行——场景对项目下拉行为... |
| web-placeholder-command-shows-autodraft | scroll [data-testid=verify-yaml-section] element_visible | test-defect | 测试用例自身缺陷（非产品缺陷） | ProjectProfilePanel.tsx:172 条件渲染 {project ? <Card data-testid=verify-yaml-section>... : null}。测试 click .ant-select-item-option 未实际选中项目（project state 为 undefi... |
| web-autodraft-reload-after-dispatch | scroll [data-testid=verify-yaml-section] element_visible | test-defect | 测试用例自身缺陷（非产品缺陷） | ProjectProfilePanel.tsx:172 条件渲染 {project ? <Card data-testid=verify-yaml-section>... : null}。测试 click .ant-select-item-option 未实际选中项目（project state 为 undefi... |

## 本轮场景集变更

当前稳定场景集共 31 个（第 1 轮）。

- 无理由缺失 8 个场景，已以持久化集补齐：api-autodraft-existing-contract-overwrite-dispatched、cli-invalid-serve-kind-exit-five、cli-missing-contract-exit-one、cli-ready-probe-fail-exit-four、cli-serve-root-not-exist-exit-three、cli-healthy-contract-exit-zero、cli-invalid-yaml-exit-one、cli-prepare-failure-exit-two

> ⚠️ 本轮 planner 产出缺少既有场景且无理由，已以持久化集补齐后继续验证（不中断验证）。

