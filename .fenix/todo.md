## 2026-09-27

### 浪费
- **自进化分析 run 两连败 143 轮报废后重派补回**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：两条自进化分析 run（evolution 车道，按水位推进判定成败）连败：一条跑满 143 轮后 CLI 以退出码 1 报废，另一条连产物文件都没落盘就结束；随后重派一轮 332 轮才补回，多烧约一轮半分析成本并延迟约 20 分钟。
  - 证据：日志 2026-09-25T19:01:23Z「自进化分析 run evo-1790361035 失败（水位不推进）： claude CLI failed: Exit code: 1 …143 rounds…max 305.4s」与 19:20:15Z「run evo-1790363139 失败：产物 JSON 不可读/非法: out-evo-1790363139.json 不存在」（均为本地 09-26 03:01/03:20）；.fenix/evolution/ 下仅剩 out-evo-1790361035.json.parts 与 out-evo-1790363139.json.parts 两个残片目录；后继 run evo-1790393159（03:39Z 启动，332 轮）成功。
  - 调查评估：暴露于自进化车道的常规分析轮（窗口开头时段）。已核实：残片目录与失败文案吻合，后继 run 成功说明分析可复做，损失为两条失败 run 的已耗轮数与延迟。两条失败面不同——一条 claude CLI 退出码 1（是否与本窗口全部离群 run 首条 stderr 均出现的 unrecognized_model glm-5.3-flash 告警相关，未核实），一条产物 JSON 根本未写——说明失败不止单一模式，产物落盘无保障。与存量工作：spec/changes/ 活跃区无覆盖自进化产物落盘可靠性的条目。结论：低频但每次整轮报废，且其中一条败得毫无产出，值得一个轻量的产物校验兜底。
  - 建议：自进化 run 收尾前校验产物文件存在且 JSON 可解析，缺失时先原地重写产物再判失败；对 CLI 退出码 1 的样本与 unrecognized_model stderr 做一次关联排查。

### 失误
- **两个已收口 spec 的 verification-report 漏提交入库**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：add-codefix-affinity-batching（已 merge 入 main）与 add-help-docs-mechanism-coverage（42 项任务全部完成）两个已实质收尾的 spec，验证报告文件至今未提交入库，违反库内 41 例既有惯例，归档时需补提交，期间验证结论没有版本化留痕。
  - 证据：git status 显示 spec/changes/add-codefix-affinity-batching/verification-report.md 与 spec/changes/add-help-docs-mechanism-coverage/verification-report.md 均为未跟踪；git ls-files 统计库内已有 41 个 spec 的同名文件入库；admin 告警 6dcf374565c7（affinity-batching 验证环境处置记录）的 evidence 已引用该报告路径，说明报告已生成但未随收口提交。
  - 调查评估：暴露于两个 spec 的验证收口环节（同一晚上先后发生，非孤例）。已核实：报告文件在工作区存在、且被 admin 处置流程当作证据引用，但 affinity-batching 的 merge（本地 09-27 00:48，提交 d54c29a6）与 help-docs 的 repair 收口（含提交 b6c5fec7）都没有带上它。根因是收口链的提交步骤未把 verification-report.md 纳入清单——merge/archive 自动化只认任务产物与 spec 定义文件，属流程缺口而非单次手滑。与存量工作：归档流程（fenix-archive）入库时可能补提交，但那是靠后续环节兜底，收口与入库之间存在丢失窗口。结论：先补提交两个文件，再把该文件固化进收口清单。
  - 建议：立即补提交两份 verification-report.md 入库；在验证收口与 merge-back 流程的提交清单中加入 spec/changes/<spec>/verification-report.md，使其不再依赖归档环节兜底。

