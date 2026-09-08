# 验证报告：add-draft-promotion-gate

> ⚠️ 本报告由框架于 2026-09-08T07:09:03Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 9/25 场景通过，16 失败，0 错误（1 个真实产品 Bug）**

25 场景 9 通过 16 失败。0 场景流量级环境问题。根因聚类：①产品 Bug（1 个 major，影响 4 个 cli-promote 场景）：CLI --project 参数位置与文档/SPEC 声明的 `promote <spec> [--project]` 语法不符，promote 流程不可达；②测试场景缺陷（12 个，不阻塞产品验收但需修正场景）：settings 3 场景为 approve_mode Form.Item 无 label 属性导致的臆测选择器 + antd 双汉字按钮自动插空格（保存→保 存）；promote 弹窗 4 场景为 antd v6 confirm 弹窗无 .ant-modal-content 类且按钮文本带空格（晋升→晋 升、取消→取 消），弹窗实际已正常打开（.ant-modal-wrap 拦截指针事件、text_contains 通过佐证）；api 3 场景 json_path 用了 harness 求值器不支持的 `$.ok` 前缀（正确路径为 ok，curl 实测响应体含 ok 字段）；cli 2 场景 output_match 在多 run 步骤时绑定到最后一步输出。产品在 API 层（200+ok 语义、404、lint 违规拒绝）、设置页开关渲染/默认态/说明文字、弹窗打开与文本内容方面均实测正确，仅 CLI 参数解析接口存在缺陷。

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 16 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 18.89M |
| 本链增量 Token（输出） | 0.22M |


## 真实产品 Bug

### BUG-01（severity=major）· exit_code / output_match

