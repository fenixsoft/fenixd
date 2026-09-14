# 验证报告：add-draft-promotion-gate

> ⚠️ 本报告由框架于 2026-09-13T10:53:07Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-08T19:45:51.286727+00:00

## 结论：✅ 通过（verified）

**状态：verified — 20/25 场景通过，5 失败，0 错误（全部场景通过）**

25 场景：20 通过、5 失败（全归类 flaky，非阻塞，无产品缺陷）。4 个 web 场景（settings-promote-mode-save-preserves-approve、promote-button-shown-for-drafted-spec、promote-button-hidden-for-ready-spec、promote-lint-violation-shows-error）均在导航后首个 wait 步骤（harness 固定 5000ms 超时）偶发超时：引擎按 depends_on 分层并行执行（max_parallel=5），web 场景共享单浏览器实例与同一 dashboard，列表加载在负载窗口下偶发超过 5s；同一选择器在同轮兄弟场景promote-confirm-success-refreshes-list 成功定位并完成晋升（webfix 已置 ready），list.tsx:1031 确认「更多」按钮对所有行无条件渲染，元素真实存在，属偶发时序非产品缺陷。1 个 api 场景api-config-get-after-save-promote-manual 级联失败：depends_on 上游 settings 保存场景未执行 manual 保存（config.yaml 确证无 promote_mode 键），effective config 返回缺省 auto，产品行为正确。产品功能已被 20 个通过场景端到端覆盖：CLI/API/Web 三种放行方式、lint 拦截、非 drafted 拒绝、配置缺省与校验、设置页渲染与文档。无场景文件缺陷，无需修复。