### 可改进
- **全仓审查一次出 191 条 消化 run 轮数三倍离群**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：一次手动触发的仓库级全量代码审查花费 60.37 美元、1701 轮、API 纯耗时 4.4 小时，产出 191 条台账（code-review 发现条目）；随后消化链跨 5 个 code-fix 批 run、约 4 小时，每 run 290-562 轮（达同组中位数 96.5 的 3-5.8 倍），修复成本达审查本身的数倍。
  - 证据：日志 2026-09-26T09:07Z「code-review 手动审查完成：run_id=code-review-1790408884, inserted=191, updated=0, shards=26」，该 run 记录 total_cost_usd=60.372、duration_api_ms≈4.44 小时；本地 19:20-23:15 密集出现 336 个「fix: 修复 code-review 台账条目（code-fix batch）」提交与 5 次 merge implementer branch fenix/code-review-fix-*。
  - 调查评估：暴露于手动全仓审查的产出消化链（本地 09-26 17:07 审查完成、晚间消化）。已核实：191 条当日全部消化完毕、窗口内 runs 0 失败，链路健康但昂贵；审查侧已用 26 shards 分片（add-code-review-sharded-out 机制生效）。与存量工作：add-codefix-affinity-batching（选批亲和性聚类+波次上限自适应+批收尾回归两段式）恰在本窗口末尾 23:44 落地，正是针对批消化成本设计——本窗口的批次全部跑在其生效前，构成天然基线。结论：不需重复立项，应转为验证新机制有效性。
  - 建议：下个窗口以本基线（约 14 个 code-fix run、批均约 430 轮消化 191 条）对比 affinity-batching 生效后的批均轮数与 run 数，验证收敛；若仍离群，再考虑台账入库时按严重度/文件亲和性预聚类减批。

- **回归两段式回退路径字面占位符执行必挂**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：verify.yaml 的 regression.cmd 一旦朴素写入 {test_targets} 占位符，三类回退场景（链末批恒全量 / 触碰面映射空集 / targeted_regression 配置关）spec 原样执行，字面 {test_targets} 传给 pytest → 「file or directory not found」→ 该批回归必挂；末批挂则整链无法正常收敛核销。任何按样例朴素接占位符的项目都会踩，单次代价 = 整链末批回归失败与重试烧钱。
  - 证据：core/code_fix.py `_resolve_batch_regression_spec` 回退分支原样返回 reg_spec（约 :2130/:2147，无占位符消毒）；`_apply_test_targets`（约 :1294）仅定向路径调用且 targets 空时原样返回；tests/test_code_fix_affinity_batching.py:557-594 断言止步「spec 原样」、未覆盖执行层。fenixd 自身 .fenix/verify.yaml 已于 09-27 以引号保护注释占位符 + ${FENIX_TEST_TARGETS:-tests/} 缺省展开写法规避（定向/回退/空环境变量三场景 argv 演算全过）。
  - 调查评估：暴露于手工给 fenixd 自身 verify.yaml 接入占位符（本地 09-27）。已核实：回退路径无任何占位符消毒，executed cmd 会携带字面 {test_targets}；无占位符的存量 cmd 不受影响（行为不变）。与存量工作：add-codefix-affinity-batching 已 pushed，其 Scenario「链末批恒全量」只约定 spec 原样、未约定执行层消毒，属实现缺口非规格违背。结论：框架级坑值得小 SPEC 修，修前靠 verify.yaml 写法规约规避。
  - 建议：`_resolve_batch_regression_spec` 回退分支对含占位符 cmd 做消毒（把 {test_targets} 替换为全量缺省如 tests/，str/list 两态各自处理），补「占位符在场 + 回退」组合的执行层单测；并在 .fenix/config.template.yaml 的 targeted_regression 注释段补安全写法样例。


## 2026-09-28

