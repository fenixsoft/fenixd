## ADDED Requirements

### Requirement: 缺失机制文档化

docs/help 中下列近两周演进的重要机制 MUST 各有可发现的描述（新小节或既有小节内段落），每处 MUST 附权威代码锚点供实现时实读核对：

1. **env 豁免 admin 握手**（05-verification.md）：两级防线判据（级一 judge 前全批 blocked-env→inconclusive；级二 judge 后断言归因全 env 在采纳前拦截）、共享计数 `_inconclusive_attempts`、`verify_engine.inconclusive_max_attempts`=3 / `inconclusive_escalate_attempts`=4、admin DISPOSITION 放行守卫（放行须晚于本轮 SIGNAL，陈旧放行不复用）、report.json `admin_disposition_backlink` 回链。锚点 `core/pm_engine/verification/escalation.py:46,70,1316,1410-1422,1564,1645`。
2. **fastlane 小缺陷轻量通道**（05-verification.md）：三条件（失败场景=1、judge 归因影响面 ≤3 文件、无争议标记）→ code-fix 主树直接修复 + 子集重验（失败 ∪ depends_on 前置链 ∪ 下游链）；连续 2 次失败回落整轮（`_fastlane_fail_streak`）；判定记录 `.fenix/verify-progress/<spec>/fastlane_decision.json`。锚点 `core/pm_engine/verification/fastlane.py`。
3. **judge 重裁决治理与 verdict 缓存**（05-verification.md）：轮内真实派发 ≤2 停派+人工升级 `judge_rerun_cap`、spec 级 `_MAX_JUDGE_RERUNS`=5 超限 blocked；verdict 缓存（verdict_cache.json）供修复轮重验范围裁剪。锚点 `core/pm_engine/verification/judge_gate.py:24-30,255-300`、`verdict_evidence.py:1053`。
4. **迟到 verifier 结果防御**（05-verification.md 伪失败防线表补行）：spec 非 testing 时结果丢弃不覆写终态；verified 收敛点回收在飞 verify 车道。锚点 `core/pm_engine/verification/legacy.py:12,59,354,483,555`、`core/pm_engine/engine.py:1139-1183`。
5. **逐测超时门**（05-verification.md 或 06-governance.md）：pytest 全局单用例 10s signal 硬门；豁免须登记 `tests/timeout-allowlist.yaml`（nodeid+timeout_seconds+reason 三字段机械校验）。锚点 `pytest.ini`、`tests/timeout-allowlist.yaml`。
6. **infra 失败预算豁免**（05-verification.md / 06-governance.md）：infra 失败轮不计入 MAX_VERIFY_FAIL_ROUNDS 冻结判定、验证 run 预算退款幂等（`_infra_refunded_run_ids`）；STATE 字段 `_infra_failure_count`/`_verify_infra_rounds`。锚点 `core/state_machine.py:247-260`、archive `2026-09-21-evo-infra-failure-budget-exempt`。
7. **并行出题产物**（05-verification.md + 10-artifacts.md）：`parallel_plan.json` 状态机（dispatched→completed/failed/cancelled/frozen→consumed）与失败半成品隔离。锚点 `core/pm_engine/engine.py:853-877`。
8. **run 止损三件套**（06-governance.md）：取消旗标跨 attempt 生效（not_running 分支也登记）；in-place retry 对并行出题标记 discarded/quarantined 让位；停滞复合判停（连续 N 次 ≥120s 往返或 stall 占比过半且 M 分钟无产物进展）；`agents.run_stall_budget_enabled`（缺省 false）/_stalls=5/_window_minutes=10。锚点 `core/agent_runner/runner.py:169,4520,5085-5170`、`core/config.py:225-265`。
9. **瞬断解封渐进恢复**（06-governance.md 瞬断治理节）：解封后态序 冻结>post-unseal hold>探针观察窗>错峰放行>open；`agents.transient_unseal_backoff_base_seconds`=60/_max_seconds=600/_probe_window_seconds=120/_stable_window_seconds=1800/_release_stagger_seconds=30（base/stagger=0 禁用）；「ready 却迟迟不派发」排查入口。锚点 `core/agent_runner/provider_circuit.py:118-129,939-1150`、`core/pm_engine/dispatch/queue.py:525-560`。
10. **信号死法冷却**（06-governance.md）：同 spec 连续 3 次信号死法（Exit 143/负信号）→ 600s 冷却，期间全部 agent 类型重派跳过、不耗预算、到期自动恢复。锚点 `core/agent_runner/provider_circuit.py:131-142`、`queue.py:462-478`。
11. **SPEC 并发在飞守卫**（03-lifecycle.md 或 07-safeguards.md）：评审收尾遇实现中 spec 跳过回退落 `_review_skipped_result` 侧车；实现派发前查在飞评审（进程表→流文件→queued 前置→陈旧锚点 fail-open）；实现合并收尾见 ready 先补记 ready→implementing 再推 implemented。锚点 `core/pm_engine/dispatch/queue.py:277-330,1264,2577`、`core/pm_engine/spec_review.py:41,465`。
12. **取消保持态与恢复运行**（03-lifecycle.md 冻结节旁新增取消小节 + 08-dashboard.md 详情行工具条）：人工取消 run → `_cancelled_hold` 有意等待态（重启恢复跳过、不重派、唯一出路显式复位）；Dashboard「恢复运行」按钮（保留分支三层回落判定 → 命中走 `_recovery_resume` 续做 + scheduling_kick 即时派发；不通过降级普通重派；终态/冻结/非保持态幂等拒绝）。锚点 `core/state_machine.py:229-236,1836-1846`、`core/dashboard/data/admin_actions.py:725-830`。
13. **stash pop 冲突三分诊**（07-safeguards.md autostash 段展开或姊妹 SPEC 已改写处的细化）：态 1 三方重试 / 态 2 恢复 commit 只入库冲突路径留审计 / 态 3 兜底落工作区+登记 disposition。锚点 `core/worktree_manager/stash_guard.py:134-165,274-360`。
14. **merge-back spec 目录在飞守卫**（07-safeguards.md 或 06-governance.md）：合并前检 spec/changes/ 在飞未提交编辑 → 有界顺延（缺省 30 分钟/3 轮，`_merge_retry_pending`），超限回落人工通道、不重派整轮不耗预算。锚点 `core/worktree_manager/mergeback.py:152,213-269`。
15. **relocation writeback 同层修正**（07-safeguards.md 交付物守卫段）：judge typo/reference 修正写「生效声明命中层」（worktree 命中写 worktree 并提交分支、主树命中写主树、branch 来源走 dispute 审计核销）；修正后按守卫读取基准复检；同族复发熔断（独立持久字段）。锚点 `core/deliverables.py:624-700,830-891`。
16. **信号前置探测+处置回写**（07-safeguards.md 告警系统段）：请求型信号（verify_regression_missing/verify_contract_missing/build_artifact_paths_missing）摄取时只读探测、诉求已满足即 handled 免唤起 admin；admin 处置终态回写 mark_signal_handled。锚点 `core/admin_monitor.py:1956-1988,3592-3604`。
17. **告警降噪治理**（07-safeguards.md）：daemon_errors 指纹级重启首扫冷却+孪生指纹合并、已交付 spec 改产 spec_delivered_no_content（不冻结）、fixture 项目抑制。锚点 `core/admin_monitor.py:111-136,866,209`、`core/pm_engine/spec_integrity.py:52`。
18. **陈旧悬空超时**（07-safeguards.md 陈旧自愈段补）：陈旧态悬空超 `stale_code_selfheal.max_dangling_seconds`（缺省 14400s，0=关）不再等全空闲、走规划性重启，落 `stale_code_dangling_timeout` 升级告警。锚点 `core/config.py:1497-1623`、`fenixd.py:1557-1584`。
19. **质量门禁整链**（08-dashboard.md + 05-verification.md 交叉）：SPEC 详情页「质量门禁」Card（6 道门固定顺序 full-suite/frontend-build/code-review/interaction-contract/result-artifact-gate/deliverable-guard，status 六态，done=passed+skipped）；列表页 gates 橙色阶段两窗口；落盘 3 项合成 6 道（quality-gates.json 嵌套 gates 形态唯一合法）；终态豁免（pushed/verified/done 的 full-suite→skipped、ocr 门 merge-base==head_commit 豁免）；平铺形态容错+兜底文案+对账告警。锚点 `core/dashboard/data/quality_gates.py:25-65,171-207,397-456,512-543`、`core/dashboard/data/summary.py:307-329`。
20. **fenix-ignore 注释标记**（08-dashboard.md 代码审查分面段或 09-config.md code_review 节）：`[fenix-ignore:<item_id>] <理由>` 注释固化误报裁决，审查 LLM 复核 MUST NOT 再上报；「全部忽略」批量置 ignored 终态；code-fix 以 `IGNORE_ELIGIBLE_SKIP_REASONS` 走 mark_ignored。锚点 `core/code_review.py:1421-1463`、`core/agent_runner/maintenance_runs.py:1997-2010`、`core/code_fix.py:91`。
21. **触发受理回链三态**（08-dashboard.md 代码审查分面段）：手动触发后 run-result 三态反馈（started/dropped/failed）、受理窗口内二次 POST 409 `code_review_ack_pending`、前端两段轮询按钮禁用。锚点 `core/code_review.py:730-800`、`core/dashboard/routes/code_review_routes.py:348-397`。
22. **会话接入分面全貌**（08-dashboard.md 新增小节）：显式「开始会话」启动、SSE 实时流+uuid 去重、composer `/` 斜杠命令与 skill 补全（150ms debounce、键盘导航）、`@` 文件提及（top10）、草稿按项目 localStorage 持久化、Enter 发送/Shift+Enter 换行、停止会话、空闲 1800s 回收、truncated 提示、移动端 VisualViewport 键盘适配；`/api/session/files`（git ls-files 上限 5000）与 `/api/session/commands`（init 事件缓存、无在飞会话空数组）数据源。锚点 `core/dashboard/static/src/pages/projects/components/session/SessionPanel.tsx`、`SessionComposer.tsx`、`core/dashboard/routes/session_routes.py:17,195`。
23. **运行记录可读性**（08-dashboard.md SPEC 详情段）：心跳类事件静默、信息类语义系统条（provider_marker→模型路由、transient_retry→瞬断退避）、同类工具聚合、thinking 折叠+时长+开关、「加载更早事件」向前分页。锚点 `core/dashboard/static/src/pages/projects/components/detail/`（runEvents.ts/toolGrouping.ts/ClaudeOutputPane.tsx）。
24. **SPEC 列表筛选 URL sticky**（08-dashboard.md）：tab/搜索词/状态多选/类型/已归档过滤写入 URL，刷新/分享/前进后退保留；白名单 fail-safe 解析。锚点 `core/dashboard/static/src/pages/projects/listFilters.ts:11-63`。
25. **code-fix 车道全机制**（09-config.md admin.code_review_fix 节展开 + 08-dashboard.md 进度卡）：批内并行（同波 ≤4、单写者落盘，纯提示词协议）、WIP defer 台账（`.fenix/code-review/fix-deferred.json`，90min/6 次双门）、占用者协调（订阅在飞 run 终态/无主 WIP 30min 宽限升级 major）、选批 WIP 预检（wip_overlap_at_select）、批失败自愈（chain_skipped 链内跳过、fail_count 预算达 3 一次性告警）、salvage 自动提交兜底、条级进度+startup_stage 读侧合成、LLM 拒绝出口（false_positive/not_worth_fixing→ignored）、手动「立即自动修复」整链授权（`code_fix_request.json` 信号 + `manual_authorized` 随链持久化）、回归问题一键转台账（regression- 前缀、超时条目锚定 verify.yaml、复发指纹重开）。锚点 `core/code_fix.py`（79-135,778-920,1330-1380,1751-1832,2247-2410,2860-2945）。
26. **UI 名称校准**（08-dashboard.md 全文）：分面 label 逐字改为「功能开发」「代码审查」「测试回归」「项目架构」「会话接入」；SPEC 详情页页面级页签全集枚举（运行时间轴/场景结果/Bug 列表/失败截图/Hook）；设置页页签现状（用户级 11 个 + 项目级追加自省/项目/Hook）；「质量」页签 2 张 Card + ocr 环境探测 Alert。锚点 `core/dashboard/static/src/pages/projects/list.tsx:1295-1455`、`settings/index.tsx:33-48`、`detail.tsx:1216-1560`。

