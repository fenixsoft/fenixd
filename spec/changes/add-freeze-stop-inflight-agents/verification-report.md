# 验证报告：add-freeze-stop-inflight-agents

> ⚠️ 本报告由框架于 2026-09-20T22:42:37Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-20T22:40:53.076645+00:00

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 20/22 场景通过，2 失败，0 错误（1 个真实产品 Bug）**

22 场景 20 通过 2 失败（均为跨轮已裁决 product-bug，同根因合并为 1 个 Bug：freeze_spec 后端未返回 stopped_agents）。静态缺陷情报 web-freeze-idle-confirm-success（double_han_text_selector）经源码核实为误报：断言带 selector 限定 tr[data-row-key=fs-web-idle] 匹配持久 DOM 状态列「阻塞」而非按钮文本，antd autoInsertSpace 不适用，场景已 pass 无需修复。

| 指标 | 数量 |
| --- | --- |
| 通过 | 20 |
| 失败 | 2 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 18.81M |
| 本链增量 Token（输出） | 0.26M |


## 真实产品 Bug

### BUG-01（severity=major）· json_path（stopped_agents）+ text_contains

- 关联场景：api-freeze-inflight-stopped-agents、web-freeze-inflight-stopped-hint
- 描述：冻结有在跑 agent 的 spec 时，freeze_spec 后端返回值未扩展 stopped_agents 计数（admin_actions.py:309-343 仅返回 ok/found/frozen/error），proposal Impact「freeze_spec 返回值扩展（stopped_agents 计数）」未实现；前端 SpecStatusModal.tsx:165 if(result?.stopped_agents) 恒 false，toast 走缺省分支「已冻结，daemon 停止调度」，停止计数与「进度已留存，解冻后可续做」反馈缺失
- 根因：freeze_spec（admin_actions.py:309-343）未统计并返回被停止的在跑 agent 数；tasks 6.x 仅扩展了前端类型，后端计数缺失，导致前后端契约不一致
- 证据（场景 api-freeze-inflight-stopped-agents 结构化证据，引用）：
  - failed_assertions: [{"type": "json_path", "path": "stopped_agents", "expected": 1, "actual": null, "label": "冻结返回值含 stopped_agents=1"}]
  - screenshots: []
  - first_failed_step: 步骤1: POST /api/spec-freeze?spec=fs-api-inflight 返回 200，响应缺 stopped_agents 字段（proposal Impact 声明 freeze_spec 返回值扩展计数，实际 admin_actions.py:309 未返回）


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-freeze-polling-loop | 冻结即停核心：轮询环 frozen 命中终止序列（frozen-terminated 终态行落盘 + FrozenTerminatedError）、未冻结零影响、STATE 读取异常 fail-open 不误杀、frozen 检查先于 cancel 且清理残留 cancel 旗标。来源：spec/changes/add-freeze-stop-inflight-agents/specs/freeze-stop-inflight-agents/spec.md 全部『冻结即停』『冻结终止序列与独立终态』需求；测试文件 tests/test_freeze_stop_inflight_agents.py（test_frozen_hit_terminates_and_writes_frozen_terminal / test_not_frozen_zero_impact / test_state_read_error_fail_open / test_frozen_precedes_cancel_and_clears_flag）。 | pass | 0/5 | - |
| cli-freeze-hold-markers | 冻结终止独立保持标记：_frozen_hold 序列化往返（True/False/缺省）、mark_frozen_hold 原子写形态（_frozen_hold True + _cancelled_hold False + error 保真 + 锚点保留 + status 不改）、两 hold 不同时为真、全库 _cancelled_hold True 字面计数不变（静态守卫）。来源：spec freeze-stop-inflight-agents/spec.md『冻结终止的独立保持标记』；测试文件 tests/test_freeze_stop_inflight_agents.py（test_frozen_hold_serialization_roundtrip / test_mark_frozen_hold_atomic_write / test_cancelled_hold_and_cancelled_hold_not_both_true / test_cancelled_hold_true_literal_count_unchanged）。 | pass | 0/5 | - |
| cli-freeze-unfreeze-resume | 解冻自动续做接线：_frozen_hold + 保留分支未合并提交 → 保留 branch/implementer_run + _recovery_resume True；分支不可用 → 清标记普通重派降级；无 _frozen_hold 行为逐位不变（回归）；共享判定零漂移（_recovery_preserve_spec 与解冻续做同源）。来源：spec freeze-stop-inflight-agents/spec.md『解冻后在保留分支自动续做』；测试文件 tests/test_freeze_stop_inflight_agents.py（test_unfreeze_resume_preserves_branch / test_unfreeze_no_resume_degrade / test_unfreeze_no_frozen_hold_unchanged / test_shared_judgment_zero_drift）。 | pass | 0/5 | - |
| cli-freeze-branch-protection | 冻结终止保留分支受 stale_sweep 保护：frozen+_frozen_hold 的 blocked spec 的 branch 受保护（不回收）；仅有 frozen 或仅有 _frozen_hold 不受保护（降级路径有 WARNING 留痕）。来源：design.md Risks『遗产宽限期回收分支的风险』（tasks 2.7）；测试文件 tests/test_freeze_stop_inflight_agents.py（test_frozen_hold_branch_protected / test_frozen_without_hold_not_protected / test_hold_without_frozen_not_protected）。 | pass | 0/4 | - |
| cli-delete-attribution | 删除停止动作归属判定：run_spec_part 全等匹配（fix-x 不被 impl-fix-x-y-* 命中）、-a<n>/-r<n> 后缀剥离、末行终态（result/cancelled/error/interrupted/frozen-terminated）判非在跑、superseded 非终态判仍在跑。来源：spec delete-stop-inflight-agents/spec.md『删除 SPEC 先停止在跑 agent 再软删除』；测试文件 tests/test_delete_stop_inflight_agents.py（test_full_equality_spec_attribution / test_suffix_stripping / test_terminal_last_line_not_running / test_superseded_last_line_still_running）。 | pass | 0/5 | - |
| cli-delete-signal-safety | 删除异步受理信号安全：spec_delete_request.json 原子写 payload（spec/source/created/stopping）、已有未消费信号 409 冲突不覆盖、daemon 未托管（unmanaged）拒绝且不写文件、daemon 未运行（stopped）拒绝且不写文件。来源：spec delete-stop-inflight-agents/spec.md『删除 API 异步受理』；测试文件 tests/test_delete_stop_inflight_agents.py（test_atomic_write_payload / test_conflict_existing_signal / test_unmanaged_rejects_no_file / test_daemon_down_rejects_no_file）。 | pass | 0/5 | - |
| cli-delete-soft-delete-lifecycle | soft_delete_spec 先停后删生命周期：无在跑零等待直接删除（回归）、停止回调使其终态后删除成功（stopped 计数）、停止后仍不落终态超时返回 running 且 STATE/目录不变（不产生半删状态）、stop_callback 缺省回退既有 409 拒绝语义。来源：spec delete-stop-inflight-agents/spec.md『删除 SPEC 先停止在跑 agent 再软删除』全部场景；测试文件 tests/test_delete_stop_inflight_agents.py（test_no_running_direct_delete / test_stop_callback_terminates_then_delete / test_timeout_still_running_no_delete / test_no_stop_callback_fallback_409）。 | pass | 0/5 | - |
| cli-seed-freeze-delete-fixtures | 种子场景：向 fixture 项目 /root/scheduling-showcase 写入本 SPEC 涉及的补充夹具——fs-api-idle（ready 可冻结）、fs-api-inflight（implementing + 末行非终态 run 文件，供冻结 stopped_agents 计数）、fs-web-idle / fs-web-inflight（web 场景专用同型）、fs-done（done 终态不可冻结）、fs-hold（blocked+frozen+_frozen_hold+error=用户指令冻结：原状态 implementing+保留锚点，供解冻续做/冻结态渲染）、dl-api-idle / dl-web-idle（无在跑可删除）、dl-inflight（implementing + 非终态 run 文件，供删除 409）；全部建 spec/changes/<name>/ 目录防 archived 过滤；幂等复位（移除跨轮残留同名单 + 清 archive 残留）。出处：spec/changes/add-freeze-stop-inflight-agents/specs/freeze-stop-inflight-agents/spec.md 与 delete-stop-inflight-agents/spec.md 各验收场景的 WHEN 前置（implementing + 在跑 run / done / blocked+frozen+_frozen_hold）；写路径复用 add-spec-status-modal-budget 轮 seed 边界（StateMachine.add_spec 落 /root/scheduling-showcase/.fenix/STATE.md，fresh 实例由本轮独占）。 | pass | 0/2 | - |
| api-freeze-idle-success | POST /api/spec-freeze 冻结无在跑 agent 的 spec：200 + {ok:true, frozen:true}；随后 GET /api/specs 列表确认该 spec 状态为 blocked。出处：core/dashboard/routes/spec_routes.py:163（_api_spec_freeze，成功 → 200 + ok/frozen）；spec freeze-stop-inflight-agents/spec.md『冻结即停』WHEN 冻结。 | pass | 0/5 | - |
| api-freeze-inflight-stopped-agents | POST /api/spec-freeze 冻结有在跑 implementer 的 spec：按 proposal Impact『freeze_spec 返回值扩展（stopped_agents 计数）』与前端冻结反馈验收，响应须含 stopped_agents 计数（本 fixture 有 1 个在跑 run → stopped_agents:1）。当前实现实测 freeze_spec 返回值无 stopped_agents 字段（tasks 6.x 仅扩展前端类型，后端计数缺失）——本场景按 SPEC 验收断言，若失败即为实现缺口。出处：proposal.md Impact『core/dashboard/data/：freeze_spec 返回值扩展（stopped_agents 计数）』；core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:165（stopped_agents>0 提示分支）。 | failed（已修正） | 1/4 | product-bug |
| api-freeze-done-terminal-rejected | POST /api/spec-freeze 冻结 done 终态 spec：200 + {ok:true, frozen:false, error 含终态原因}（终态不可冻结，不破坏语义）。出处：core/dashboard/routes/spec_routes.py:163 契约（终态 → 200 + frozen:false）；spec freeze-stop-inflight-agents 无直接场景，属『冻结即停』边界防破坏。 | pass | 0/4 | - |
| api-freeze-not-found-404 | POST /api/spec-freeze 冻结不存在的 spec：404 + 错误信息（spec not found）。出处：core/dashboard/routes/spec_routes.py:171（!found → 404）。 | pass | 0/2 | - |
| api-unfreeze-hold-restores-status | POST /api/spec-unfreeze 解冻带 _frozen_hold 的冻结 spec：200 + {ok:true, frozen:false}，随后 GET /api/specs/fs-hold?project= 详情确认 status 恢复为冻结前原状态 implementing。出处：core/dashboard/routes/spec_routes.py:191（_api_spec_unfreeze）；spec freeze-stop-inflight-agents/spec.md『解冻后在保留分支自动续做』（状态恢复为冻结前状态）。 | pass | 0/5 | - |
| api-delete-idle-sync | POST /api/spec-delete 删除无在跑 agent 的 spec：200 + {ok:true, archived:true, archive_path}（同步软删除，无异步往返），随后 GET /api/specs 列表确认该 spec 条目已移除。出处：core/dashboard/routes/spec_routes.py:680（无在跑 → 既有同步软删除）；spec delete-stop-inflight-agents/spec.md『无在跑 run 时保持既有行为（直接软删除）』。 | pass | 0/4 | - |
| api-delete-inflight-daemon-down-409 | POST /api/spec-delete 删除有在跑 implementer 的 spec（dl-inflight，非终态 run 文件）：异步受理前置托管态校验——验证实例 daemon 未受 supervisor 托管（hosting_state 非 managed）时返回 409 明确拒绝（信号无人消费），且不写 spec_delete_request.json。出处：core/dashboard/routes/spec_routes.py:707-717（有在跑 → request_spec_delete → unmanaged/daemon_down → 409）；spec delete-stop-inflight-agents/spec.md『daemon 未托管时拒绝』。验证实例形态（无 daemon 托管）与『有在跑 agent 时返回受理（202）』场景的环境前提不符——本场景按环境可达的 409 分支断言。 | pass | 0/2 | - |
| api-delete-not-found-404 | POST /api/spec-delete 删除不存在的 spec：404 + 错误信息（spec not found，幂等不发文件操作）。出处：core/dashboard/routes/spec_routes.py:728（!found → 404）。 | pass | 0/2 | - |
| web-freeze-idle-modal-button | SPEC 列表「修改状态」弹窗渲染冻结区块：未冻结 spec（fs-web-idle）弹窗含「冻结 SPEC」按钮与说明文案「冻结后 daemon 停止调度该 SPEC，直到手动解冻」。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:523-528（未冻结分支 + 冻结 SPEC 按钮）；列表入口 core/dashboard/static/src/pages/projects/list.tsx:894（key:status 修改状态菜单）；路由 core/dashboard/static/src/app.tsx:107（/projects/:name，v3 hash 路由）。 | pass | 0/4 | - |
| web-freeze-inflight-stopped-hint | 冻结有在跑 implementer 的 spec（fs-web-inflight）的停止反馈验收：toast 须含「已停止 1 个在跑 agent」与「进度已留存，解冻后可续做」（stopped_agents>0 分支）。当前实现后端 freeze_spec 未返回 stopped_agents（实测缺失，proposal Impact 声明）→ 本场景按 SPEC 验收断言，失败即暴露实现缺口。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:165-168；spec freeze-stop-inflight-agents/spec.md『冻结后的停止提示』。 | failed（已修正） | 2/4 | product-bug |
| web-freeze-done-modal-no-freeze | 终态 spec（fs-done）「修改状态」弹窗不含冻结操作（冻结破坏终态语义）：断言弹窗可见且无「冻结 SPEC」按钮。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:517-518（nonTerminal 条件渲染冻结区块）；列表入口 list.tsx:894。 | pass | 0/3 | - |
| web-delete-confirm-text | 删除确认弹窗文案：确认删除 spec（dl-web-idle）时弹窗展示「若有在跑的 agent 会先停止并留存进度」说明（先停后删语义），取消按钮可用且未触发删除。出处：core/dashboard/static/src/pages/projects/list.tsx:765-770（6.4 先停后删文案）；spec delete-stop-inflight-agents/spec.md『前端删除的停止反馈』。 | pass | 0/5 | - |
| web-freeze-idle-confirm-success | 冻结无在跑 agent 的 spec（fs-web-idle）成功反馈：确认后 toast「SPEC「fs-web-idle」已冻结，daemon 停止调度」（stopped_agents 为 0/缺省分支，不展示停止计数提示）。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:164-170（freezeSpec 成功 → stopped_agents 缺省走 message.success 无计数提示）；spec freeze-stop-inflight-agents/spec.md『无在跑 agent 时不展示停止提示』。 | pass | 0/3 | - |
| web-delete-idle-sync-success | 删除无在跑 agent 的 spec（dl-web-idle）同步完成：确认删除后该 spec 行从列表消失（STATE 移除 + 目录移入 archive），不展示「正在停止 N 个」类提示。出处：core/dashboard/static/src/pages/projects/list.tsx:776-790（deleteSpec 同步分支 + load 轮询）；spec delete-stop-inflight-agents/spec.md『无在跑 agent 时不展示停止提示』。 | pass | 0/2 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

场景集与持久化集一致，无变更。