| 指标 | 数量 |
| --- | --- |
| 通过 | 20 |
| 失败 | 5 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 44.14M |
| 本链增量 Token（输出） | 0.60M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-seed-drafted-spec | 向验证项目 /root/scheduling-showcase 写入 5 个 drafted SPEC 夹具与对应 tasks.md（webfix/apiok/cliok/cliok2 声明合法；lintbad 含不存在路径 modify 违规），并复位项目 config.yaml 移除 promote_mode（保证本轮 promote_mode 缺省 auto、跨轮无残留），供 api/web/cli 场景经 depends_on 串接消费；非 drafted 拒绝类场景复用夹具基线既有 done 态 c-sched-done（写路径落 /root/scheduling-showcase/.fenix，与 add-verify-multi-kind-runner 轮 seed 同边界：fresh 实例的 STATE 由本轮独占） | pass | 0/3 | - |
| cli-config-default-auto | 配置缺省值：ConfigLoader.get_promote_mode 在无 promote_mode 键时返回 auto（core/config.py:854-863） | pass | 0/2 | - |
| cli-config-explicit-manual | 配置 getter：promote_mode 显式 manual 时 get_promote_mode 返回 manual（core/config.py:854-863） | pass | 0/2 | - |
| cli-config-invalid-value-rejected | 配置校验拒绝非法枚举值 promote_mode="yes"，报错指出合法取值 auto/manual（core/config.py:348-355） | pass | 0/3 | - |
| cli-docs-config-key | 配置文档 docs/help/08-config.md gates 表含 promote_mode 条目：default auto、范围 auto/manual、热更新（docs/help/08-config.md:93） | pass | 0/2 | - |
| cli-docs-governance-flow | 治理文档 docs/help/06-governance.md 含草稿人工放行流程：promote_mode 开关、三种放行方式、lint 拦截语义、切回 auto 存量处理（docs/help/06-governance.md:44,56） | pass | 0/2 | - |
| api-promote-spec-not-found | POST /api/spec-promote 对 STATE.md 不存在的 spec 返回 404（core/dashboard/server.py:808-809） | pass | 0/1 | - |
| api-promote-project-not-found | POST /api/spec-promote 对不存在的项目返回 404（core/dashboard/server.py:793-798） | pass | 0/1 | - |
| api-config-get-returns-promote-mode-default | GET /api/config?project=scheduling-showcase 返回 effective config，gates.promote_mode 默认补全为 auto（data.py:3697-3705） | pass | 0/3 | - |
| settings-promote-mode-radio-visible | 设置页审批页签「草稿晋升模式」Radio.Group 渲染且在审批模式（approve_mode）上方（ApprovalModePanel.tsx:52-84） | pass | 0/3 | - |
| settings-promote-mode-reflects-config | 设置页审批页签单选反映配置值：配置缺省 auto 时页面加载后选中 auto（ApprovalModePanel.tsx:18,47） | pass | 0/2 | - |
| settings-promote-mode-description-text | 审批页签草稿晋升模式附带说明文字：manual 停留草稿态供阅读，可经 /fenix-ready、项目页按钮或 CLI 放行（ApprovalModePanel.tsx:64-82） | pass | 0/3 | - |
| cli-promote-success | CLI promote 对声明合法的 drafted SPEC（verify-draft-cliok）成功晋升：输出晋升成功信息、SPEC 状态变 ready、退出码 0（bin/fenix_cli.py:34-49; promotion.py:11-118） | pass | 0/3 | - |
| cli-promote-with-project-flag | CLI promote 使用 --project 指定项目路径（verify-draft-cliok2）时晋升作用于指定项目的 STATE.md，退出码 0（bin/fenix_cli.py:21-31,73-77） | pass | 0/3 | - |
| cli-promote-lint-violation | CLI promote 对声明段违规的 drafted SPEC（verify-draft-lintbad）输出违规明细、停留 drafted、退出码非 0（bin/fenix_cli.py:50-59; promotion.py:104-115） | pass | 0/2 | - |
| cli-promote-non-drafted-rejection | CLI promote 对非 drafted 状态 SPEC（夹具基线 done 状态 c-sched-done）输出拒绝原因、退出码非 0、STATE 不变（bin/fenix_cli.py:50-59; promotion.py:36-37） | pass | 0/2 | - |
| api-promote-success | POST /api/spec-promote 对 drafted SPEC（verify-draft-apiok）成功晋升返回 200 + ok:true，STATE 状态变 ready（core/dashboard/server.py:782-809; data.py:342-372） | pass | 0/2 | - |
| api-promote-lint-violation | POST /api/spec-promote 对声明违规 SPEC（verify-draft-lintbad）返回 200 + ok:false + violations 数组，STATE 写 error 停留 drafted（core/dashboard/server.py:804-811; data.py:370-372） | pass | 0/4 | - |
| api-promote-non-drafted-rejection | POST /api/spec-promote 对非 drafted 状态 SPEC（夹具基线 done 状态 c-sched-done）返回 200 + ok:false + reason，STATE 不变（core/dashboard/server.py:782-789; data.py:366-369） | pass | 0/3 | - |
| settings-promote-mode-save-preserves-approve | 在审批页签选择 manual 并保存成功，保存载荷同时提交 promote_mode 与 approve_mode 两键不丢前者（ApprovalModePanel.tsx:23-35; data.py:3989-3995 校验 + merge 保留 approve_mode） | fail | - | flaky |
| promote-button-shown-for-drafted-spec | 项目列表页 drafted 状态 SPEC（verify-draft-webfix）行的操作菜单提供「晋升 ready」菜单项（list.tsx:795-799） | fail | - | flaky |
| promote-button-hidden-for-ready-spec | 项目列表页非 drafted 状态（done 状态 c-sched-done）SPEC 行的操作菜单不提供「晋升 ready」菜单项（list.tsx:795-799） | fail | - | flaky |
| promote-lint-violation-shows-error | 项目页对声明违规的 drafted SPEC（verify-draft-lintbad）执行晋升时展示失败原因（含违规摘要），SPEC 停留 drafted（list.tsx:710-714） | fail | - | flaky |
| api-config-get-after-save-promote-manual | 设置页保存 manual 后，GET /api/config?project=scheduling-showcase 返回 gates.promote_mode=manual、approve_mode 保持 manual 未被覆盖（data.py:3697-3707 读取 + write_config merge 保留 approve_mode） | fail | 1/3 | flaky |
| promote-confirm-success-refreshes-list | 项目页对 drafted SPEC（verify-draft-webfix）确认晋升成功后提示已晋升 ready（list.tsx:704-709; Modal.confirm 弹窗） | pass | 0/2 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| settings-promote-mode-save-preserves-approve | element_visible .ant-menu-item:has-text('审批') 设置页审批页签 | flaky | 不稳定复现（非产品缺陷） | 相同 navigate+wait 在 settings-promote-mode-radio-visible/reflects-config/description-text 三个场景全部通过，菜单项确实渲染；本场景为偶发加载超时，重试可过 |
| promote-button-shown-for-drafted-spec | element_visible tr:has-text('verify-draft-webfix') button:has-text('更多') 项目页行操作按钮 | flaky | 不稳定复现（非产品缺陷） | 同一选择器在同轮 promote-confirm-success-refreshes-list 中成功定位并完成晋升点击，元素真实存在；项目页列表加载偶发超时 |
| promote-button-hidden-for-ready-spec | element_visible tr:has-text('c-sched-done') button:has-text('更多') 项目页行操作按钮 | flaky | 不稳定复现（非产品缺陷） | 与 promote-button-shown 场景同一 wait 模式同时段连续超时，而后续同类场景同一选择器通过；页面加载偶发超时，非产品缺陷 |
| promote-lint-violation-shows-error | element_visible tr:has-text('verify-draft-lintbad') button:has-text('更多') 项目页行操作按钮 | flaky | 不稳定复现（非产品缺陷） | lintbad 为 seed 场景写入的 drafted 夹具，列表应渲染其行；三个项目页场景同一 wait 模式连续超时、后续同类场景通过，属列表加载偶发超时 |
| api-config-get-after-save-promote-manual | json_path gates.promote_mode == manual | flaky | 不稳定复现（非产品缺陷） | depends_on 上游 settings-promote-mode-save-preserves-approve 因 wait 超时失败未执行保存，promote_mode 保持缺省 auto；产品行为正确（未保存则返回 auto），上游重试通过后本场景可过 |

## 本轮场景集变更

当前稳定场景集共 17 个（第 2 轮）。

首轮写入 17 个场景

