## 2026-09-18

### 失误
- **声明路径漂移致守卫缺件走异议闭环**
  - 影响：交付物守卫按失效路径 core/dashboard/data.py 对账缺件将 spec 置 blocked 待裁决（阻塞约 4 分钟即经异议闭环解除），暴露「spec 评审实测的绝对路径在实现期因同批前序重构落地而漂移」的时序脆弱，同类问题还令分支携带过期测试副本。
  - 证据：09-17T06:49:34Z ERROR「交付物守卫缺件异议 'fix-observability-gaps'（core/dashboard/data.py）— blocked 待裁决，run=impl-fix-observability-gaps-1789617176-a1」；commit 814afc6a（09-17 14:53）更正声明 data.py → data/timeline.py，注明前序 refactor-dashboard-data-module（把 data.py 拆为 data/ 包的 refactor spec）已落地、单文件不再存在，实现者提 deliverable-dispute 异议经人工确认成立。
  - 调查评估：已核实 814afc6a：spec 评审（09-15）实测 data.py 单文件 5333 行且 data/ 包尚不存在，但实现期间前序 refactor-dashboard-data-module 落地拆包使声明失效；spec 已有「实现前置确认（必做）」指引，实现者按指引提出异议、人工确认后更正解除——机制闭环良好，实际阻塞仅 4 分钟。同类时序漂移的另一实例：本 spec 的 1789628051 分支在 main 落地 37fc33de（runner.py 行数契约放宽 <4000）前分出、携带过期测试副本（≤3800）与合法增长至 3962 行的 runner.py 冲突，靠恢复与 main 一致的独立 commit 修复（d7bf6227）。根因：同批推进的 refactor 与依赖 spec 间的时序竞态，评审时点实测 ≠ 实现时点事实。与存量关系：spec 自身指引已缓解，无独立 spec 覆盖。结论：轻量执行失误，残余缺口小。
  - 建议：spec 评审登记交付物绝对路径时，对同批在飞的 refactor spec（拆包/拆文件）在声明段显式标注「若前序已落地按符号名定位」豁免，减少再走异议闭环。

### 可改进
- **派发滞留竞态误报升级留未处理记录**
  - 影响：refactor-giant-classes 在 16:33Z 收到一条 dispatch_stalled 升级告警，实为 recovery watch（周期复查异常 spec 是否滞留的机制）与 blocked 状态写入前 4 秒的竞态误报，成为窗口内唯一未处理升级告警，需人工事后核销。
  - 证据：09-17T16:33:58Z「Recovery watch failed for 'refactor-giant-classes' — not recovered, escalating dispatch_stalled」；admin_disposition-admin-refactor-giant-classes-1789664978.json 记录第 4 点定性「16:33 那条 dispatch_stalled 是 recovery watch 复查机制在 blocked 写入前 4 秒的竞态产物，已被 blocked 事实覆盖」；同类误报修复先例 3fad3350（09-17 18:07，core/admin_monitor.py「修复依赖未满足的 ready spec 被假就绪巡检误报 dispatch_stalled」）。
  - 调查评估：已核实：admin 处置记录明确把 16:33 的 dispatch_stalled 定性为竞态产物并被随后写入的 blocked 事实覆盖，处置只处理 blocked_stuck（blocked 滞留告警）本体；已 pushed 的 evo-recovery-watch-transition-guard（恢复观察过渡守卫，09-14 立项）覆盖的是「成功收工与复查竞态」窗口，本次属「blocked 写入竞态」——触发源与 guard 不同。根因：recovery watch 的 stale 判定未与状态写入（blocked）串行化，复查瞬间与写入交错产生误报。与存量关系：无 spec 覆盖此变体。结论：低严重度改进，频度低（窗口内 1 次）但每次升级都留未处理记录、需人工核销。
  - 建议：在 recovery watch stale 升级前增加「复查当前 status 是否已偏离（如已 blocked/implementing/testing）」的前置检查（对齐 evo-recovery-watch-transition-guard 的 transition_defer 顺延范式），消除与状态写入的竞态误报。

