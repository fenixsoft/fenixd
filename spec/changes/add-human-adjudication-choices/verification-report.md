# 验证报告：add-human-adjudication-choices

> ⚠️ 本报告由框架于 2026-09-22T11:28:08Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-22T11:24:35.349186+00:00

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 27/32 场景通过，5 失败，0 错误（1 个真实产品 Bug）**

32 场景：27 通过、5 失败（0 警告/错误/环境阻塞）。5 个失败场景全部命中同一产品根因并按聚合规则合并为 1 个 major Bug：is_spec_frozen（admin_actions.py:130-142）以 status!='blocked' 提前返回 False，对 reviewing+frozen 的评审器失败冻结误判为未冻结，导致 skip_review_gate 裁决动词在 CLI 直调、API alert-resolve、Web 横幅三条通道全部被拒（400/ok=false），下游终态对账 5 条断言级联失败。其余 27 场景（注册表完整性、choices 发射契约、reset_verification/force_advance 成功与拒绝路径、8 类裁决选项闭环、桶 0 兼容、UI 渲染/执行/失败重试/二次确认、移动端、处置留痕、终态对账非级联项）全部通过。分类计数：product-bug=5 场景（1 个聚合 Bug），test-defect=0，flaky=0，env=0。

| 指标 | 数量 |
| --- | --- |
| 通过 | 27 |
| 失败 | 5 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 18.59M |
| 本链增量 Token（输出） | 0.22M |


## 真实产品 Bug

### BUG-01（severity=major）· output_match / status_code / element_not_exist / no_console_error

