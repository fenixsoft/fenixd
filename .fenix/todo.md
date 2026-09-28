## 2026-09-27

### 失误
- **两个已收口 spec 的 verification-report 漏提交入库**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：add-codefix-affinity-batching（已 merge 入 main）与 add-help-docs-mechanism-coverage（42 项任务全部完成）两个已实质收尾的 spec，验证报告文件至今未提交入库，违反库内 41 例既有惯例，归档时需补提交，期间验证结论没有版本化留痕。
  - 证据：git status 显示 spec/changes/add-codefix-affinity-batching/verification-report.md 与 spec/changes/add-help-docs-mechanism-coverage/verification-report.md 均为未跟踪；git ls-files 统计库内已有 41 个 spec 的同名文件入库；admin 告警 6dcf374565c7（affinity-batching 验证环境处置记录）的 evidence 已引用该报告路径，说明报告已生成但未随收口提交。
  - 调查评估：暴露于两个 spec 的验证收口环节（同一晚上先后发生，非孤例）。已核实：报告文件在工作区存在、且被 admin 处置流程当作证据引用，但 affinity-batching 的 merge（本地 09-27 00:48，提交 d54c29a6）与 help-docs 的 repair 收口（含提交 b6c5fec7）都没有带上它。根因是收口链的提交步骤未把 verification-report.md 纳入清单——merge/archive 自动化只认任务产物与 spec 定义文件，属流程缺口而非单次手滑。与存量工作：归档流程（fenix-archive）入库时可能补提交，但那是靠后续环节兜底，收口与入库之间存在丢失窗口。结论：先补提交两个文件，再把该文件固化进收口清单。
  - 建议：立即补提交两份 verification-report.md 入库；在验证收口与 merge-back 流程的提交清单中加入 spec/changes/<spec>/verification-report.md，使其不再依赖归档环节兜底。

### 可改进
- **回归两段式回退路径字面占位符执行必挂**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：verify.yaml 的 regression.cmd 一旦朴素写入 {test_targets} 占位符，三类回退场景（链末批恒全量 / 触碰面映射空集 / targeted_regression 配置关）spec 原样执行，字面 {test_targets} 传给 pytest → 「file or directory not found」→ 该批回归必挂；末批挂则整链无法正常收敛核销。任何按样例朴素接占位符的项目都会踩，单次代价 = 整链末批回归失败与重试烧钱。
  - 证据：core/code_fix.py `_resolve_batch_regression_spec` 回退分支原样返回 reg_spec（约 :2130/:2147，无占位符消毒）；`_apply_test_targets`（约 :1294）仅定向路径调用且 targets 空时原样返回；tests/test_code_fix_affinity_batching.py:557-594 断言止步「spec 原样」、未覆盖执行层。fenixd 自身 .fenix/verify.yaml 已于 09-27 以引号保护注释占位符 + ${FENIX_TEST_TARGETS:-tests/} 缺省展开写法规避（定向/回退/空环境变量三场景 argv 演算全过）。
  - 调查评估：暴露于手工给 fenixd 自身 verify.yaml 接入占位符（本地 09-27）。已核实：回退路径无任何占位符消毒，executed cmd 会携带字面 {test_targets}；无占位符的存量 cmd 不受影响（行为不变）。与存量工作：add-codefix-affinity-batching 已 pushed，其 Scenario「链末批恒全量」只约定 spec 原样、未约定执行层消毒，属实现缺口非规格违背。结论：框架级坑值得小 SPEC 修，修前靠 verify.yaml 写法规约规避。
  - 建议：`_resolve_batch_regression_spec` 回退分支对含占位符 cmd 做消毒（把 {test_targets} 替换为全量缺省如 tests/，str/list 两态各自处理），补「占位符在场 + 回退」组合的执行层单测；并在 .fenix/config.template.yaml 的 targeted_regression 注释段补安全写法样例。

## 2026-09-28

### 失误
- （当日无）