### 浪费
- **code-fix 首批消化 316 轮死于单轮 API 超时 快照无人恢复**
  - 影响：消化周期审查 151 条台账的首个 code-fix 批（code-fix-1790453264，代码审查台账修复批）跑 316 轮、95 个 API 往返后，因单轮 API 请求超时整轮报废，约 2 小时的批修复窗口蒸发；该批搁浅约 5 小时，直到下一轮手动审查重新出账、7 个新批才把消化接上。
  - 证据：日志 2026-09-26T20:50:49Z 三连记录：「run code-fix-1790453264: 95 rounds…max 1549.9s」（最长单轮 25.8 分钟）、「context metrics: turns=316」、「ERROR code-fix run 失败…claude CLI failed: Exit code: 1」；归档 .fenix/runs/archive/code-fix-1790453264.jsonl 末条 assistant 为模型 <synthetic>（CLI 合成消息）「Request timed out」；22:58:39Z「Pre-rmtree snapshot saved…commit 6e823fd7…recover via: git stash store 6e823fd7」（删除工作树前留了 stash 快照，仅留痕无恢复动作）；下一轮审查 code-review-1790464976（手动全仓审查 run）09-27T00:40Z 完成 inserted=163 后消化重启。
  - 调查评估：暴露于周期审查 code-review-1790442246（09-26T18:31Z 完成、inserted=151）的消化首批（本地 09-27 02:34 启动）。已核实：run 中段单轮 API 请求超时（合成消息 "Request timed out"）→ CLI Exit 1 → 整轮判失败 → 工作树以 success=False 清理，仅留 stash 快照（git cat-file 确认 commit 6e823fd7 仍存在），无人执行恢复；run 内 stderr 有 2 处 unrecognized_model（CLI 不识别 glm-5.3-flash 模型名的告警）。根因：现有止损与救回机制都接不住该签名——in-place retry（失败后同 worktree 原位重试）救的是 run 级启动瞬态；evo-add-run-stop-loss（run 停滞止损，tasks 全部勾选已落地）判停判据是「连续 N 次以上 120 秒往返或停滞过半」，针对慢死且缺省关闭，单次超长请求超时终局两者都不覆盖；Pre-rmtree 快照机制只留恢复指令不自动恢复。与存量工作互补不重复：run-stop-loss 管「多次停滞的慢死」，本条是「一次超时即死」。结论：成果可从快照低成本恢复却整轮重烧，同类签名复发敞口为每次一批 300 轮级工作。
  - 建议：对终态为 API timeout（synthetic "Request timed out"/Exit 1）且留有 Pre-rmtree snapshot 的失败 run，重派前自动评估快照恢复（git stash apply 该 commit）而非清空重跑；评估把「单轮 ≥25 分钟后超时终局」纳入 run_stall_budget 判停统计并改为缺省开启。

- **knowledge 维护 spec 验证链一晚四连折腾 人工介入才收口**
  - 影响：add-knowledge-atlas-maintenance（知识真相源维护三车道 SPEC）从实现到收口折腾一晚：交付物守卫拦缺件、判卷车道 worktree 让位失败降级旧版验证、裁决证据三轮校验不合规 blocked、达重验上限停摆等人工——验证侧白跑约 7.8 美元（出题 3.30 + 三轮判卷 4.45），并消耗人工多次介入，验证收口延迟半天。
  - 证据：日志链（本地 09-27）：11:30「交付物守卫触发…缺件 core/knowledge_audit.py（missing）、core/knowledge_backfill.py（missing）等 5 件」；12:36 implementer 220 轮 11.05 美元 success 补齐；12:46「Planner judge 失败: Failed to create worktree (gave up: parallel run or manual freeze)，降级到旧版 verifier（第 1 次降级）」（该 run turns=0 cost=0 未烧 token）；12:57/12:59 两轮判卷 2.30+0.63 美元后「裁决重试后证据分类仍不合规…['web-settings-knowledge-section']」「二次校验仍失败—阻断推进为 blocked-env（环境类阻塞终态）」；13:42「连续 3 轮验证全部 blocked-env，已达重验上限 3…暂停自动重验等待人工处置」（第三轮 1.52 美元）；13:26 提交 fe612841、13:51 提交 446f7687 verification-report（验证报告）入库收口。
  - 调查评估：暴露于 add-knowledge-atlas-maintenance 的验证收口环节。已核实根因（fe612841 提交说明自带现场证据）：校验器 triage（证据分类）漏条目检测要求步骤失败型场景在 evidence.failed_assertions 逐条自申报失败清单，原 planner-judge（出题式验证的判卷车道）提示词只教「从 assertion_results 摘未通过断言」，该形态下该表必空 → 首轮漏 triage、重试轮摘出空表 → fail-closed（校验不过即驳回）死循环——属系统性提示词缺口非单次失误，处方已修复；worktree 让位那次为人工接管态的设计内让位（第 1 次降级计数器已生效，锁活跃签名已由 evo-add-worktree-acquire-backoff 退避覆盖，与本条不重复）；交付物缺件由 220 轮实现轮补齐，守卫拦截属机制正常工作。与存量工作：judge 提示词处方已修（fe612841 改 agents/planner-judge.md），但无回归场景固化「assertion_results 空表 + 失败步骤在场」形态。结论：单次损失约 7.8 美元白跑加半天延迟，根因已修，残余敞口是同类步骤失败型场景再触发时仍靠驳回-重试循环撞出。
  - 建议：为「assertion_results 为空但存在失败步骤」形态补一条冻结回归场景，验证 fe612841 处方在该形态下产出合规 evidence；评估在 fail-closed 驳回前把该形态自动映射为 failed_assertions 缺省自申报，替代整轮驳回。