- 关联场景：cli-verb-skip-review-gate-success、cli-verb-skip-review-gate-reject-rejected-freeze、api-resolve-skip-review-gate、web-banner-skip-review-popconfirm-execute、cli-resolve-final-state-digest
- 描述：skip_review_gate（人工授权跳过评审门）对「评审器失败冻结」（reviewing+frozen，spec-review-incomplete）全链路不可用：CLI 直调动词、API 端点 /api/alert-resolve、Web 横幅 Popconfirm 三条通道均被守卫以「spec 未处于冻结态（当前 reviewing）」拒绝（ok=false / 400），合法的人工授权请求无法执行；连带 spec-review-rejected 专属拒绝分支不可达，cli-resolve-final-state-digest 五条终态断言级联失败（adj-review-inc/adj-ui-skip/adj-skip-verb 未推进 ready、adj-alert-inc/adj-alert-uiskip 未收口）。影响范围：跳过评审门裁决选项在全部三条消费通道上完全失效（系统性问题，5 场景同根因聚合为 1 个 Bug）。
- 根因：core/dashboard/data/admin_actions.py:130-142 is_spec_frozen 首行 `if entry.get("status") != "blocked": return False`——判定只认 blocked 态，未把结构化 frozen=True 纳入独立判据；reviewing+frozen（评审器失败冻结）被误判为未冻结，skip_review_gate 的全部分支（含 admin_actions.py:1449 评审否决拒绝分支）在该提前返回之后不可达。
- 证据（场景 cli-verb-skip-review-gate-success 结构化证据，引用）：
  - failed_assertions: [{"type": "output_match", "expected": "\"ok\": true", "actual": "ok=false error=spec 未处于冻结态（当前 reviewing），跳过评审门仅对评审器失败冻结开放"}]
  - screenshots: []
  - first_failed_step: 步骤1: 直调 skip_review_gate(adj-skip-verb) 即被拒——is_spec_frozen(admin_actions.py:133) 要求 status=='blocked'，reviewing+frozen 的评审器失败冻结被误判为未冻结，ready 推进/计数清零/留痕断言连带失败


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| seed-adjudication-fixtures | cli 幂等种子：在非夹具项目 activation-showcase（registry 扫描发现恒非 fixture，core/dashboard/registry.py:259-268，其告警进 /api/alerts 聚合可见——fixture 项目被 base.py:47 跳过）重建 22 个 adj-* 合成 spec 块（STATE.md 文本表）、17 条 adj-alert-* 告警记录（choices 字段直接取自注册表 choices_for 快照，adjudication_choices.py:220；stale_code 知情类不带 choices 键=桶 0 兼容形态；sig1/sig2 为 kind=signal 通道）、config.yaml agents.token_budget_millions=12 基线、adj-judge-cap 的陈旧验证进度文件。跨轮残留经「先剥 adj-* 再追加」幂等复位。所有后续场景以此为前置。 | pass | 0/6 | - |
| cli-registry-integrity-digest | 注册表完整性（specs/adjudication-choices-registry「注册表按信号类型返回选项」「未注册信号返回空集」）：直接 import core.dashboard.data.adjudication_choices（纯静态声明模块常量，无 LLM 生成），断言 8 类桶 2 信号全覆盖、每信号选项 id 集与 SPEC 信号表逐项一致、每选项含 id/label/desc/action 四字段、id 同信号内唯一、未注册信号（stale_code/None/空串）返回空元组不抛异常。出处 core/dashboard/data/adjudication_choices.py:30-236。 | pass | 0/2 | - |
| cli-emission-contract-pytest | 发射点接线与端点契约回归（tasks 7.1 交付测试套件）：在验证树根跑 tests/test_adjudication_choices.py 全套（注册表完整性、告警记录 choices 写入与无字段兼容、三动词前置校验/成功/留痕、alert-resolve 成功/非法/重复 409/失败不假成功、发射点逐信号断言含 mergeback SIGNAL 记录携 choices、桶 0 不携带）。只带 -v（不并列 -q，防 pytest 输出退化无 PASSED 行），断言锚点为真实测试名。出处 tests/test_adjudication_choices.py:1-636。 | pass | 0/7 | - |
| cli-administrator-contract-digest | Administrator 处置契约段落地（specs/admin-choices-contract）：agents/administrator.md 增补「裁决选项消费契约」段——先读 signal_type 的注册表选项集、结论优先表达为结构化 choice_id+依据、超出注册表才自由处置并回填 suggested_choice（含 id/label/action 语义）、处置记录结构化字段含 choice_id/suggested_choice 可选键。出处 agents/administrator.md:117-123 与 161-162。 | pass | 0/6 | - |
| cli-verb-reset-verification-success | 裁决动词 reset_verification 成功路径（specs/adjudication-actions「冻结态 spec 重置验证成功」）：对 judge_rerun_cap 冻结的 adj-judge-cap（种子状态 blocked+frozen、_judge_rerun_count=3、_judge_cap_frozen=True、_verify_fail_rounds=2、verify-progress 下 4 个陈旧场景/进度文件+审计侧车 tokens.json）直调动词，断言：场景与进度文件按 spec 名精确删除、tokens.json 生命周期审计侧车保留、judge/验证计数清零、冻结解除、无 branch → BLOCKED→READY 复位路径（resolve_env_blocked_reset_path branch_guard.py:48-50）、steps 明细含「已删除/计数/裁决依据：note」。出处 core/dashboard/data/admin_actions.py:1290-1380。 | pass | 0/9 | - |
| cli-verb-reset-verification-reject-review-freeze | 裁决动词 reset_verification 拒绝路径（specs/adjudication-actions「非验证类冻结被拒绝」）：对 spec-review-rejected（方向不成立）冻结的 adj-reset-rej 无 signal_type 直调，error 文本无验证链特征（judge/验证/重派/预算/verify/inconclusive/env 任一均无，admin_actions.py:1242-1244）→ 拒绝并说明，spec 状态保持 blocked+frozen 不变。 | pass | 0/3 | - |
| cli-verb-force-advance-reject-normal-state | 裁决动词 force_advance 前置校验（specs/adjudication-actions「未冻结 spec 被拒绝」）：对处于 implementing 正常态的 adj-fa-rej 直调 force_advance(target=done) → 拒绝并说明仅对冻结/blocked 开放，spec 状态不变。出处 core/dashboard/data/admin_actions.py:1403-1416。 | pass | 0/3 | - |
| cli-verb-skip-review-gate-success | 裁决动词 skip_review_gate 成功路径（specs/adjudication-actions「评审器连坏冻结的 spec 跳过评审门」）：对 spec-review-incomplete 冻结（reviewing+frozen）的 adj-skip-verb 直调 → 解冻、评审器重试计数清零、reviewing 直推 ready 进入正常实现调度、留痕含「人工授权跳过评审」与 note 原文。出处 core/dashboard/data/admin_actions.py:1435-1494。 | failed（已修正） | 4/5 | product-bug |
| cli-verb-skip-review-gate-reject-rejected-freeze | 裁决动词 skip_review_gate 拒绝路径（specs/adjudication-actions「评审否决冻结不可跳过」）：对 spec-review-rejected（方向不成立）冻结的 adj-skip-rej 直调 → 拒绝并说明该冻结类型不支持跳过（admin_actions.py:1461-1471），spec 保持 reviewing+frozen 不变。 | failed（已修正） | 1/3 | product-bug |
| api-alerts-aggregate-choices-shape | 告警记录携带 choices 字段契约（specs/adjudication-choices-registry「真裁决告警携带选项」+ 前端 payload 形状）：GET /api/alerts?project=activation-showcase 真实端点按项目回读种子记录（admin_store.read_all 按 created 倒序返回，种子 created 为固定未来时间戳，索引确定且不受后续 disposition 追加影响）；choices 由发射点同款 choices_for 快照写入，断言 impl_budget_exhausted 告警（alerts[0]）四选项 id/label/action 与注册表一致且四字段齐备；stale_code 记录位于 alerts[4]（桶 0 无 choices 键的存量兼容形态可正常读取返回）。路由出处 core/dashboard/routes/alert_routes.py:22-36（?project= 分支，base.py:310）与 core/admin_store.py:297-301（read_all 倒序）。 | pass | 0/16 | - |
| api-resolve-force-advance-closed-loop | alert-resolve 一次选择完整闭环（specs/alert-resolve「选择即完整闭环」+「重复处置被拒绝」）：对 impl_budget_exhausted 冻结告警 adj-alert-dup 选 force_advance 附 note，单次调用完成 动作执行+解冻推进 done+handled+DISPOSITION 留痕（choice_id/note/动作摘要/source=alert-resolve）；随后同告警重复提交 → 409 冲突不重复执行。留痕对活动区可见由 web-activities-disposition-trail 以 note 唯一锚点复核。路由出处 core/dashboard/routes/alert_routes.py:138-274（POST /api/alert-resolve，base.py:367）。 | pass | 0/12 | - |
| api-resolve-illegal-choice-400 | 非法选择被拒绝（specs/alert-resolve「非法选择被拒绝」）：对 signal_type=token_budget 的告警 adj-alert-token 提交 force_advance（不在 ignore/freeze_stop_loss/raise_budget 选项集）→ 400 且错误信息列出该信号合法选项集；spec 状态与告警 handled 均不变（终态对账由 cli-resolve-final-state-digest 复核 adj-token-fz 仍 implementing、告警未 handled）。出处 alert_routes.py:190-199。 | pass | 0/5 | - |
| api-resolve-notfound-and-missing-params | 入参校验负路径回归：未知 alert_id → 404 alert not found；缺 choice_id → 400 alert_id and choice_id are required（校验先于 handled/动作执行，零副作用）。出处 alert_routes.py:168-183。 | pass | 0/4 | - |
| api-resolve-continue-auto-fix | verify_fail_escalation 告警选 continue_auto_fix（验证循环耗尽族「继续自动修复」语义）：解冻+清验证失败轮计数（重新获得自动修复预算）+ BLOCKED→READY 回实现通道+handled+留痕。种子 adj-verify-esc 带 _verify_fail_rounds=4，终态清零由 cli-resolve-final-state-digest 复核。出处 admin_actions.py:1555-1588。 | pass | 0/7 | - |
| api-resolve-revise-reproposal | spec-review-rejected 告警选 revise_reproposal（评审否决族「已修订方案·重新评审」语义）：校验冻结 error 含 spec-review-rejected 特征 → 清否决计数解冻回 reviewing（_exec_review_unfreeze，admin_actions.py:1499-1530）+handled+留痕。跳过评审门对本类冻结的拒绝由 cli-verb-skip-review-gate-reject-rejected-freeze 覆盖。 | pass | 0/6 | - |
| api-resolve-skip-review-gate | spec-review-incomplete 告警选 skip_review_gate（评审器连坏时人工授权放行，经端点→execute_adjudication_choice 共享执行器路径）：reviewing 直推 ready 进入正常实现调度+留痕「人工授权跳过评审」+handled。出处 alert_routes.py:202-219 与 admin_actions.py:1435-1494。 | failed（已修正） | 7/8 | product-bug |
| api-resolve-freeze-stop-loss | token_budget 告警选 freeze_stop_loss（token 预算族「冻结止损」语义）：经共享执行器 freeze_spec 冻结 adj-token-fz2（blocked+结构化 frozen 标记+error 冻结前缀，admin_actions.py:309-352）+handled；终态由 cli-resolve-final-state-digest 复核。 | pass | 0/5 | - |
| api-resolve-raise-budget | token_budget 告警选 raise_budget（「调大预算」语义）：agents.token_budget_millions 翻倍（种子基线 12 → 24 写入 .fenix/config.yaml）并复位告警幂等标记+handled；配置终态由 cli-resolve-final-state-digest 复核 token_budget_millions=24。出处 admin_actions.py:1591-1620。 | pass | 0/7 | - |
| api-resolve-signal-declare-no-artifacts | SIGNAL 通道裁决（specs/adjudication-choices-registry 消费通道约定 + specs/alert-resolve kind 差异约定）：kind=signal 的 build_artifact_paths_missing 告警 adj-alert-sig1 选 declare_no_artifacts → 原子写 worktree.has_build_artifacts=false 结案；handled 标记走 mark_signal_handled（SIGNAL 直接更新，alert_routes.py:221-227）——证明 SIGNAL 记录不经前端告警区也能经 alert-resolve 完成裁决闭环。配置终态由 cli-resolve-final-state-digest 复核。 | pass | 0/6 | - |
| api-resolve-signal-open-config | SIGNAL 通道 open_config 选择（配置裁决类「去配置表单裁决」语义）：本动作仅确认信号并提示到配置表单填写 worktree.has_build_artifacts / build_artifact_paths，不改 spec 状态、不代填配置；确认后告警 handled 收口。出处 adjudication_choices.py:196-211 与 admin_actions.py:1747-1752。 | pass | 0/6 | - |
| web-detail-select-note-desc-render | 详情页告警选择题渲染与选中回显（specs/adjudication-ui「真裁决告警渲染下拉并可执行」渲染半程）：spec 详情页（路由 #/projects/:name/:spec，core/dashboard/static/config/routes.ts:23；告警区 detail.tsx:1630-1758）对带 choices 的 impl_budget_exhausted 告警渲染下拉框（placeholder 选择裁决项）+note 输入框（placeholder 处置依据（可选））+执行按钮；点开下拉选「接受现状推进」后，选中值回显于选择框、选项 desc（人工豁免剩余缺口…）常驻展示于卡片、note 输入值正确、执行按钮可点击未被遮挡。选中后即止（不点执行），告警保持未处理（终态对账见 cli-resolve-final-state-digest 的 adj-impl-budget/implb handled=False）。 | pass | 0/10 | - |
| web-detail-force-advance-execute-closes-alert | 详情页选择即完整闭环·执行半程（specs/adjudication-ui 执行态）：对 impl_budget_exhausted 冻结告警 adj-alert-exec 选择「接受现状推进」填 note 点执行 → resolveAlert POST /api/alert-resolve 成功 → 提示「裁决已执行，处置留痕已写入」、告警转已处理态从告警区移除（loadSpecAlerts 重拉）。服务层 resolveAlert 出处 services/dashboard.ts:263-271；交互链 detail.tsx:836-867。 | pass | 0/6 | - |
| web-detail-execute-fail-error-recoverable | 执行失败可重试（specs/adjudication-ui「执行失败可重试」）：对未冻结（implementing）spec 的告警 adj-alert-uifail 选「接受现状推进」点执行 → 端点前置校验拒绝（spec 未处于冻结/blocked 态），错误信息与「告警保持未处理，可调整后重试」展示于告警卡片内，下拉与执行按钮恢复可交互（组件仍渲染、未禁用），允许改选其他选项重试（改选撤销的重试由后续两个场景承接）。失败回显链 detail.tsx:854-866。 | pass | 0/8 | - |
| web-detail-bucket0-no-select-clear | 知情类告警无下拉（specs/adjudication-ui「知情类告警无下拉」+ specs/adjudication-choices-registry「知情类告警不携带选项」「存量无字段告警兼容」渲染半程）：不带 choices 字段（存量兼容形态）的 stale_code 告警在详情页（路由 #/projects/:name/:spec，routes.ts:23）只渲染既有清除（X）交互，不出现裁决下拉框与执行按钮。本场景止于渲染态（点击关闭由 web-detail-bucket0-clear-dismisses 承接；引擎断言在全部步骤后单趟执行，渲染断言与点击后断言必须拆场景）。选择器依据 detail.tsx:1693-1756（adjudicable 门控）与 1752-1754（清除链接内 CloseOutlined 图标）。 | pass | 0/6 | - |
| web-banner-force-advance-closes-item | overview 横幅选择题执行闭环（specs/adjudication-ui「真裁决告警渲染下拉并可执行」横幅形态 + tasks 5.4）：概览页（routes.ts:11）AlertBanner（AlertBanner.tsx:202-291，展开列表为缺省态）对带 choices 告警渲染下拉+note+执行；对 impl_budget_exhausted 冻结告警 adj-alert-banner 选「接受现状推进」填 note 点执行 → 成功提示「裁决已执行，处置留痕已写入」、该告警从横幅列表移除。 | pass | 0/6 | - |
| web-detail-abandon-popconfirm-visible | 撤销动作二次确认弹层（specs/adjudication-ui「撤销动作二次确认」前半）：对 adj-alert-uifail 改选「撤销丢弃」（不可逆动作）点执行 → 不直接发起 alert-resolve，而是弹出 Popconfirm 二次确认，desc 显示动作后果「撤销并丢弃该 spec 的工作（软删除归档，留处置痕，不可自动恢复）」与确认/取消按钮。本场景止于弹层展开态；确认后的真实闭环由 web-detail-abandon-confirm-soft-delete 在独立 spec 上完成。Popconfirm 链 detail.tsx:1714-1727。 | pass | 0/8 | - |
| web-detail-bucket0-clear-dismisses | 知情类告警走既有清除交互关闭（specs/adjudication-ui「无 choices 告警保持既有『知道了』类交互」）：对 stale_code 告警点清除（X）→ 既有 markAlertHandled 标记已处理并从告警区移除——证明选择题改造未破坏存量无字段告警的读取与关闭路径（存量兼容回归）。handled 落盘由 cli-resolve-final-state-digest 复核（adj-alert-stale handled=True）。 | pass | 0/5 | - |
| web-banner-skip-review-popconfirm-execute | 横幅跳过评审门二次确认+执行（specs/adjudication-ui「撤销动作二次确认」扩展到 skip_review_gate + 执行闭环）：对 spec-review-incomplete 冻结告警 adj-alert-uiskip 选「人工授权跳过评审门」（越权语义）点执行 → Popconfirm 确认 → reviewing 直推 ready+handled；告警从横幅列表移除。成功留痕与终态由 cli-resolve-final-state-digest（adj-ui-skip ready）复核。 | failed（已修正） | 2/4 | product-bug |
| web-activities-disposition-trail | 处置留痕进 admin 活动区（specs/alert-resolve「处置留痕进 admin 活动记录」）：运维页（routes.ts:37，activities/index.tsx:135 activity-card）聚合展示各项目 kind=disposition 记录；api-resolve-force-advance-closed-loop 产生的留痕（summary 含「人工裁决 force_advance（force_advance）：实测留痕NOTE-DUP9K7」+ 处置动作摘要）以唯一 note 为锚点在该页可见——人工下拉处置的留痕不依赖手写散文模板。 | pass | 0/5 | - |
| web-mobile-banner-adjudication-reset | 移动端横幅裁决（tasks 5.5 screen-xs 自查的交互级回归）：390x844 视口下横幅裁决控件 wrap 布局（flexWrap，AlertBanner.tsx:260-280）仍可完成完整选择题闭环——对 impl_budget_exhausted 冻结告警 adj-alert-mobile 选「人工已修复·重置验证重跑」（manual_fixed_reverify→reset_verification，非确认类直接执行）→ 重置重验+handled；spec 回 ready 终态由 cli-resolve-final-state-digest 复核。断言的选择器与该视口实际渲染结构一致（同一桌面 DOM 的 wrap 排布，无移动端专属组件门控）。 | pass | 0/5 | - |
| web-detail-abandon-confirm-soft-delete | 撤销动作确认后完整执行（specs/adjudication-ui「撤销动作二次确认」后半 + specs/alert-resolve abandon 闭环）：对 adj-alert-uifail2 选「撤销丢弃」→ Popconfirm 点「确认执行」→ 发起 alert-resolve → 软删除归档（STATE.md 条目移除）+告警 handled+留痕；告警从告警区移除。终态（spec 块 absent、handled=true）由 cli-resolve-final-state-digest 复核。 | pass | 0/6 | - |
| cli-resolve-final-state-digest | 全链路终态对账（回归点：操作后状态与操作前对比）：所有 api resolve 与 web 交互场景收尾后，一次性回读 activation-showcase 的 STATE.md（StateMachine.read_one，布尔归一读侧）、admin_alerts.json 与 config.yaml，核对每条裁决的目标终态——推进类（done/ready/reviewing）、冻结止损（blocked+frozen）、abandon 软删除（spec 块移除）、拒绝/渲染-only 路径零状态变更（非法 choice、未冻结 force_advance、评审否决 reset/skip 拒绝、桶 0 X 清除只动 handled）、SIGNAL 通道 declare_no_artifacts 落配置、raise_budget 翻倍 12→24。 | failed（已修正） | 5/35 | product-bug |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

场景集与持久化集一致，无变更。