### 可改进
- **affinity-batching 首验证批均降 25% 条均反升 22% 未收敛**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：affinity-batching（code-fix 批次的选批亲和性聚类机制）生效后首个全量消化窗口：7 个 code-fix 批消化 163 条台账共 2253 轮，批均 322 轮较基线批均约 430 轮降 25%，但条均 13.8 轮较基线 11.3 轮不降反升 22%，仍为同组中位（96.5 轮）的 3 倍以上——消化成本未实质收敛，复发敞口为每轮审查消化 2000+ 轮级 runner 消耗。
  - 证据：run metrics：code-fix-1790471986（730 轮）、1790473640（408）、1790474787（415）、1790476127（379）、1790477784（182）、1790479244（18）、1790481526（121），合计 2253 轮；对应 09-27 本地 09:42-12:17 的批次「fix: 修复 code-review 台账条目（code-fix batch）」提交与 4 次 merge code-review-fix-*（10:28/10:55/11:20/12:22）；基线见既有条目 2026-09-27#可改进#2：5 批 290-562 轮、批均约 430 消化 191 条。
  - 调查评估：本窗口批次全部跑在 add-codefix-affinity-batching（09-26 23:44 落地）生效之后，构成该机制的首个对照样本。已核实：批均轮数下降（批切分更均匀，出现 18 轮小批），但单位条目成本不降反升，7 批中 5 批（379-730 轮）仍为组中位的 3.9-7.6 倍离群。结论：affinity-batching 的「批间均衡」目标见效、「降条均成本」目标未兑现，既有条目 2026-09-27#可改进#2 建议的下一步（仍离群则上预聚类）触发条件已成立，该既有条目不判闭环。
  - 建议：按 2026-09-27#可改进#2 原建议推进：先抽样 2 个大批（730/415 轮）逐轮归因确认轮数花在哪（读代码 vs 自检重跑），再决定台账 ingest 时按严重度/文件亲和性预聚类（同文件多条合并单批）的方案；预聚类立项后以本窗口条均 13.8 轮为对照基线。


## 2026-09-29

### 浪费
- **429 限流打死 218 轮全仓审查 13 分片仅抢救回 4 片 19 条**
  - 影响：一次手动全仓代码审查跑 218 轮、烧 13.89 美元后被账户级 429 限流（provider 拒绝请求）整轮打死，13 个分片只抢救落账 4 片 19 条，全仓快照核销未做——约 14 美元审查开销换回不足两成分片产出，台账与仓库真实状态间留下未对账缺口。
  - 证据：归档 .fenix/runs/archive/code-review-1790574672.jsonl（手动审查 run）末段：terminal_reason 为 api_error、api_error_status 429、result 文本含「Request rejected (429) · 您的账户已达到速率限制」，run_metrics 记 218 轮、13.89 美元；fenixd.log 2026-09-28T06:17:29Z（本地 14:17）「error 收场抢救落账: run=code-review-1790574672 shards=4 inserted=19 ……（部分覆盖，未做全仓快照核销）」；同窗口另有 13 个归档 run 现场文本含「速率限制」（多数为成功 code-fix 批），说明限流在窗口内持续存在。
  - 调查评估：暴露于 09-28 14:17 本地手动触发的第二次全仓审查（当日 02:20 本地周期审查 code-review-1790528604 刚出账 233 条）。已核实：429 韧性机制在场——add-code-review-concurrency-and-429-resilience（审查并发上限与 429 分类 SPEC，09-24 落地）提供仓库审查并发读取器（缺省 4）与 classify_ratelimit_error（429 限流分类），但限流期间 run 仍以 CLI Exit 1 终局，框架对该终局无退避重派或断点续跑，收场抢救只落已完成分片。根因属机制缺口：账户级限流恢复是分钟级，现有 in-place retry（失败后同工作树原位重试，30/60 秒退避，为秒级瞬态设计）尺度不够。与存量工作：该 429 SPEC 管「并发上限与分类」，本条缺口是「限流致死后的续跑」，互补不重复。结论：周期审查出账未消化完时叠加日内二次全仓，复发概率高，单次代价 14 美元级审查开销加核销缺口。
  - 建议：为审查 run 增加 429 终局的分钟级退避重派或分片断点续跑（已完成分片落账后从中断分片继续而非整轮重来）；审查触发入口对「上一轮出账未消化完」的日内二次全仓做降频或确认。