#### Scenario: 机制条目可发现性核对
- **WHEN** 对 docs/help 10 份文档按上述 26 项逐条执行关键词核对（每项至少一个特征词命中，如 fastlane/「恢复运行」/transient_unseal/quality-gates/fenix-ignore/code_review_ack_pending/SessionComposer/parallel_plan）
- **THEN** 26 项全部在对应文档命中，且每处描述附代码锚点（file 路径形态）

#### Scenario: 新增配置键全键参考落位
- **WHEN** 对 09-config.md 的键清单与 core/config.py 实际暴露的用户可配置键比对（timeout_overrides/impl_run_budget_max/verify_redo_budget/transient_unseal_*/run_stall_budget_*/max_dangling_seconds/code_review.scope/stall_alert_minutes/review_stall_minutes/mergeback_wip_orphan_grace_minutes/repo_code_review_concurrency/impl_code_review_mode/impl_code_review_lane_timeout_sec）
- **THEN** 上述键全部有「键｜默认值｜范围｜生效方式」表行或等效段落，且默认值与代码缺省一致（实现时实读核对）

#### Scenario: STATE 字段与文件地图补全
- **WHEN** 对 10-artifacts.md 的 STATE.md 字段清单与 `core/state_machine.py` 序列化键表（含 `_` 前缀透传）比对；对 10/11 章文件地图与 `.fenix/` 实际产物清单比对
- **THEN** STATE 清单覆盖 start_after/frozen_until/impl_run_budget_override 与关键内部字段（_verify_redo_count/_frozen_hold/_cancelled_hold/_env_block_rounds/_verify_fail_rounds/_fastlane_fail_streak/_review_skipped_result 等）并注明「`_` 前缀字段无条件透传持久化」；文件地图收录 parallel_plan.json/fastlane_decision.json/quality-gates.json/architecture//code-review 分片与 fix-deferred.json/fix-progress.json/fix-failed.json/code_review_request_result.json/spec_delete_request.json/restart_history.jsonl/supervisor_runtime.json/scheduling_kick/