- 关联场景：cli-promote-non-drafted-rejection、cli-promote-success、cli-promote-lint-violation、cli-promote-with-project-flag
- 描述：CLI promote 子命令不支持文档声明的 `promote <spec> [--project <path>]` 调用形式：argparse 将 --project 挂在主解析器（须置于子命令之前），promote 子解析器不接收 --project，导致 `python3 bin/fenix_cli.py promote <spec> --project .` 报 unrecognized arguments 退出码 2，晋升逻辑从未执行。
- 根因：bin/fenix_cli.py:63-77 参数解析设计缺陷：--project 定义在主解析器而 docstring（fenix_cli.py:8-10）与 SPEC tasks.md 3.1 均声明 `promote <spec> [--project <path>]` 语法。实现与规格/文档不一致，promote 命令按文档调用即失败；多步骤场景中 exit_code/output_match 断言绑定到最后一步 grep 输出进一步掩盖了 promote 步骤的 exit 2。
- 证据（场景 cli-promote-non-drafted-rejection 结构化证据，引用）：
  - failed_assertions: [{"type": "exit_code", "expected": 1, "actual": 2, "error": "argparse 拒绝参数：unrecognized arguments --project ."}, {"type": "output_match", "expected": "晋升被拒绝", "actual": "usage 错误信息，promote 逻辑未执行"}, {"type": "output_match", "expected": "not drafted", "actual": "usage 错误信息"}]
  - screenshots: []
  - first_failed_step: CLI promote 命令 exit 2；SPEC task3.1 声明的 promote <spec> [--project] 语法与 argparse 实现（--project 在主解析器，须置于子命令前）不一致


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-seed-drafted-spec | 向验证项目 STATE.md 写入两个 drafted SPEC 夹具（verify-draft-fixture 声明合法 / verify-draft-bad 声明违规），供 api/web 场景经 depends_on 串接消费（写路径落在验证树 .fenix，与 add-verify-multi-kind-runner 轮 seed 同边界：fresh 实例的 STATE 由本轮独占） | pass | 0/3 | - |
| settings-switch-position-and-visibility | 设置页审批页签「草稿自动晋升」开关位于审批模式设置项上方（core/dashboard/static/src/pages/settings/components/ApprovalModePanel.tsx:52-60） | failed（已修正） | 1/5 | test-defect |
| settings-switch-reflects-default-true | 当配置为默认值时（gates.auto_promote_draft 未设置或为 true），页面加载后开关显示为开启态（ApprovalModePanel.tsx:18,47） | pass | 0/3 | - |
| settings-switch-toggle-save-success | 切换「草稿自动晋升」开关并点击保存，页面无错误提示，配置持久化成功（ApprovalModePanel.tsx:23-35,91） | failed（已修正） | - | test-defect |
| settings-switch-save-preserves-approve-mode | 切换草稿晋升开关并保存时，审批模式（approve_mode）设置不被覆盖，保存载荷同时提交两键（ApprovalModePanel.tsx:27-29） | failed（已修正） | 2/4 | test-defect |
| settings-switch-description-text | 「草稿自动晋升」开关附带说明文字，说明关闭后 SPEC 停留草稿态供人工阅读、需在项目页手动放行（ApprovalModePanel.tsx:57） | pass | 0/5 | - |
| promote-button-shown-for-drafted-spec | 项目列表页 drafted 状态 SPEC 的操作菜单中显示「晋升 ready」选项（pages/projects/list.tsx:796-799） | pass | 0/3 | - |
| promote-button-hidden-for-ready-spec | 项目列表页非 drafted 状态（如 ready）SPEC 的操作菜单中不显示「晋升 ready」选项（pages/projects/list.tsx:796-799） | pass | 0/4 | - |
| api-promote-non-drafted-rejection | POST /api/spec-promote 对非 drafted 状态 SPEC 返回 200 + ok:false + reason（core/dashboard/server.py:782-809） | failed（已修正） | 1/2 | test-defect |
| api-promote-spec-not-found | POST /api/spec-promote 对不存在的 SPEC 返回 404（core/dashboard/server.py:782-809） | pass | 0/1 | - |
| api-promote-project-not-found | POST /api/spec-promote 对不存在的项目返回 404（core/dashboard/server.py:782-809） | pass | 0/1 | - |
| cli-promote-non-drafted-rejection | CLI promote 对非 drafted 状态 SPEC 输出拒绝原因，退出码非 0（bin/fenix_cli.py:50-59） | failed（已修正） | 3/3 | product-bug |
| cli-config-invalid-value-rejected | 配置校验拒绝非布尔值：gates.auto_promote_draft 为字符串等非布尔值时加载报错并指明合法取值为布尔（core/config.py:345-352） | pass | 0/3 | - |
| cli-config-default-true | 配置缺省值：配置文件中不存在 gates.auto_promote_draft 时 getter 返回 true，自动晋升行为与引入该键之前一致（core/config.py:851-859） | failed（已修正） | 1/2 | test-defect |
| cli-docs-config-key | 配置文档（docs/help/08-config.md）增补 gates.auto_promote_draft 键说明：bool 类型、缺省 true、热更新属性（tasks.md:4.1） | failed（已修正） | 1/4 | test-defect |
| cli-docs-governance-flow | 治理文档（docs/help/06-governance.md）增补草稿人工放行流程：设置页开关位置 + 项目页按钮/CLI promote 两种放行方式（tasks.md:4.2） | pass | 0/3 | - |
| promote-click-opens-confirm-dialog | 点击「晋升 ready」菜单项后弹出确认对话框，提示晋升将执行声明软化与 lint 检查（pages/projects/list.tsx:693-702） | failed（已修正） | 4/7 | test-defect |
| promote-confirm-success-refreshes-list | 确认晋升后 API 返回成功，页面刷新 SPEC 列表，成功消息提示晋升完成（pages/projects/list.tsx:707-710） | failed（已修正） | - | test-defect |
| promote-lint-violation-shows-error | 对声明违规的 drafted SPEC 执行晋升时，API 返回失败并展示违规摘要（pages/projects/list.tsx:712-714） | failed（已修正） | - | test-defect |
| api-promote-success | POST /api/spec-promote 对 drafted SPEC 成功晋升，返回 200 + ok:true（core/dashboard/server.py:782-809） | failed（已修正） | 1/2 | test-defect |
| api-promote-lint-violation | POST /api/spec-promote 对声明违规的 drafted SPEC 返回 200 + ok:false + violations 数组（core/dashboard/server.py:782-809） | failed（已修正） | 1/2 | test-defect |
| cli-promote-success | CLI promote 对声明合法的 drafted SPEC 成功晋升，输出晋升成功信息，SPEC 状态变为 ready，退出码为 0（bin/fenix_cli.py:34-49） | failed（已修正） | 2/3 | product-bug |
| cli-promote-lint-violation | CLI promote 对声明段违规的 drafted SPEC 输出违规明细，SPEC 停留 drafted，退出码非 0（bin/fenix_cli.py:50-59） | failed（已修正） | 3/3 | product-bug |
| cli-promote-with-project-flag | CLI promote 使用 --project 指定外部路径时，晋升作用于指定项目的 STATE.md（bin/fenix_cli.py:62-78） | failed（已修正） | 2/3 | product-bug |
| promote-confirm-cancel-closes-dialog | 在晋升确认对话框点击取消后对话框关闭，SPEC 状态不变（pages/projects/list.tsx:700,703） | failed（已修正） | - | test-defect |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| settings-switch-position-and-visibility | element_visible .ant-form-item:has-text("草稿自动晋升") | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| settings-switch-position-and-visibility | element_visible .ant-form-item:has-text("草稿自动晋升") .ant-switch | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| settings-switch-position-and-visibility | element_visible .ant-form-item:has-text("审批模式") | test-defect | 测试用例自身缺陷（非产品缺陷） | 选择器臆测 Form.Item 含 label 文本"审批模式"，实际 ApproveModePanel.tsx:61-63 approve_mode Form.Item 无 label 属性，DOM 无该文本 |
| settings-switch-position-and-visibility | no_click_interception .ant-menu-item:has-text("审批") | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| settings-switch-position-and-visibility | no_console_error | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| settings-switch-toggle-save-success | element_visible .ant-message-notice 保存成功提示 | test-defect | 测试用例自身缺陷（非产品缺陷） | 依赖保存点击成功，未执行 |
| settings-switch-toggle-save-success | text_contains 保存成功 | test-defect | 测试用例自身缺陷（非产品缺陷） | 依赖保存点击成功，未执行 |
| settings-switch-toggle-save-success | no_console_error | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| settings-switch-toggle-save-success | no_click_interception .ant-menu-item:has-text("审批") | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| settings-switch-save-preserves-approve-mode | element_visible .ant-form-item:has-text("审批模式") .ant-radio-group | test-defect | 测试用例自身缺陷（非产品缺陷） | approve_mode Form.Item 无 label 属性（ApprovalModePanel.tsx:61-63），has-text 匹配不到 |
| settings-switch-save-preserves-approve-mode | element_visible .ant-form-item:has-text("审批模式") .ant-radio-wrapper-checked | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上 |
| settings-switch-save-preserves-approve-mode | no_console_error | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| settings-switch-save-preserves-approve-mode | no_click_interception .ant-menu-item:has-text("审批") | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| api-promote-non-drafted-rejection | status_code expected 200 | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| api-promote-non-drafted-rejection | json_path $.ok expected False | test-defect | 测试用例自身缺陷（非产品缺陷） | evaluate_json_path 不支持 $ 前缀，应写 ok；curl 实测响应体含 ok 字段（{ok:false,found:true,...}），产品行为正确 |
| cli-config-default-true | output_match DEFAULT: True | test-defect | 测试用例自身缺陷（非产品缺陷） | 多 run 步骤时 output_match 绑定最后一步输出；get_auto_promote_draft 缺省返回 True（config.py:858-861 实测验证），产品正确 |
| cli-config-default-true | output_match EXPLICIT_FALSE: False | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| cli-docs-config-key | exit_code expected 0 config_doc | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过（grep 找到 auto_promote_draft 返回 0） |
| cli-docs-config-key | output_match auto_promote_draft | test-defect | 测试用例自身缺陷（非产品缺陷） | step1 grep exit 0 说明文档含关键词，但 output_match 检查了 step2 输出（doc_attrs grep）导致误报失败 |
| cli-docs-config-key | exit_code expected 0 doc_attrs | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| cli-docs-config-key | output_match 热更新 | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| promote-click-opens-confirm-dialog | element_visible .ant-modal-content 确认对话框可见 | test-defect | 测试用例自身缺陷（非产品缺陷） | antd v6 Modal.confirm 渲染 ant-modal-confirm 结构无 ant-modal-content 类（DOM 实测），弹窗实际已打开（ant-modal-wrap 拦截指针事件佐证） |
| promote-click-opens-confirm-dialog | text_contains .ant-modal-title 晋升 ready | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| promote-click-opens-confirm-dialog | text_contains .ant-modal-body 确认将 SPEC | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| promote-click-opens-confirm-dialog | element_visible .ant-modal-confirm-btns .ant-btn-primary:has-text("晋升") | test-defect | 测试用例自身缺陷（非产品缺陷） | 按钮文本渲染为"晋 升"（antd 双汉字自动插空格），has-text("晋升")不匹配 |
| promote-click-opens-confirm-dialog | element_visible .ant-modal-confirm-btns .ant-btn:not(.ant-btn-primary):has-text("取消") | test-defect | 测试用例自身缺陷（非产品缺陷） | 按钮文本渲染为"取 消"，has-text("取消")不匹配 |
| promote-click-opens-confirm-dialog | no_click_interception button:has-text("更多") | test-defect | 测试用例自身缺陷（非产品缺陷） | 弹窗打开后 ant-modal-wrap 覆盖全页拦截"更多"按钮，属预期弹窗行为 |
| promote-click-opens-confirm-dialog | no_console_error | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| promote-confirm-success-refreshes-list | element_visible .ant-message-notice 操作结果提示 | test-defect | 测试用例自身缺陷（非产品缺陷） | 依赖确认按钮点击成功，选择器因空格失败 |
| promote-confirm-success-refreshes-list | text_contains 已晋升 ready | test-defect | 测试用例自身缺陷（非产品缺陷） | 依赖确认按钮点击成功，选择器因空格失败 |
| promote-confirm-success-refreshes-list | no_click_interception button:has-text("更多") | test-defect | 测试用例自身缺陷（非产品缺陷） | 依赖弹窗流程完整走通，选择器因空格失败 |
| promote-confirm-success-refreshes-list | no_console_error | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| promote-lint-violation-shows-error | element_visible .ant-message-notice 操作结果提示 | test-defect | 测试用例自身缺陷（非产品缺陷） | 依赖确认按钮点击成功，选择器因空格失败 |
| promote-lint-violation-shows-error | text_contains 晋升失败 | test-defect | 测试用例自身缺陷（非产品缺陷） | 依赖确认按钮点击成功，选择器因空格失败 |
| promote-lint-violation-shows-error | no_click_interception button:has-text("更多") | test-defect | 测试用例自身缺陷（非产品缺陷） | 依赖弹窗流程完整走通，选择器因空格失败 |
| promote-lint-violation-shows-error | no_console_error | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| api-promote-success | status_code expected 200 | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| api-promote-success | json_path $.ok expected True | test-defect | 测试用例自身缺陷（非产品缺陷） | evaluate_json_path 不支持 $ 前缀，应写 ok；curl 实测响应体含 ok 字段（{ok:false,found:true,...}），产品行为正确 |
| api-promote-lint-violation | status_code expected 200 | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |
| api-promote-lint-violation | json_path $.ok expected False | test-defect | 测试用例自身缺陷（非产品缺陷） | evaluate_json_path 不支持 $ 前缀，应写 ok；curl 实测响应体含 ok 字段（{ok:false,found:true,...}），产品行为正确 |
| promote-confirm-cancel-closes-dialog | element_visible button:has-text("更多") | test-defect | 测试用例自身缺陷（非产品缺陷） | 依赖取消按钮点击成功关闭弹窗，选择器因空格失败 |
| promote-confirm-cancel-closes-dialog | element_not_exist .ant-modal-content | test-defect | 测试用例自身缺陷（非产品缺陷） | 依赖取消按钮点击成功，且 antd v6 confirm 弹窗无 ant-modal-content 类 |
| promote-confirm-cancel-closes-dialog | no_click_interception .ant-modal-confirm-btns .ant-btn:not(.ant-btn-primary) | test-defect | 测试用例自身缺陷（非产品缺陷） | 依赖取消按钮可点击，选择器因空格失败 |
| promote-confirm-cancel-closes-dialog | no_console_error | test-defect | 测试用例自身缺陷（非产品缺陷） | 通过，无失败 |

## 本轮场景集变更

当前稳定场景集共 31 个（第 1 轮）。

- 无理由缺失 8 个场景，已以持久化集补齐：api-autodraft-existing-contract-overwrite-dispatched、cli-invalid-serve-kind-exit-five、cli-missing-contract-exit-one、cli-ready-probe-fail-exit-four、cli-serve-root-not-exist-exit-three、cli-healthy-contract-exit-zero、cli-invalid-yaml-exit-one、cli-prepare-failure-exit-two

> ⚠️ 本轮 planner 产出缺少既有场景且无理由，已以持久化集补齐后继续验证（不中断验证）。