- **DNS 故障打死 366 轮批修复 网络类终局不在超时保全签名内**
  - 影响：09-28 凌晨一次 DNS 不可达把跑了 366 轮、6.19 美元的 code-fix 批（台账修复批）整轮打死，工作区无 WIP 保全、无快照留痕，批成果全部蒸发，靠当晚后续批重跑补回。
  - 证据：归档 .fenix/runs/archive/code-fix-1790540479.jsonl 末段：result 为「API Error: Can't reach the API server — check your internet or DNS (ENOTFOUND)」、terminal_reason 为 api_error、run_metrics 记 366 轮、6.19 美元（16 个子代理 6 个失败）；fenixd.log 2026-09-27T20:33:56Z ERROR「code-fix run 失败（run code-fix-1790540479）: claude CLI failed: Exit code: 1」；该 run_id 在日志中无任何 Pre-rmtree 快照或 salvage 痕迹。
  - 调查评估：暴露于周期审查 233 条台账的消化链（本地 09-28 04:24 启动的批）。已核实：evo-code-fix-api-timeout-salvage（API 超时现场保全 SPEC）当日 02:37 本地已 merge（提交 19c5a644），其保全判别 is_api_timeout_signature 只命中「terminal_reason 为 api_error 且 result 含 Request timed out」的超时形态；本 run 的 result 是 DNS 不可达（ENOTFOUND），签名不命中，salvage commit（失败现场以提交方式落批分支保全）路径未触发。根因是签名枚举过窄：网络层故障与 API 超时同属「非代码原因的整轮报废」，却不在保全名单。与存量工作：api-timeout-salvage 管超时形态，本条暴露其邻近盲区，属签名扩展关系非重复。结论：批跑得越长暴露越大（本例 366 轮全损），同类网络抖动复发一次即损失一批 300 轮级工作。
  - 建议：把 salvage 保全签名从「Request timed out」扩展到网络类终局（result 含 ENOTFOUND、ECONNRESET、Can't reach the API server 等形态），复用既有 salvage commit 落批分支加下一批认领接续链路，补对应判别单测。

- **知识审计疑点不沉淀 同批疑点两天重复复核 待人工四条无人消费**
  - 影响：知识审计车道（每日扫描知识真相源疑似矛盾并派 run 复核纠偏）连续两天体检结果逐字相同（修 0、转写 1、待人工 4、过 12），第二天 10 个复核 run 里 9 个是对首日已判「无矛盾」或已纠偏疑点的重复复核，4 条标记待人工的疑点两天无人消费仍照常重扫；两天 20 个 run 仅产出两笔纠偏提交。
  - 证据：fenixd.log 2026-09-27T16:35:12Z 与 2026-09-28T16:29:59Z 两条「audit 体检完成：修 0 / 转写 1 / 待人工 4 / 过 12」逐字一致；.fenix/runs/ 下 ka-rewrite1 至 ka-rewrite10 两轮各 10 个 .out（复核 run 输出），两轮疑点相同；第二轮 10 个中 9 个判 AUDIT_VERDICT: no-conflict（无矛盾），其中 rewrite7 第二天复核的疑点自述「09-28 audit 已把根路由表述对齐，初筛系句式相似误报」——首日已纠偏（提交 492dd241，五页根路由表述）仍被再派复核；疑点 8 首日判无矛盾、次日判 contradiction-confirmed（矛盾确认）才产出 9ae0c7a8（两页 3 行纠偏）。
  - 调查评估：暴露于 add-knowledge-atlas-maintenance（知识真相源维护三车道 SPEC）落地的每日 audit 车道。已核实：no-conflict 复核结论不写入疑点台账，次日初筛原样重出同批疑点；「待人工」队列无消费闭环，挂起期间每日照常重派复核；复核结论还会翻转（疑点 8 首日漏报次日抓出），「同一疑点两次疑似即升级人工」的累计机制缺位。损失量化：knowledge 车道复核 run 未记账（日志无对应 run metrics），以每日约 9 个白跑复核 run 计，随疑点堆积线性放大。与存量工作：与 2026-09-27#浪费#1（自进化产物不落盘）同属「车道产出不沉淀」族，对象是疑点清单而非产物文件，不重复。结论：机制缺口，值得小 SPEC 做疑点台账化。
  - 建议：为 audit 车道增加疑点台账（疑点指纹、判定历史、状态流转）：无矛盾判定按内容指纹豁免次日重扫（内容未变不复发）；待人工疑点停止自动复核改为挂起等消费；同一疑点第二轮再被判疑似时升级人工仲裁而非继续自动复核。