### Requirement: 结构与校准修复

docs/help 的结构缺陷 MUST 修复：

1. `04-cli.md` bin/ 辅助脚本表：混入「托管态」表格尾部的三行（fenix_archive.py / launch-chrome-extension.js / test_for.py）归位回 bin/ 脚本表；bin/ 脚本表补录用户可用的主要脚本（至少 fenix_cli.py——promote/reflow/activate/review/unfreeze 子命令、fenix_status.py、fenix_verify_contract.py、ocr_review.py、run_full_suite.py），标注各脚本一句话用途；托管态三态表恢复独立完整。
2. `12-faq.md`：重复的两个「## 9.」编号修正为连续编号（后续条目顺延）；「烧钱快」条目处置补 run 止损指引（`agents.run_stall_budget_*` 开启后停滞 run 自动终止）；第 1 条 SPEC 卡 ready 根因列表核对宽松优先级调度口径。
3. `08-dashboard.md` 文档区描述自相矛盾修复：明确两个层级——文档弹窗 5 页签（需求背景/详细设计/任务清单/测试场景清单/验证报告）与 SPEC 详情页页面级 5 页签（运行时间轴/场景结果/Bug 列表/失败截图/Hook），删除「五个页签……Hook 页签（失败截图之后）」的混排表述。

#### Scenario: 结构修复核对
- **WHEN** 检查 04-cli.md 的两个表格边界（托管态表不含脚本行、bin/ 表含 fenix_cli.py 等）、12-faq.md 的标题编号序列、08-dashboard.md 的页签描述分层
- **THEN** 托管态表仅含三态行；bin/ 表含 fenix_cli.py 及用途列；faq 标题编号无重复；详情页描述出现「运行时间轴/场景结果/Bug 列表」页面级页签枚举且与文档区弹窗页签分层表述清晰
