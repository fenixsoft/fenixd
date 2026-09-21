# 验证报告：fix-scheduling-kick-single-slot

> ⚠️ 本报告由框架于 2026-09-20T20:17:20Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-20T20:14:20.498099+00:00

## 结论：✅ 通过（verified）

**状态：verified — 21/22 场景通过，1 失败，0 错误（全部场景通过）**

22 场景中 21 通过、1 flaky（cli-pytest-dashboard-api-kick）：pytest exit_code=1 且 test_activate_two_manual_specs_both_signals 未见 PASSED 行，但同代码复现 -k 场景 5 passed / 完整 test_dashboard_api.py 100 passed，判定为一次性不可复现失败（flaky，不阻塞）。上一轮场景文件 -k 表达式缺陷已修复并生效（test_clear_two_specs_both_signals_exist 本轮 PASSED 匹配成功）。

| 指标 | 数量 |
| --- | --- |
| 通过 | 21 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 19.34M |
| 本链增量 Token（输出） | 0.20M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-signal-per-spec-two-files | 核心修复·两个 SPEC 在同一窗口内先后清空定时：write_scheduling_kick 为 spec A 和 spec B 各写一个文件，两文件并存（原事故形态：单槽位下第二个被丢弃）。出处：core/signals.py:139 write_scheduling_kick；core/signals.py:33 SCHEDULING_KICK_DIR = '.fenix/scheduling_kick' | pass | 0/5 | - |
| cli-signal-idempotent-overwrite | 功能正向·同一 SPEC 重复清空幂等：write_scheduling_kick 对同 spec 写两次，第二次覆盖第一次，目录中仍只有一文件，两次均返回 ok:true。出处：core/signals.py:144 同一 SPEC 重复清空幂等覆盖自身文件 | pass | 0/3 | - |
| cli-signal-invalid-name-rejected | 异常路径·非法 SPEC 名拒绝写入：含路径分隔符 / 或 .. 或大写字母的 SPEC 名被 validate_scheduling_kick_spec 拒绝，write_scheduling_kick 返回 ok:false + error，目录外不产生任何文件。出处：core/signals.py:117 validate_scheduling_kick_spec；core/signals.py:39 _KEBAB_RE | pass | 0/4 | - |
| cli-pytest-kick-signal | 回归·信号层全量测试：python3 -m pytest tests/test_scheduling_kick_signal.py -v 通过（9 个用例覆盖写入助手、幂等、多槽位、非法名拒绝、原子性、临时文件后缀、异常不外抛）。出处：tests/test_scheduling_kick_signal.py:21 TestWriteSchedulingKick | pass | 0/4 | - |
| cli-pytest-dashboard-api-kick | 回归·Dashboard API 多槽位与诚实回报：pytest tests/test_dashboard_api.py -k 'kick or warning or activate_two or honest or both_signals' -v 通过（多槽位信号并存、写入失败 warning 透传、CLI 诚实回报）。出处：tests/test_dashboard_api.py:425 test_clear_two_specs_both_signals_exist；tests/test_dashboard_api.py:505 test_activate_cli_honest_report_on_write_failure（2026-09-21 修复：-k 表达式补 both_signals，使 test_clear_two_specs_both_signals_exist 被收集） | fail | 2/5 | flaky |
| cli-pytest-spec-scheduling-kick | 回归·消费侧目录扫描与陈旧回收：pytest tests/test_spec_scheduling.py -k 'kick or reclaim or legacy' -v 通过（多信号同轮消费、单条隔离、旧文件兼容、损坏清理、陈旧回收阈值分档）。出处：tests/test_spec_scheduling.py:698 test_kick_request_multi_dir_entries_same_round；tests/test_spec_scheduling.py:805 test_reclaim_stale_only_deletes | pass | 0/5 | - |
| cli-pytest-start-after-gate | 回归·start_after 门控路径断言：pytest tests/test_start_after_gate.py 通过（路径断言同步为新目录形态，保留旧路径兼容断言）。出处：tests/test_start_after_gate.py:126 test_future_start_after_not_promoted；tests/test_start_after_gate.py:396 test_kick_signal_drafted_promotes_after_clear | pass | 0/3 | - |
| cli-activate-manual-spec | 功能正向·CLI 激活待激活 SPEC：对 start_after=manual 的 spec 调用 fenix_cli.py activate → exit 0，输出包含「已激活，立即进入调度」。出处：bin/fenix_cli.py:106 cmd_activate；bin/fenix_cli.py:129 成功文案 | pass | 0/5 | - |
| cli-activate-rejected-non-manual | 异常路径·CLI 拒绝非待激活 SPEC：对 start_after=null 的 spec 调用 activate → exit 1，stderr 包含「激活被拒绝」。出处：bin/fenix_cli.py:137 拒绝路径（幂等拒绝，STATE 零变更） | pass | 0/4 | - |
| cli-seed-fixtures | 夹具准备·注入 API/Web 场景所需的 kick-* spec（幂等 reset：清残留信号 + 重建 7 个 spec + 创建 spec/changes 目录防归档过滤）。出处：scheduling-showcase 夹具经 core/state_machine.py StateMachine 直接写入；is_spec_archived 依赖 spec/changes/<name>/ 存在（core/dashboard/data/spec_archive.py:117） | pass | 0/2 | - |
| api-activate-unknown-404 | 异常路径·激活不存在的 SPEC：POST /api/spec-activate spec=ghost-nonexistent → 404。出处：core/dashboard/routes/spec_routes.py:310 found 分支 | pass | 0/2 | - |
| api-clear-start-after-success | 功能正向·清空定时返回 ok 且无 warning：POST /api/spec-start-after value=null on kick-future → 200, ok:true, start_after:null, 响应不含 warning（信号写出成功）。出处：core/dashboard/routes/spec_routes.py:261 resp 构建；spec scheduling-kick-signal「信号写入成功时 API 不带警告」 | pass | 0/4 | - |
| api-set-start-after-manual | 功能正向·设为待激活哨兵：POST /api/spec-start-after value=manual on kick-plain → 200, ok:true, start_after=manual（哨兵非定时，不触发 kick 信号）。出处：core/dashboard/data/admin_actions.py:496 哨兵分支；spec spec-manual-activation「各立项与放行入口提供手工激活选项」 | pass | 0/3 | - |
| api-start-after-invalid-400 | 异常路径·非法 ISO8601 被拒绝：POST /api/spec-start-after value=not-a-date on kick-plain → 400。出处：core/dashboard/routes/spec_routes.py:258 invalid 分支；core/dashboard/data/admin_actions.py:501 parse_utc 返回 None | pass | 0/2 | - |
| api-start-after-terminal-403 | 异常路径·终态 SPEC 设置定时被拒：POST /api/spec-start-after on kick-done → 403。出处：core/dashboard/routes/spec_routes.py:255 terminal 分支 | pass | 0/2 | - |
| api-activate-manual-success | 功能正向·激活待激活 SPEC：POST /api/spec-activate on kick-manual → 200, ok:true, start_after:null, 无 warning。出处：core/dashboard/routes/spec_routes.py:278 _api_spec_activate；spec spec-manual-activation「激活待激活 SPEC」 | pass | 0/3 | - |
| api-activate-not-manual-rejected | 异常路径·非待激活 SPEC 激活被拒：POST /api/spec-activate on kick-null（start_after=null）→ 200, ok:false + reason 含「非待激活态」。出处：core/dashboard/routes/spec_routes.py:316 非待激活分支；spec spec-manual-activation「对非待激活 SPEC 激活被拒」 | pass | 0/3 | - |
| api-activate-terminal-403 | 异常路径·终态 SPEC 激活被拒：POST /api/spec-activate on kick-done → 403。出处：core/dashboard/routes/spec_routes.py:313 terminal 分支 | pass | 0/2 | - |
| web-clear-start-after-success | 功能正向·Dashboard 清除定时成功文案：对 kick-future-web（有未来 start_after）打开「设置拾取时间」弹窗 → 清除定时 → 确定 → toast「已清除定时，立即恢复调度」。出处：core/dashboard/static/src/pages/projects/list.tsx:865 handleStartAfterOk 分支文案；SPA 路由 #/projects/<name> 出自 core/dashboard/static/src/app.tsx:103；核心修复正向路径「信号写出成功 → 立即恢复调度」 | pass | 0/3 | - |
| web-spec-status-manual-activate-btn | UI 状态·待激活 SPEC 修改状态弹窗显示激活按钮：对 kick-manual-web（start_after=manual）打开「修改状态」弹窗，调度区块显示「激活（立即调度）」primary 按钮（持久存在于状态弹窗内，不因二次确认关闭而移除）。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:591 isManualPending 分支 | pass | 0/3 | - |
| web-spec-status-set-manual-btn | UI 状态·非待激活 SPEC 修改状态弹窗显示设为待激活：对 kick-null（start_after=null）打开「修改状态」弹窗，调度区块显示「设为待激活」按钮（持久存在于状态弹窗内）。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:597 else 分支 | pass | 0/3 | - |
| web-activate-manual-spec-flow | 功能正向·激活待激活 SPEC 完整流程：点击「激活（立即调度）」→ Modal.confirm 二次确认（antd okText「激活」自动插空格「激 活」，用 class 选择器点击）→ 确认 → toast「已激活，daemon 将立即拾取」。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:389 handleActivate → appModal.confirm → activateSpec → message.success；modal 内部「审批推送」按钮经修复后持久（onDone 仅刷新列表不关状态弹窗） | pass | 0/3 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| cli-pytest-dashboard-api-kick | exit_code: 期望 pytest_api 步骤退出码 0（layer 1） | flaky | 不稳定复现（非产品缺陷） | 本步命令与场景文件定义一致（-k 已补 both_signals）；同代码复现 -k 场景 5 passed exit 0、完整文件 100 passed，本次 exit 1 无确定性根因，判一次性抖动 |
| cli-pytest-dashboard-api-kick | output_match: 期望 combined 输出含 'test_activate_two_manual_specs_both_signals PASSED'（layer 3） | flaky | 不稳定复现（非产品缺陷） | 复现输出含该测试 PASSED 行（同断言 label test_activate_two_manual_specs_both_signals）；本次缺失与 exit_code=1 同源（该测试当次失败），复现不可再现，判 flaky |

## 本轮场景集变更

场景集与持久化集一致，无变更。