### 失误
- **两份收口验证报告与 verify.yaml 改动滞留两天未入库（恶化）**
  - 影响：add-codefix-affinity-batching（code-fix 批次亲和性聚类 SPEC）与 add-help-docs-mechanism-coverage（帮助文档机制覆盖 SPEC）两个已收口 spec 的验证报告，自上次自省点名后滞留工作区至今仍未补提交（已超两天），验证结论持续无版本化留痕；.fenix/verify.yaml 的批收尾定向回归接入同样未提交，fenixd 自身每批修复的收尾回归因此仍跑全量约 254 秒，定向化收益持续未兑现。
  - 证据：git status 中 spec/changes/add-codefix-affinity-batching/verification-report.md 与 spec/changes/add-help-docs-mechanism-coverage/verification-report.md 仍为未跟踪状态（与 2026-09-27#失误#1 点名时一致）；.fenix/verify.yaml 有 13 行未提交改动（regression.cmd 改为引号保护加 FENIX_TEST_TARGETS 环境变量缺省展开写法，注释自署「add-codefix-affinity-batching，2026-09-27 接入」），git log 显示该文件上次提交停在 09-26 18:28（提交 319e2b33）。
  - 调查评估：上次自省（2026-09-27#失误#1）已建议「立即补提交并把报告固化进收口清单」，至今两条均未发生，属执行层未落实而非新失误，滞留时间拉长故标恶化。已核实：verify.yaml 的定向化对 implementer 与 verifier worktree（从 HEAD 建树）生效的前提是该文件已入库，未提交即 fenixd 自身 12 个修复批的收尾回归全部走旧全量命令（实测 5297 用例约 254 秒每批），且克隆与全新环境缺这份配置。与存量工作：报告入库机制 evo-add-verification-report-commit-on-write（验证报告写盘即入库 SPEC，已落地）只挂验证放行出口，接不住「已收口不再验证」的存量报告，两份漏件无法靠它自愈。结论：靠人记必再犯，需一次性清欠并把两类文件纳入收口清单硬门。
  - 建议：立即补提交两份 verification-report.md 与 .fenix/verify.yaml；在 merge-back 或归档前的清单校验中加入「工作区无未入库的验证报告与 verify.yaml 改动」，违例阻断收口。

### 可改进
- **消化条均轮数三连升至 15.0 预聚类决策条件已成立（恶化）**
  - 影响：affinity-batching（code-fix 批次选批亲和性聚类机制）生效后第二个全量消化窗口：12 个成功批消化约 252 条台账共 3786 轮，条均约 15.0 轮、约 0.33 美元，较基线 11.3 轮累计上升 33%；535、487、480、429 轮的四个大批单批 8.5 至 13.6 美元——消化成本恶化趋势未扭转，复发敞口为每轮审查消化 4000 轮级 runner 消耗。
  - 证据：本窗口 13 个 code-fix run 轮数：307、299、535、278、487、429、366（失败）、480、32、230、388、49、272；消化来源为周期审查 code-review-1790528604 出账 233 条（fenixd.log 2026-09-27T18:20:42Z「inserted=233, shards=13」）加 429 死亡审查抢救的 19 条，共约 252 条；基线对比：2026-09-27 条目批均约 430 轮、条均 11.3，上一窗口批均 322、条均 13.8。
  - 调查评估：本条为 2026-09-28#可改进#1 的重述（恶化）：本窗口批均 3786 除以 12 批约 316 轮，与上窗口 322 持平，条均 15.0 较 13.8 续升 9%——「批间均衡见效、条均成本不降」的判断在第二个窗口继续成立且恶化，原条目预设「仍离群则上预聚类（同文件多条合并单批）」的触发条件进一步坐实。已核实：evo-add-codefix-digest-cost-metrics（消化链成本指标 SPEC）已于 09-28 02:56 merge（提交 9580f37c），链级 rollup（每链 run 数、总轮数、工具调用合计的落盘汇总与结构化日志）从此可用，本窗口批次跑在其生效当天、未产出 rollup 数据。结论：归因的数据机制已就位，预聚类立项的决策输入已齐。
  - 建议：用新落地的 rollup 指标抽样 535 轮与 487 轮两个大批做轮数构成归因（读代码与自检重跑占比），据此决策台账入库时按严重度与文件亲和性预聚类；立项后以条均 15.0 轮为对照基线。

