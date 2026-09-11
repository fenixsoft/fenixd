# 验证报告：add-spec-approve-push-modal

> ⚠️ 本报告由框架于 2026-09-11T02:41:40Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 6/14 场景通过，7 失败，0 错误（1 个真实产品 Bug）**

14 场景：6 PASS；8 非 PASS 已逐场景归因。product-bug×1（合并 2 场景，_error 中文错误消息 ensure_ascii 转义致 body_contains 失配，severity=minor）；test-defect×1（web-approve-push-modal-pushed：seed 夹具未建 ap-push-pushed 活跃目录致 archived 过滤不渲染该行，已按原地修复协议在 test_scenarios.json seed 中补 (SC/'ap-push-pushed').mkdir，MUST 重跑确认）；env×5（daemon 未运行致 409 三场景+signale-consume+confirm-success 失败，SPA 冷启动首帧未 ok 致 web-approve-push-modal-done 阻塞，标 warning 不阻塞）。注意：web-approve-push-modal-done/first 场景 blocked-env 与 web-pushed 属不同根因（前者冷启动竞态、后者 seed 目录缺陷），勿混淆。

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 7 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 11.36M |
| 本链增量 Token（输出） | 0.13M |


## 真实产品 Bug

### BUG-01（severity=minor）· body_contains

