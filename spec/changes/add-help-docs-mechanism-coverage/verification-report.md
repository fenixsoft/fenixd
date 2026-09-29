# 验证报告：add-help-docs-mechanism-coverage

> ⚠️ 本报告由框架于 2026-09-26T11:35:36Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-26T11:35:36.639617+00:00

## 结论：✅ 通过（verified）

**状态：verified — 33/33 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 33/33 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 33 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.95M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| help-docs-inventory-present | 交付基线（空状态核对）：tasks.md 声明的 10 份 docs/help 修改文档全部存在且非空，docs/help 目录 16 个 md 完整在位（出处 spec/changes/add-help-docs-mechanism-coverage/tasks.md:3-24；docs/help/ 目录实况 2026-09-26 实测） | pass | 0/4 | - |
| mech-env-exempt-admin-handshake | 机制1 env 豁免 admin 握手：05 章新增小节可发现——两级豁免防线判据（级一 judge 前/级二 judge 后）、共享计数 _inconclusive_attempts、3/4 次阈值键、admin DISPOSITION 放行守卫（陈旧放行不复用）、report.json backlink 回链与「verified 卡在 implemented」排查指引；附 escalation.py 代码锚点（出处 docs/help/05-verification.md:108-119 实测取证；spec.md 机制清单第 1 项） | pass | 0/12 | - |
| mech-fastlane-channel | 机制2 fastlane 小缺陷轻量通道：三条件准入（失败=1/影响面≤3 文件/无争议标记）、code-fix 主树直接修复+子集重验（失败∪depends_on 前置链∪下游链）、连败 2 次回落整轮、fastlane_decision.json 判定记录可发现；附 fastlane.py 锚点（出处 docs/help/05-verification.md「fastlane 小缺陷轻量通道」节实测取证；spec.md 第 2 项） | pass | 0/10 | - |
| mech-judge-governance-verdict-cache | 机制3 judge 重裁决治理与 verdict 缓存：轮内停派+judge_rerun_cap 人工升级、spec 级 5 次硬上限 blocked（_MAX_JUDGE_RERUNS，冻结后不因重启清零）、verdict_cache.json 指纹缓存裁剪修复轮重验范围可发现；附 judge_gate.py/verdict_evidence.py 锚点（出处 docs/help/05-verification.md「judge 门禁治理与 verdict 缓存」节实测取证；spec.md 第 3 项） | pass | 0/9 | - |
| mech-false-fail-defense-rows | 机制4+5 伪失败防线表补两行：迟到 verifier 结果直接丢弃不覆写终态（legacy.py 单一收敛点 + verified 收敛点回收在飞 verify 车道）；pytest 逐测 10s signal 硬门与 tests/timeout-allowlist.yaml 三字段豁免登记可发现（出处 docs/help/05-verification.md 伪失败防线表行实测取证；spec.md 第 4/5 项） | pass | 0/11 | - |
| mech-infra-budget-exempt | 机制6 infra 失败预算豁免：infra 轮不计入 MAX_VERIFY_FAIL_ROUNDS 冻结判定、验证 run 预算幂等退款（_infra_refunded_run_ids）、STATE 观测字段 _infra_failure_count/_verify_infra_rounds、与 06 章三类预算交叉引用可发现；附 state_machine.py 锚点（出处 docs/help/05-verification.md infra 豁免段实测取证；spec.md 第 6 项） | pass | 0/8 | - |
| mech-parallel-plan-artifact | 机制7 并行出题产物：parallel_plan.json 状态机（dispatched→completed/failed/cancelled/frozen→consumed）与失败半成品隔离（.parallel-discarded 改名+discarded 标记）在 05 章与 10 章文件地图双落点可发现；附 engine.py 锚点（出处 docs/help/05-verification.md 并行出题段、docs/help/10-artifacts.md 实测取证；spec.md 第 7 项） | pass | 0/9 | - |
| mech-run-stall-budget | 机制8 run 止损三件套：取消旗标跨 attempt、in-place retry 让位、停滞复合判停（≥120s 慢往返/占比过半+无产物进展）、agents.run_stall_budget_* 三键（缺省关闭）与超时活性监督的关系可发现；附 runner.py/config.py 锚点（出处 docs/help/06-governance.md「run 止损」节实测取证；spec.md 第 8 项） | pass | 0/12 | - |
| mech-transient-unseal-progressive-recovery | 机制9 瞬断解封渐进恢复：解封后态序（冻结>post-unseal hold>探针观察窗>错峰放行>open）、transient_unseal_* 五键（base 60/max 600/probe 120/stable 1800/stagger 30，0=禁用）、「ready 却迟迟不派发」排查入口可发现；附 provider_circuit.py 锚点（出处 docs/help/06-governance.md 瞬断治理节实测取证；spec.md 第 9 项；键名以代码实读为准 transient_unseal_backoff_max_seconds） | pass | 0/12 | - |
| mech-signal-death-cooldown | 机制10 信号死法冷却：同 SPEC 连续 3 次 Exit 143/负信号死法→600s 冷却、期间全 agent 类型重派跳过不耗预算、到期自动恢复可发现；附 provider_circuit.py/queue.py 锚点（出处 docs/help/06-governance.md「信号死法冷却」段实测取证；spec.md 第 10 项） | pass | 0/9 | - |
| mech-concurrent-review-guard | 机制11 SPEC 并发在飞守卫：评审收尾不打回实现中 SPEC（_review_skipped_result 侧车）、实现派发前在飞评审探测（进程表→流文件→queued，异常 fail-open）、实现合并收尾补记 ready→implementing 转移可发现；附 spec_review.py/queue.py 锚点（出处 docs/help/06-governance.md 方案评审与实现车道交叉守卫段实测取证；spec.md 第 11 项） | pass | 0/9 | - |
| mech-cancelled-hold-resume | 机制12 取消保持态与恢复运行：人工取消 run 后 _cancelled_hold 有意等待语义（恢复链路跳过/不重派）、与 _frozen_hold 并列互斥（冻结终止先清取消保持）、唯一出路 Dashboard「恢复运行」（保留分支三层判定→_recovery_resume 续做+scheduling_kick 唤醒；终态/冻结/非保持态幂等拒绝）可发现；附 state_machine.py 锚点（出处 docs/help/03-lifecycle.md「取消保持态」节实测取证；spec.md 第 12 项） | pass | 0/11 | - |
| mech-stash-pop-triage | 机制13 stash pop 冲突三分诊：autostash pop 冲突三态处置链（三方 merge-file 重试→恢复 commit 只入库冲突路径留审计→兜底落工作区+登记 disposition）与 stash 条目保留记账可发现；附 stash_guard.py 锚点（出处 docs/help/07-safeguards.md autostash 段实测取证；spec.md 第 13 项） | pass | 0/9 | - |
| mech-mergeback-inflight-guard | 机制14 merge-back spec 目录在飞守卫：合并前检 spec/changes/ 未提交编辑→有界顺延（缺省 30 分钟/3 轮，_merge_retry_pending 记账，不重派不耗预算）→超限回落人工通道、守卫自身 fail-open 可发现；附 mergeback.py 锚点（出处 docs/help/07-safeguards.md「merge-back 的 spec 目录在飞守卫」节实测取证；spec.md 第 14 项） | pass | 0/8 | - |
| mech-relocation-writeback-same-layer | 机制15 relocation writeback 同层修正：judge 修正写「生效声明命中层」（worktree 命中写 worktree 并提交分支/主树命中写主树/branch 来源 dispute 审计核销）、修正后按守卫读取基准复检、同族复发独立持久化熔断可发现；附 deliverables.py 锚点（出处 docs/help/07-safeguards.md 交付物守卫段实测取证；spec.md 第 15 项） | pass | 0/9 | - |
| mech-signal-probe-and-alert-noise | 机制16+17 信号前置探测与告警降噪治理：请求型困境信号摄取时只读探测（诉求已满足即 handled 免唤起 admin）、处置终态回写闭环；daemon_errors 指纹级重启首扫冷却+孪生合并、fixture 项目抑制、spec_delivered_no_content 不冻结可发现；附 admin_monitor.py/spec_integrity.py 锚点（出处 docs/help/07-safeguards.md 告警系统段实测取证；spec.md 第 16/17 项） | pass | 0/13 | - |
| mech-stale-dangling-timeout | 机制18 陈旧悬空超时：陈旧态悬空超 stale_code_selfheal.max_dangling_seconds（缺省 14400s=4h，0=关）不再等全空闲、走规划性重启并落 stale_code_dangling_timeout 升级告警可发现；附 fenixd.py 锚点（出处 docs/help/07-safeguards.md 陈旧自愈段实测取证；spec.md 第 18 项） | pass | 0/7 | - |
| dash-quality-gates-card | 机制19 质量门禁整链：SPEC 详情页「质量门禁」Card 六道门固定顺序（full-suite/frontend-build/code-review/interaction-contract/result-artifact-gate/deliverable-guard）、六态与 done=passed+skipped、quality-gates.json 嵌套形态唯一合法、终态豁免（pushed 后 full-suite→skipped、merge_base==head_commit 豁免）、列表页橙色门禁阶段两窗口、「卡在哪道门」排查指引可发现；附 quality_gates.py/summary.py 锚点（出处 docs/help/08-dashboard.md「质量门禁 Card」节实测取证；spec.md 第 19 项） | pass | 0/17 | - |
| dash-session-facet-fullpicture | 机制22 会话接入分面全貌：显式开始/SSE 流+uuid 去重/composer 斜杠命令与 skill 补全（150ms 防抖）/`@` 文件提及（files 上限 5000）/commands 缓存语义/草稿 localStorage 持久化/Enter 发送 Shift+Enter 换行/停止会话/truncated 提示/VisualViewport 移动端适配/空闲 1800s 回收可发现；附 SessionComposer/session_routes.py/session_manager.py 锚点（出处 docs/help/08-dashboard.md「会话接入」分面实测取证；spec.md 第 22 项） | pass | 0/20 | - |
| dash-runlog-readability | 机制23 运行记录可读性：心跳类事件静默、信息类语义系统条（provider 切换→模型路由、瞬断重试→退避提示）、同类工具聚合、thinking 折叠+开关、「加载更早事件」向前分页可发现；附 claude-msg/ 组件目录锚点（出处 docs/help/08-dashboard.md 运行记录段实测取证；spec.md 第 23 项） | pass | 0/9 | - |
| dash-labels-calibrated-and-old-removed | 机制26 UI 名称校准（异常路径）：分面 label 逐字改为「功能开发/代码审查/测试回归/项目架构/会话接入」且旧名「SPEC 开发」「Claude Code 会话」全篇不再出现；设置页页签现状（用户级 11 个+项目级追加 3 个）与「质量」页签 2 张 Card+ocr 环境探测提示可发现；附 settings/index.tsx 锚点（出处 docs/help/08-dashboard.md 分面与设置页段实测取证；spec.md 第 26 项与结构修复第 3 项相关面） | pass | 0/14 | - |
| dash-trigger-ack-fenix-ignore | 机制20+21 触发受理回链三态与 fenix-ignore：代码审查分面五动作（全库审查/当期审查/自动修复/生成修复 SPEC/全部忽略）、run-result 三态反馈（started/dropped/failed）、受理窗口二次 POST 409 code_review_ack_pending+前端两段轮询禁用、[fenix-ignore:<item_id>] 注释固化误报裁决（复核不再上报）、批量置 ignored 终态可发现（出处 docs/help/08-dashboard.md「代码审查」分面段实测取证；spec.md 第 20/21 项） | pass | 0/15 | - |
| dash-detail-tabs-toolbar-regression-btn | 结构修复3+详情行工具条+回归转台账：SPEC 详情页页面级 5 页签全集（运行时间轴/场景结果/Bug 列表/失败截图/Hook）与文档弹窗 5 页签（SpecDocModal：需求背景/详细设计/任务清单/测试场景清单/验证报告）分层表述自洽；详情行工具条「恢复运行」动作（取消保持态一键恢复、保留分支续做、幂等拒绝）；测试回归分面「自动修复回归问题」按钮（code_fix_request.json+manual_authorized、CodeFixProgressCard 条级进度+startup_stage、regression- 前缀转台账）可发现；附 detail.tsx 锚点（出处 docs/help/08-dashboard.md 详情页/回归分面段实测取证；spec.md 结构修复第 3 项+机制 12/25 的 08 落点） | pass | 0/20 | - |
| config-keys-agents-lane | 配置键补录（agents 组）：agents.timeout_overrides.*（角色白名单+≥300s 下限+supervision-judge ≥1s 特例+参与 absolute_max 派生）、impl_run_budget_max（缺省 100、硬天花板 1000）与 per-spec 覆盖 impl_run_budget_override、verify_redo_budget（缺省 3、仅重启恢复路径计数、超限 verify_redo_exhausted 冻结）键表行+默认值可发现，且各键在代码侧真实存在（出处 docs/help/09-config.md agents 段实测取证；spec.md Scenario「新增配置键全键参考落位」） | pass | 0/18 | - |
| config-keys-governance-dangling | 配置键补录（治理+悬空组）：transient_unseal_* 五键（60/600/120/1800/30）、run_stall_budget_* 三键（缺省关闭，5 次/10 分钟）、stale_code_selfheal.max_dangling_seconds（缺省 14400，0=关）在 09 章键表行形态（键｜默认值｜范围｜生效方式）+06 章键表交叉可发现，且各键在代码侧真实存在（出处 docs/help/09-config.md 键表行与 docs/help/06-governance.md:139-141 实测取证；spec.md 第 8/9/18 项） | pass | 0/19 | - |
| config-keys-admin-verify | 配置键补录（admin/verify 组）：admin.code_review.scope（window/full，恰为 full 才走全仓，审查窗口与自省同源限定 window 档）与 stall_alert_minutes（缺省 15）、admin.review_stall_minutes（缺省 30，mtime+CPU 双判据）、admin.mergeback_wip_orphan_grace_minutes（缺省 30）、verify.repo_code_review_concurrency（缺省 4）、impl_code_review_mode（gate/advisory 缺省 gate）、impl_code_review_lane_timeout_sec（缺省 2400）键表行+默认值可发现，且各键在代码侧真实存在（出处 docs/help/09-config.md 实测取证；spec.md 第 20/21/25 项相关键面） | pass | 0/20 | - |
| config-code-fix-lane-mechanisms | 机制25 code-fix 车道全机制：批内并行（同波≤4、单写者落盘、纯提示词协议）、WIP defer 台账双门（90min/6 次）+零预算语义、占用者协调（订阅在飞 run 终态/无主 WIP 宽限升级）、选批 WIP 预检（_wip_overlap_at_select）、批失败自愈（fail_count 预算 3+墓碑跨链）、salvage 自动提交兜底、LLM 拒绝出口（false_positive/not_worth_fixing→mark_ignored）、手动整链授权（code_fix_request.json+manual_authorized）、回归一键转台账（regression- 前缀/超时锚定 verify.yaml/复发重开）可发现；附 code_fix.py 锚点（出处 docs/help/09-config.md admin.code_review_fix 节实测取证；spec.md 第 25 项） | pass | 0/27 | - |
| artifacts-state-fields-and-filemap | STATE 字段与文件地图补全：10 章 STATE 清单覆盖显式键（start_after/frozen_until/impl_run_budget_override）与「_ 前缀字段无条件透传持久化、完整集合以 state_machine.py 为准」内部字段小表（_verify_redo_count/_frozen_hold/_cancelled_hold/_env_block_rounds/_verify_fail_rounds/_fastlane_fail_streak/_review_skipped_result 等）；.fenix/ 文件地图收录 parallel_plan.json/fastlane_decision.json/quality-gates.json/architecture//scheduling_kick//spec_delete_request.json/code_fix_request.json/code_review_request_result.json/regression .running/restart_history.jsonl/supervisor_runtime.json/code-review 分片与 fix-* 三件台账（出处 docs/help/10-artifacts.md 实测取证；spec.md Scenario「STATE 字段与文件地图补全」） | pass | 0/35 | - |
| logs-code-review-artifacts | 11 章日志章补全：code-review/ 工作区表收录分片产物行（out-<run_id>-b<N>.jsonl）、fix-* 台账三件（fix-deferred/fix-progress/fix-failed）、code_review_request_result.json；条目态枚举修正为 open/in_spec/resolved/ignored（fixing 是批 phase 非条目态）（出处 docs/help/11-logs.md 实测取证；spec.md tasks 6.3） | pass | 0/8 | - |
| structure-fix-04-cli-tables | 结构修复1（04-cli.md 表格边界）：托管态表仅含 managed/unmanaged/stopped 三态行且 fenix_archive.py/launch-chrome-extension.js/test_for.py 三行不再混入（awk 截取「### 托管态」至下一「## 」节段计数=0）；三脚本归位 bin/ 表（节段计数=3）；bin/ 表补录 fenix_cli.py（promote/reflow/activate/review/unfreeze 子命令）/fenix_status.py/fenix_verify_contract.py/ocr_review.py/run_full_suite.py（出处 docs/help/04-cli.md「bin/ 辅助脚本」与「### 托管态」节实测取证；spec.md 结构修复第 1 项） | pass | 0/15 | - |
| structure-fix-12-faq-numbering | 结构修复2（12-faq.md）：标题编号序列连续 1-13 无重复（原重复「## 9.」已顺延）；「烧钱快」条目处置补 run 止损指引（agents.run_stall_budget_* 缺省关闭、[run-stall-budget] 终止前缀）；第 1 条 SPEC 卡 ready 根因按宽松优先级调度口径核对（pm.dispatch.aging 逐级放宽降档）（出处 docs/help/12-faq.md 标题与第 1/3 条实测取证；spec.md 结构修复第 2 项） | pass | 0/10 | - |
| dash-filter-url-sticky | 机制24 SPEC 列表筛选 URL sticky：tab/搜索词/状态多选/类型/已归档过滤写入 URL，刷新/分享/前进后退保留；白名单 fail-safe 解析、非法参数静默忽略可发现；附 listFilters.ts 锚点（出处 docs/help/08-dashboard.md「功能开发」分面筛选段实测取证；spec.md 第 24 项） | pass | 0/7 | - |
| sister-spec-baseline-regression | 回归点（design D1 只增不删）：姊妹 SPEC fix-help-docs-contra-behavior 落地的新口径与本 SPEC 编辑前既有表述在重叠文档中完好——05 章修复循环三轮熔断、08 章架构图两段式超时（720/1080）、06 章派发锁退避表、09 章 code_review_fix 定向重试现场即弃+分片直写、02 章 11 状态枚举引用、12 章烧钱快条目、03 章冻结与解冻、07 章 autostash 段均未被本 SPEC 的新增小节编辑删除或改写（出处 docs/help/ 各重叠文件 2026-09-26 实测取证；design.md D1/R1） | pass | 0/11 | - |

## 本轮场景集变更

当前稳定场景集共 33 个（第 1 轮）。

- 首轮写入 33 个场景