- **场景集变更段绕过报告入库闸门 九份报告改动滞留**
  - 影响：验证引擎向 9 个 spec 的 verification-report.md 直写追加「本轮场景集变更」小节（合计约 65 行），全部滞留工作区未入库——其中恰包括 evo-add-verification-report-commit-on-write（验证报告写盘即入库机制）自己的报告；这些场景集演进记录在任何工作区误操作或重建下可丢。
  - 证据：git diff 显示 9 个已跟踪 verification-report.md 各追加 5 至 7 行「## 本轮场景集变更」小节且未暂存（add-knowledge-atlas、add-knowledge-atlas-maintenance、evo-add-codefix-digest-cost-metrics、evo-add-verification-report-commit-on-write 等）；写入者是 core/verify_scenarios.py:651 的渲染函数（场景集写入时同步渲染报告小节）；而入库闸门 core/verify_report.py 的三个出口（present、resynthesized、synthesized）均挂在验证放行时刻。
  - 调查评估：暴露于本窗口密集验证轮（8 个 evo spec 与 2 个 knowledge spec 的验证收口）之后。已核实：场景集变更是验证准备阶段由 verify_scenarios 直写报告文件的另一条写路径，不经过验证放行出口，因此 commit-on-write 的三出口挂钩接不住；evo-add-verification-report-commit-on-write 的报告自身也带了一段未入库小节（「场景集与持久化集一致，无变更」），是该盲区的直接自证。根因属系统性路径缺口：入库触发点选在「放行时刻」而非「报告文件内容变更时刻」。与存量工作：该机制（verified 10/10 已 push）覆盖验证放行的三路报告生成，本条是其写路径盲区的扩展，不重复。结论：随验证轮次增多滞留面线性扩大，值得小 SPEC 把入库触发下沉到报告文件变更。
  - 建议：在 verify_scenarios 渲染「本轮场景集变更」小节后复用 ensure_verification_report 的 pathspec 精确提交（或把渲染调用挪到放行出口之后），补「场景段直写即入库」与「其他 spec 在途草案不受扰」两条单测。

- **回退路径占位符消毒实现洞仍在 规约三件套已齐等收口（持续）**
  - 影响：回归命令若把 {test_targets} 占位符朴素写进参数位，三类回退场景（链末批恒全量、触碰面映射空集、定向配置关）仍会字面传给 pytest 致该批回归必挂，单次代价为整链末批回归失败与重试；fenixd 自身靠 verify.yaml 写法规约规避至今，洞对其他接入项目敞口未变。
  - 证据：core/code_fix.py 现状：_cmd_has_test_targets（约 :1338）与 _apply_test_targets（约 :1350，targets 空时原样返回）只在定向分支调用，回退分支（约 :2192-2201 的否则路径）无占位符消毒；.fenix/verify.yaml 未提交注释自署「MUST NOT 把 {test_targets} 直接写进参数位：回退路径 spec 原样执行……（实现洞，todo.md 已登记）」；.fenix/config.template.yaml:471-476 已有 targeted_regression 安全写法注释样例（原建议第三项已落地）。
  - 调查评估：本条为 2026-09-27#可改进#2 的重述（部分改善后持续）：原建议三项中「config.template.yaml 补安全样例」已落地，「回退分支消毒加执行层单测」未做——回退路径对含占位符命令仍原样执行，防线依赖用户读到模板注释。已核实执行侧已具备环境变量双轨（core/code_fix.py:1389 _with_test_targets_env 在回归窗口导出 FENIX_TEST_TARGETS，:3525 使用），说明框架内已有等效消毒的挂点，缺的只是对「占位符在参数位且回退」组合的兜底替换与对应单测。与存量工作：add-codefix-affinity-batching 的场景只约定回退 spec 原样、未覆盖消毒，属其验收外缺口。结论：小改动低风险，值得随下个 code-fix 批捎带修掉。
  - 建议：在回退分支对含 {test_targets} 的命令做消毒（str 与 list 两态把占位符替换为全量缺省 tests/ 或剥离该参数），补「占位符在场加回退」组合的执行层单测，并把 verify.yaml 的未提交写法规约一并入库。