- 关联场景：api-approve-push-403-ready、api-approve-push-403-pushed
- 描述：审批推送 API 的错误响应（403/409 等）中中文错误文案被转义为 \uXXXX 序列输出，API 原始响应不可直接读。core/dashboard/server.py:_error 用 json.dumps({'error': msg}) 默认 ensure_ascii=True 转义中文，而同文件 _json 用 ensure_ascii=False，编码策略不一致；导致 body_contains 中文子串断言（如「仅 done 状态可审批推送」「已推送」「无需审批」）在 raw body 上失配。
- 根因：server.py:2082 _error 构造 JSON 时未传 ensure_ascii=False（对照 _json:2071 传 ensure_ascii=False），中文错误消息被转义；SPEC 场景要求错误响应包含可读中文文案，响应文本字面不满足。
- 证据（场景 api-approve-push-403-ready 结构化证据，引用）：
  - failed_assertions: [{"type": "body_contains", "expected": "仅 done 状态可审批推送", "actual": "API 返回 403，但错误消息经 server._error json.dumps 默认 ensure_ascii=True 转义为 \\uXXXX 序列，raw body 不含可匹配中文"}]
  - screenshots: []
  - first_failed_step: body_contains 断言失败：_error 中文错误消息被转义，raw body 无法匹配


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-seed-approve-push-fixtures | 种子场景：向 scheduling-showcase fixture 写入本 SPEC 所需的补充夹具——pushed 竞本（ap-push-pushed，status=pushed，供 403 pushed 幂等拒绝测试与 pushed 弹窗不渲染测试）、独立 done 竞本（ap-push-web，status=done + spec/changes 活跃目录，供 cli-write/cli-consume 信号测试——与 c-sched-done 解耦，避免 daemon 消费信号把状态推进 pushed 后影响其他场景）、另一个独立 done 竞本（ap-push-confirm，status=done + 目录，供 web 确认成功场景——从未被写入信号，保证弹窗显示审批推送按钮）；并清理上一轮残留的 approve_push_request.json 信号文件、确保 c-sched-done 有活跃 spec/changes 目录（幂等复位）。出处：spec/changes/add-spec-approve-push-modal/specs/spec-approve-push-modal/spec.md 场景表；夹具路径 /root/scheduling-showcase（复用 add-spec-status-modal-budget 已有 fixture 项目，.fenix/STATE.md 含 c-sched-done(status=done) 与 c-sched-set(status=ready) 可直接复用） | pass | 0/6 | - |
| api-approve-push-404-project | 异常路径·POST /api/spec-approve-push 对不存在的 project 返回 404（project 不在 dashboard registry）。出处：core/dashboard/server.py:885-889（404 unknown project / project not found） | pass | 0/2 | - |
| api-approve-push-404-spec | 异常路径·POST /api/spec-approve-push 对不存在的 spec 返回 404（spec 不在项目 STATE.md）。出处：core/dashboard/server.py:890-893（404 spec required）、core/dashboard/data.py:620-624（found=False） | pass | 0/2 | - |
| api-approve-push-403-ready | 异常路径·POST /api/spec-approve-push 对 ready 非 done SPEC 返回 403「仅 done 状态可审批推送（当前 ready）」，STATE.md 无变化。出处：core/dashboard/data.py:628-636（terminal=True，msg 含状态名）；server.py:909-911（403 终态拒绝）。夹具 c-sched-set（ready） | failed | 1/3 | product-bug |
| api-approve-push-403-pushed | 异常路径·POST /api/spec-approve-push 对 pushed 终态 SPEC 返回 403「SPEC 已推送（pushed），无需审批」（幂等拒绝，语义正确非错误）。出处：core/dashboard/data.py:629-631（pushed 分支特定文案）；server.py:909-911（403 终态拒绝）。夹具 ap-push-pushed（seed 注入） | failed | 2/3 | product-bug |
| cli-write-approve-push-signal | 前置步骤·写入冲突信号文件供 409 冲突测试：向 scheduling-showcase/.fenix/approve_push_request.json 写入合法 payload（spec=ap-push-web, source=dashboard, created=ISO8601），模拟 API 成功后 daemon 未消费的状态。出处：core/dashboard/data.py:660-676（payload 三键 + tmp+rename 原子写）；daemon 主循环 1s 粒度扫描，此场景完成后依赖方 api-approve-push-409-conflict 立即执行（毫秒窗口，daemon 未消费则命中 409；daemon 恰好消费则返回 200，属环境时序候选）；用 ap-push-web 与 c-sched-done 解耦，即使 daemon 消费也只影响 ap-push-web，不影响 web 场景依赖的 c-sched-done | pass | 0/2 | - |
| web-approve-push-modal-done | 功能正向·打开 done SPEC（c-sched-done）「修改状态」弹窗 → 审批推送区块渲染在归档区块之前：含「审批推送」标题、说明文案（daemon 执行推送/退避重试/push_failed 告警）、「审批推送」primary 按钮，归档区块照常。出处：SpecStatusModal.tsx:318-335（summary?.status==='done' 条件渲染审批推送区块，done 态区块顺序审批推送→归档）；SPA 路由 #/projects/<name> 出自 core/dashboard/static/src/app.tsx:103（/projects 页面注册）。本场景依赖写信号场景之前执行（c-sched-done 保持 done；后置 cli-approve-push-signal-consume 已消费 ap-push-web，不影响本场景） | blocked-env | - | env |
| web-approve-push-modal-pushed | 功能正向·打开 pushed 终态 SPEC（ap-push-pushed）「修改状态」弹窗 → 不渲染审批推送区块（已推送无待审批语义），归档区块照常渲染。出处：SpecStatusModal.tsx:320（status==='done' 才渲染审批推送，pushed 不命中）；SPA 路由 #/projects/<name> 出自 core/dashboard/static/src/app.tsx:103。夹具 ap-push-pushed（seed 注入 pushed 态） | failed | - | test-defect |
| web-approve-push-confirm-cancel | 功能正向·done SPEC（ap-push-confirm）弹窗点击「审批推送」→ Modal.confirm 二次确认弹出 → 取消 → 不调用 API，弹窗保持打开，审批推送按钮仍可点击。出处：SpecStatusModal.tsx:245-271（handleApprovePush → appModal.confirm，cancel 路径不执行 onOk）；SPA 路由 #/projects/<name> 出自 core/dashboard/static/src/app.tsx:103；antd Modal.confirm 取消按钮 .ant-modal-confirm-btns .ant-btn:not(.ant-btn-primary)（二字「取消」自动插空格渲染为「取 消」，has-text 仍匹配）。本场景排在写信号场景之前（ap-push-confirm 从未被写入信号，确保弹窗显示审批推送区块） | pass | 0/5 | - |
| api-approve-push-409-conflict | 异常路径·POST /api/spec-approve-push 已有未消费信号时返回 409「已有进行中的审批推送请求」，既有信号不被覆盖。出处：core/dashboard/data.py:645-658（conflict=True，读既有 created）；server.py:906-908（409 conflict）。前置：cli-write-approve-push-signal 写入信号（毫秒窗口内 daemon 未消费则命中 409；daemon 恰好消费则返回 200，属环境时序候选） | warning | 1/2 | env |
| cli-clear-approve-push-signal | 清理步骤·删除冲突信号文件，恢复干净状态供后续 200 成功路径测试。出处：design D2（信号滞留无害，清理后 api-approve-push-200-success 无冲突信号） | pass | 0/2 | - |
| api-approve-push-200-success | 功能正向·POST /api/spec-approve-push 对 done SPEC 且 daemon 运行中、无残留信号 → 200 + {ok:true, project, spec, created}，.fenix/approve_push_request.json 被原子写入。出处：core/dashboard/data.py:660-676（写 payload{spec, source, created}）；server.py:912-913（200 返回）。夹具 c-sched-done（done）；须 daemon 运行中（否则返回 409 daemon 未运行，属环境条件非产品缺陷） | warning | 4/4 | env |
| cli-approve-push-signal-consume | 功能正向·daemon 主循环消费审批推送信号：写入 .fenix/approve_push_request.json（spec=ap-push-web）后等待 3s（≤2s 消费周期 + 1s 安全余量），信号文件被删除（读→删→调 approve_push），project log 记录推送事件。出处：fenixd.py:793-857（_check_approve_push_requests 消费逻辑，与 _check_cancel_requests 同构）；须 daemon 运行中（否则信号滞留，文件仍存在，属环境条件）；消费后 ap-push-web 若推送成功则状态推进 pushed（git push 成功时），失败保持 done（退避或无 remote），不影响信号删除断言 | warning | 2/3 | env |
| web-approve-push-confirm-success | 功能正向·done SPEC（ap-push-confirm）弹窗点击「审批推送」→ Modal.confirm 二次确认（标题「审批推送 SPEC」、文案含 SPEC 名称与推送目标）→ 确认后真实调用 POST /api/spec-approve-push，成功提示「已提交推送，daemon 执行中」并刷新列表。出处：SpecStatusModal.tsx:245-271（handleApprovePush → appModal.confirm → approveSpecPush → message.success('已提交推送，daemon 执行中') + onDone 刷新）；SPA 路由 #/projects/<name> 出自 core/dashboard/static/src/app.tsx:103；antd Modal.confirm 选择器：.ant-modal-confirm-btns .ant-btn-primary。夹具 ap-push-confirm（seed 注入独立 done 竞本，从未被写入信号，确保弹窗显示审批推送按钮）；须 daemon 运行中且无残留信号（cli-approve-push-signal-consume 场景已消费信号，ap-push-web 可能已被消费，但不影响 ap-push-confirm） | warning | 3/3 | env |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| web-approve-push-modal-done | 点击 tr[data-row-key='c-sched-done'] button.ant-dropdown-trigger | env | 环境因素（非产品缺陷） | env_blocked=true，navigate 首帧未 ok（首次访问 dashboard，SPA 资源加载/构建未就绪），元素未渲染。属环境阻塞。 |
| web-approve-push-modal-pushed | 点击 tr[data-row-key='ap-push-pushed'] button.ant-dropdown-trigger | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景文件缺陷（seed 夹具）：cli-seed-approve-push-fixtures 注入 ap-push-pushed 时未创建 spec/changes/ap-push-pushed/ 活跃目录，is_spec_archived 判定为真（data.py:937-944），列表按 archivedOn... |
| api-approve-push-409-conflict | body_contains ["已有进行中的审批推送请求"] | env | 环境因素（非产品缺陷） | API 返回 409 但错误信息为「daemon 未运行，请先启动 daemon」，表明测试环境 daemon 未运行，无法触发冲突错误路径。属于环境问题。 |
| api-approve-push-200-success | status_code 期望 200 | env | 环境因素（非产品缺陷） | 实际返回 409 daemon 未运行，测试环境 daemon 未启动，无法验证 200 成功路径。 |
| api-approve-push-200-success | json_path ok 期望 true | env | 环境因素（非产品缺陷） | 因 daemon 未运行返回 409，响应无 ok 字段。 |
| api-approve-push-200-success | json_path spec 期望 c-sched-done | env | 环境因素（非产品缺陷） | 因 daemon 未运行返回 409，响应无 spec 字段。 |
| api-approve-push-200-success | json_path created 期望时间戳 | env | 环境因素（非产品缺陷） | 因 daemon 未运行返回 409，响应无 created 字段。 |
| cli-approve-push-signal-consume | output_match 匹配 SIGNAL_CONSUMED | env | 环境因素（非产品缺陷） | 输出 SIGNAL_STILL_EXISTS，信号文件未被删除，因 daemon 未运行。 |
| cli-approve-push-signal-consume | exit_code 期望 0 | env | 环境因素（非产品缺陷） | 脚本退出码 1，因信号未消费判失败，根因 daemon 未运行。 |
| web-approve-push-confirm-success | element_visible .ant-message:has-text('已提交推送') | env | 环境因素（非产品缺陷） | API 调用返回 409 daemon 未运行，无成功提示消息。 |
| web-approve-push-confirm-success | no_click_interception .ant-modal-confirm-btns .ant-btn-primary | env | 环境因素（非产品缺陷） | API 调用失败可能导致弹窗状态异常，按钮不可点击或未渲染。 |
| web-approve-push-confirm-success | no_console_error | env | 环境因素（非产品缺陷） | 控制台错误 409 Conflict 由 API 返回，根因 daemon 未运行。 |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