- **verify-serving 存量目录人工清理（fix-verify-serving-disk-reclaim 登记）**
  - 背景：`.fenix/verify-serving/` 存量 19 个 serving worktree 合计约 30G，其中 18 个的 spec 仍存活于 `spec/changes/` 或 `spec/archive/`（按 D1 判据 1「归档等同存活」不会被自动回收），仅 1 个（`verify-draft-fixture-1788860224`）无主已被自动清扫。
  - 清理范围 MUST NOT 只限「spec 在 changes/archive 双双消失」的目录（现测仅 1 个，清理后 30G 基本不动）——**存量主体为 18 个 spec 仍在册目录内各 1.6G `node_modules`**，需按 D1 判据人工逐条核对。
  - 清理方式：**逐条核对后删除，勿用通配批量删**（按 fix-verify-cli-cwd-isolation 教训）：对每个 `<spec>-<ts>` 目录，先确认其 `servers.json` 无登记、`/proc` 无活进程指向、无在飞验证 run，再 `git worktree remove --force` + `git worktree prune`。清理前确认 `.fenix/config.yaml` 的 `verify.deps_mode` 已改为 `hardlink`（本次 SPEC 已改默认值，新建 worktree 单份仅 ~24M），防止存量模式下新建 worktree 再次膨胀。

## 2026-09-19

### 人工运维（fix-artifact-paths-hardcoded-default 登记）

- **对其它已注册项目执行产物配置回填（D5 存量回填，task 7.4）**
  - 背景：产物判定语义已反转（无内置默认集合，未配置=未裁决=判定恒假）。当前机器上除 fenixd 自身（已在本 SPEC 7.3 回填：worktree.has_build_artifacts=true + build_artifact_paths=["core/dashboard/static/"]，落盘 `/root/fenixd/.fenix/config.yaml`，仅本机生效、未入库）外的**所有已注册项目**（其它 daemon 项目主树）尚未回填。
  - 操作：对每个已注册项目主树执行
    `python3 <fenixd 仓库>/bin/fenix_detect_artifacts.py --write <项目根>`；
    脚本幂等、不覆盖已显式配置的项目；探测无产物时写 has_build_artifacts=false；
    执行前确认该项目主树无未提交的产物/源码改动（前缀会把 src 一并判为产物）。
  - **发布顺序约束（task 7.5，MUST）**：把本语义反转版本部署到某台机器前，该机上**所有**已注册项目 MUST 先完成上述回填——否则 daemon 一启动，未回填项目即落入「未裁决」窗口，其产物被判为语义内容、`core/dashboard/static` 类路径失去豁免。顺序：本仓库（7.3 已完成）→ 同机其它已注册项目（本条目）。


## 2026-09-19

### 浪费
- **冻结场景集缺 navigate 步致验证首轮报废并需人工裁决**
  - 影响：fix-verify-serving-disk-reclaim 验证第 1 轮因冻结场景集 23 个场景全部缺少 navigate 步骤（web 场景 MUST 以绝对 URL 打开被测页面）而整轮报废，spec 置 blocked 约 26 分钟，经 2 次 admin 人工唤起 + 1 次 blocked_stuck 滞留升级后才重新出题重跑，验证预算豁免回退（used 0/6）后最终通过。
  - 证据：2026-09-18T07:29:13Z 日志 ERROR「冻结场景文件验收失败 'fix-verify-serving-disk-reclaim'」并附验收差异清单「场景文件包含 23 个错误：场景'spec-in-changes-keeps-dir'缺少 navigate 步骤…」（对应 core/pm_engine/verification/pipeline.py:1410 场景验收）；同刻 verify_env_blocked（验证环境阻塞升级信号）自动呼叫 Administrator，07:47:29Z blocked_stuck（blocked 滞留超 15 分钟阈值的升级信号，当时已 18 分钟）再次唤起；07:55:24Z Gate 转移 blocked→testing（recovery 通道）解阻；10:06:59Z 合成验证报告 11/11 通过（场景数 23 变 11，推断为删除冻结集重新出题）。
  - 调查评估：已核实（fenixd.log 37360-37440 行 + pipeline.py:1410 + 验证报告）：该 spec 06:48Z 实现收尾进入 testing 后，冻结场景集生成于「navigate 必含」验收契约升级之前，契约升级后冻结集未同步迁移 → 跨轮一致性验收 23 处失败 → 按「冻结场景一经冻结跨轮一致、变更须 admin 裁决」置 blocked 待人工。根因：场景验收契约形态升级没有存量冻结集的迁移/过时标记通道，只能人工批准重新出题。与存量关系：已归档的 evo-add-frozen-scenario-schema-migration（冻结场景读侧旧 schema value→command 字段迁移）只覆盖字段形态迁移、不覆盖 navigate 必含这类验收规则演化，二者互补不重复；本事件属一次性验证轮报废，同类契约演化的复发敞口仍在。结论：整轮报废 + 约 26 分钟 blocked + 人工裁决的浪费，值得为验收契约演化补冻结集版本化机制。
  - 建议：参照 evo-add-frozen-scenario-schema-migration 的版本化范式，为场景验收契约形态升级补「冻结集 schema/契约版本标记 + 升级时自动迁移（navigate 可从 base_url 机械补齐）或自动标记过时进入重新出题」通道，使此类契约演化不再依赖人工批准重新出题。