### 失误
- （当日无）

### 可改进
- **affinity-batching 首验证批均降 25% 条均反升 22% 未收敛**
  - 影响：affinity-batching（code-fix 批次的选批亲和性聚类机制）生效后首个全量消化窗口：7 个 code-fix 批消化 163 条台账共 2253 轮，批均 322 轮较基线批均约 430 轮降 25%，但条均 13.8 轮较基线 11.3 轮不降反升 22%，仍为同组中位（96.5 轮）的 3 倍以上——消化成本未实质收敛，复发敞口为每轮审查消化 2000+ 轮级 runner 消耗。
  - 证据：run metrics：code-fix-1790471986（730 轮）、1790473640（408）、1790474787（415）、1790476127（379）、1790477784（182）、1790479244（18）、1790481526（121），合计 2253 轮；对应 09-27 本地 09:42-12:17 的批次「fix: 修复 code-review 台账条目（code-fix batch）」提交与 4 次 merge code-review-fix-*（10:28/10:55/11:20/12:22）；基线见既有条目 2026-09-27#可改进#2：5 批 290-562 轮、批均约 430 消化 191 条。
  - 调查评估：本窗口批次全部跑在 add-codefix-affinity-batching（09-26 23:44 落地）生效之后，构成该机制的首个对照样本。已核实：批均轮数下降（批切分更均匀，出现 18 轮小批），但单位条目成本不降反升，7 批中 5 批（379-730 轮）仍为组中位的 3.9-7.6 倍离群。结论：affinity-batching 的「批间均衡」目标见效、「降条均成本」目标未兑现，既有条目 2026-09-27#可改进#2 建议的下一步（仍离群则上预聚类）触发条件已成立，该既有条目不判闭环。
  - 建议：按 2026-09-27#可改进#2 原建议推进：先抽样 2 个大批（730/415 轮）逐轮归因确认轮数花在哪（读代码 vs 自检重跑），再决定台账 ingest 时按严重度/文件亲和性预聚类（同文件多条合并单批）的方案；预聚类立项后以本窗口条均 13.8 轮为对照基线。

- **unrecognized_model 告警关联排查仍未做 本窗口再添 4 例**
  - 影响：本窗口全部离群 run 与唯一失败 run 的 stderr 首条均为 [claude-code:unrecognized_model] {"model":"glm-5.3-flash"}（CLI 不识别该模型名的告警），新增 4 例；上次自省已建议关联排查但未执行，复发敞口是把 provider 真实故障当噪音漏判、或反向把无害告警当故障误判，误导止损与熔断调参。
  - 证据：中途信号深扫：impl-add-knowledge-atlas-1790478636-a1（implementer 主 run 的并行子代理轮，stall=4、最长往返 186.8 秒）、同 run 的 -r1 轮、code-review-1790464976（1626 轮审查 run）首条 stderr 均为 unrecognized_model；失败 run code-fix-1790453264 归档内 unrecognized_model 出现 2 处、终局为 <synthetic> "Request timed out" Exit 1；同晚 18:06:42Z「Global transient break TRIGGERED…(5 failures within 600s window)—freezing all new run dispatch for 600s」（全局瞬态熔断，冻结所有派发 10 分钟）。
  - 调查评估：已核实：该告警是 CLI 对 glm-5.3-flash 模型名不识别的 stderr 输出，provider bigmodel.cn 实际可用（窗口内 50 run 46 成功），但它出现在每一次异常事件现场（停滞、超时终局、Exit 1、瞬态风暴），与 provider 不稳窗口（本地 02:00-02:06 瞬态风暴、04:50 超时终局）时间共现。上次自省（2026-09-27#浪费#2 建议）已提「对 CLI 退出码 1 的样本与 unrecognized_model stderr 做一次关联排查」，本窗口未做且样本再增 4 例。与存量工作：活跃区 evo-fix-transient-break-unseal-backoff（瞬态熔断解封退避）管熔断解封节奏，不覆盖本排查项。结论：非阻断，但属告警语义不明的排查债，一次只读排查即可定噪或定真。
  - 建议：做一次只读关联排查：抽取近 7 日含/不含 unrecognized_model 的 run 两组，对比失败率与 stall 分布；强相关则在 agent_runner 对该 stderr 升级计数并纳入瞬态判据，弱相关则登记进深扫降噪白名单；同时向 provider 侧确认 glm-5.3-flash 的模型名注册状态。