### 失误
- **重构拆包致三连交付物异议且同源草案双 run**
  - 影响：90 分钟内 3 个 spec 因交付物守卫缺件异议连续 blocked 待人工裁决（各约 2-3 小时空转），其中同一需求的两份同源草案被先后各派发一个实现 run、命中同一批陈旧声明；admin 两次机械裁决（verdict=typo 修正声明路径）收场，为 [2026-09-18#失误#2] 声明路径漂移的窗口内复发（新增 3 例）。
  - 证据：2026-09-17T19:55:28Z/20:39:10Z/21:24:01Z（本地 09-18 03:55/04:39/05:24）三条 ERROR「交付物守卫缺件异议」run=impl-evo-merge-back-wip-overlap-gate-1789672392-a1、impl-evo-merge-back-wip-overlap-gate-575976-1789674928-a1、impl-fix-redispatch-loop-governance-1789675996-a1（缺件路径均为 core/worktree_manager.py、core/pm_engine/dispatch.py）；.fenix/dispute_audits.jsonl 两条裁决 verdict=typo、actual_path=core/worktree_manager/mergeback.py / core/pm_engine/dispatch/queue.py，理由均为「refactor-giant-classes(6491c960) 拆包后该单文件在主树与实现分支 HEAD 均不存在」，其中 -575976 一条 commit=4118afc9；spec/changes/evo-merge-back-wip-overlap-gate/SUPERSEDED.md 记载与 -575976 为同一需求两份同源草案且「实现前 MUST 先收敛」；fix-relint-redispatch-legacy 提交 814f64f5 事后修正主树声明段（dispatch 拆分后旧路径陈旧）。
  - 调查评估：已核实（dispute_audits.jsonl 两条裁决 + 4118afc9 + SUPERSEDED.md + 814f64f5）：refactor-giant-classes 把 worktree_manager.py 与 dispatch.py 拆为子包后，同批存量 spec 的 Deliverables 声明仍按旧单文件路径登记，交付物守卫逐 spec 触发缺件异议——全部为可机器判定的「陈旧路径笔误」，却各自走满人工裁决通道；同时 evo-merge-back-wip-overlap-gate 与 -575976 两份同源草案均被派发实现（原草案 run 在 dispute_audits 无裁决记录、成果随 SUPERSEDED 收敛去向未核实）。根因：声明路径漂移的机械对齐无自动通道 + 同源草案收敛义务未在派发前强制。与存量关系：已归档的 evo-deliverable-dispute-orphan-preclassify 仅机械处理零引用孤儿声明（19/19 验证通过），漂移形态（历史命中、目标路径存在）明确仍走人工通道，本事件即该残余缺口的实证，互补而非重复。结论：机制性缺口、复发敞口明确，建议立项补齐。
  - 建议：在孤儿预分类旁扩一类「漂移笔误机械对齐」：异议时若声明路径在主树与分支 HEAD 均缺、且全仓可唯一定位拆包后的新落点（如 core/worktree_manager.py→core/worktree_manager/mergeback.py），则机械改写声明留审计、fail-open 回人工；并让派发前检查同源草案收敛标记（存在 SUPERSEDED/同源声明时禁止对新旧两份同时派发）。

- **VerifyPanel 并发改致开关丢失与 stash 冲突**
  - 影响：设置页「收尾代码质量审查」开关（verify.impl_code_review）的表单绑定在 evo-merge-back-wip-artifact-scope 合并时丢失，Dashboard 约 6 小时（本地 09-18 13:02→19:02）不可见/不可编辑；随后 add-impl-code-review-gate 合并再遇 autostash pop 冲突（同一 VerifyPanel.tsx）留下未应用改动；最终 admin 手工补回绑定并顺带修复「添加产物路径」按钮失效。
  - 证据：提交 80070fbb（09-18 19:02 本地）「补回 verify.impl_code_review 开关的表单绑定——该键在 evo-merge-back-wip-artifact-scope 合并时丢失界面绑定，config_admin.py 侧登记/校验/回显仍在」并修复单个 Form 外 Form.List 致「添加产物路径」点击无反应；2026-09-18T10:02:24Z（本地 18:02）日志 ERROR「'add-impl-code-review-gate' stash pop conflict: files=['core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx'] —— stash 保留，可用 git stash show 找回被丢弃改动」；同批三 spec 均改动该文件（evo-merge-back-wip-artifact-scope 的 ea789573 产物路径可编辑界面、fix-verify-serving-disk-reclaim 的 e2505498 VerifyPanel Switch）。
  - 调查评估：已核实（80070fbb 提交原文 + 日志 38918/38919 行 + 相关提交 stat）：同一窗口三个 spec 连续改动 VerifyPanel.tsx，合并链无文件级串行；evo-merge-back-wip-artifact-scope 合并把代码质量审查开关的 UI 绑定挤丢（config_admin 登记仍在、仅表单绑定缺失，属「配置键须有 Dashboard 界面」原则违例），add-impl-code-review-gate 合并时 worktree 未提交改动入 stash 且 pop 冲突（改动保留可恢复、非丢失）。根因：同文件多路并发修改 + 合并后无 UI 契约自检。结论：执行层合并遗漏 + 无自检，代价为约 6 小时 UI 回归窗口 + admin 手工补回，与 stash 冲突同源并案。
  - 建议：为 Dashboard 设置页关键配置键建立合并后回归断言：验证 VerifyPanel 渲染出的表单键集合必须包含 config_admin 登记的全部布尔配置键（如 verify.impl_code_review），纳入常规测试/merge-back 自检；对同批多 spec 修改同一文件的合并增加冲突提示。

- **在飞审核回退 implementing 触发非法转移**
  - 影响：fix-start-after-premature-pickup（主题正是防 run 提前派发）自身实现 run 与在飞 spec-review run 竞态：16:30:16Z 审核收尾把 16:29:24Z 刚进入的 implementing 回退为 ready，83 分钟实现 run（157 轮、10.2M 输入 token、约 $9.38）全程在矛盾状态上运行，合并收尾触发非法转移 ERROR（ready→implemented）。
  - 证据：fenixd.log 状态轨迹：15:59:11Z reviewing→ready；16:08:51Z 启动第二个 spec-review run（spec-review-fix-start-after-premature-pickup-1789747731）；16:29:24Z ready→implementing 派发 implementer（run impl-fix-start-after-premature-pickup-1789748964-a1，agent_type=implementer）；16:30:16Z 该 review 收尾 implementing→ready（status=repaired 回退）；17:52:30Z ERROR「Invalid transition: fix-start-after-premature-pickup ready → implemented」；随后 error 清空、Implement done、verifier queued，框架以非致命方式继续。
  - 调查评估：已核实（fenixd.log 42660-42680 行及其前后状态轨迹）：spec-review run 在 implementer 派发后 52 秒收尾，状态机按 review 结论把 implementing 回退到 ready（回退时未检查是否已有在飞实现 run），实现 run 继续执行到合并；state machine 只认 implementing→implemented，故合并完成时 ready→implemented 被判非法——ERROR 后框架清错并继续（同刻 fix-fasttrack-recovery-resume-lane 正常 ready→implementing，佐证转移表无全局故障）。根因：派发未校验同 spec 在飞 reviewer/并发 run；审核收尾缺「spec 已 implementing 时不得回退」守卫。与 fix-start-after-premature-pickup 自身范围（start_after 派发门控）不重叠，属并发 run 治理残余缺口。结论：单次竞态、非致命但状态矛盾 83 分钟并留 ERROR 噪音。
  - 建议：①派发 implementer 前校验同 spec 无在飞 reviewer/repair run（有则待 review 收尾后重判）；②审核收尾遇 spec 已 implementing 时跳过回退（仅记录 in-flight）；③合并收尾对 ready 态提供显式兜底（携带通过评审证据时允许 ready→implemented 或自动补记 implementing→implemented）。

### 可改进
- **SDK 瞬断风暴致全局派发冻结且告警留未处置**
  - 影响：5 次 SDK 层瞬断（600s 窗口内）触发全局熔断，所有新 run 派发冻结约 10-13 分钟（13:19:26Z→13:32:32Z 恢复），3 个在飞 run 各自原地退避重试（30s/120s backoff），瞬断风暴升级告警（transient_break_storm，瞬断达阈值触发全局熔断的升级信号）成为窗口内唯一未处理升级记录。
  - 证据：2026-09-18T13:19:26Z 日志 ERROR「Global transient break TRIGGERED for fingerprint '{ model <model> query_source sdk }' (5 failures within 600s window) — freezing all new run dispatch for 600s (fix-provider-transient-backoff D4)」；13:18-13:19Z 三条 Transient error（spec=evo-scenario-defect-reroute-stoploss / fix-recovery-path-blockers / add-dashboard-live-session，provider inferaiapi.com）；13:32:32Z「Global transient break expired — dispatch resumed」；数据摘要「升级告警 12 条，未处理 1 条（transient_break_storm）」。
  - 调查评估：已核实（fenixd.log 40640-40655 行 + core/agent_runner/provider_circuit.py:380-400）：指纹由 _normalize_transient_text 把模型名统一替换为 <model> 占位符（设计使不同模型变体的同型瞬断收敛为一指纹），故风暴无法定位到具体模型/provider；熔断机制本身按 fix-provider-transient-backoff D4 设计工作（达阈值→600s 全局冻结→自然过期恢复），在飞 run 未中断（原地重试续跑）。残余缺口：风暴升级告警无自动核销、上下文无窗口内失败 run 清单，人工/自省难以归因，遂留 1 条未处理升级。结论：机制生效、观测面缺失，低严重度改进。
  - 建议：熔断触发时在告警上下文附窗口内失败 attempt 的 run_id/时间/来源 provider 聚合；评估「熔断自然过期即自动核销 storm 告警（留审计）」以消除人工核销负担。

- **dispatch_stalled 陈旧误报复发且修复在飞**
  - 影响：（新增，[2026-09-18#可改进#2] 复发）复发敞口实发一次：evo-merge-back-wip-overlap-gate 收到 dispatch_stalled（派发滞留升级）告警时其「ready 滞留」前提已在 2 小时前被事实推翻（19:13:12Z 已派发、19:55:28Z 已转 blocked），admin 被无谓唤起处置；针对性修复 spec evo-recovery-watch-status-recheck 在飞未落地。
  - 证据：.fenix/admin_disposition-admin-evo-merge-back-wip-overlap-gate-1789679844.json 自述「dispatch_stalled 信号前提（ready 滞留）在唤起前 2 小时即被事实推翻：该 spec 于 19:13:12Z 已派发、19:55:28Z 收工转 blocked，信号是队列老化窗口的陈旧快照」，result=partially-resolved、escalate=true；spec/changes/evo-recovery-watch-status-recheck/ 存在但 tasks.md 17 项任务未勾选、无验证报告，其 proposal 明确覆盖该形态（升级前重读状态、status==blocked 关闭观察不告警）。
  - 调查评估：已核实（处置文件 + spec 目录）：recovery watch（周期复查异常 spec 是否滞留的机制）的 stale 判定未与状态写入串行化，陈旧快照再次触发 dispatch_stalled 误报——与 [2026-09-18#可改进#2]（refactor-giant-classes 16:33 误报）同型，窗口内新增一例；针对性修复 spec evo-recovery-watch-status-recheck 已立项（proposal 覆盖升级前状态/运行痕迹复查）但 17 项任务未勾选、未验证，未落地。结论：未解决，修复在飞，复发证据新增。
  - 建议：推进 evo-recovery-watch-status-recheck 落地，优先落地「升级前重读当前 status/运行痕迹、命中 blocked/implementing/testing 即关闭观察不告警」的前置复查项（对齐 evo-recovery-watch-transition-guard 的 transition_defer 顺延范式）。

- **verify-serving 存量约 30G 人工清理未处置**
  - 影响：（未处置，[2026-09-18#可改进#3] 原样延续）未处置：.fenix/verify-serving/ 存量 44 条目，其中 19 个 spec 仍在册目录各含约 1.6G node_modules（合计约 30G）仍占磁盘；deps_mode=hardlink 已生效（新 worktree 不再膨胀），存量清理仍是最大可回收项。
  - 证据：实测 .fenix/verify-serving/ 44 条目，du 逐目录实测 19 个 <spec>-<ts> 目录（如 add-dashboard-help-center-1788528914、fix-dashboard-read-path-performance-1789587033）各 1.6G；.fenix/config.yaml 第 231 行 verify.deps_mode: hardlink；fix-verify-serving-disk-reclaim 提交 e2505498 在 .fenix/todo.md 登记「存量 18G 人工清理（18 个 spec 仍在册 worktree 各 1.6G node_modules）」。
  - 调查评估：已核实（目录实测 + config.yaml）：清理动作仍为人工运维待办、未执行；spec 侧机制（serving 清扫按 D1 判据「归档等同存活」不自动回收仍在册 spec 目录、deps_mode=hardlink 默认防新增膨胀）均已就位。结论：未解决（未处置），磁盘占用维持约 30G。
  - 建议：按 fix-verify-serving-disk-reclaim 登记的方式逐条核对删除：对每个 <spec>-<ts> 目录确认其 servers.json 无登记、/proc 无活进程指向、无在飞验证 run 后 git worktree remove --force + git worktree prune，释放约 30G；勿通配批量删（按 fix-verify-cli-cwd-isolation 教训）。
