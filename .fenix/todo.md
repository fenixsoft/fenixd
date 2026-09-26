## 2026-09-27

### 浪费
- **fast-track 结果文件缺 verification 段 两轮整 run 作废重跑**
  - 影响：两轮 fast-track（快速车道实现 run）各自跑满 171/266 轮、花费 9.61 与 12.39 美元、58 与 65 分钟后成功收尾，却因交付的结果文件不合规被整轮作废，重派重跑再耗约 2.4 美元与 16 分钟——合计约 22 美元的一轮 run 成果在交接环节被判无效。
  - 证据：日志 2026-09-26T15:35:19Z 与 16:36:23Z（本地 23:35 与 00:36）两条「fast-track 硬校验失败：结果文件非法（verification 段缺失或结构不完整）」；run metrics 显示 impl-add-codefix-affinity-batching-1790433028（266 轮、12.39 美元、3890 秒）与 impl-add-provider-health-check-1790437109（171 轮、9.61 美元、3473 秒）terminal=success（run 自身成功）后仍被拒收，随后重派 impl-add-codefix-affinity-batching-1790436919（16 轮、0.69 美元、4 分钟）与 impl-add-provider-health-check-1790440583（45 轮、1.74 美元、12 分钟）复用 worktree 收尾。
  - 调查评估：事件暴露于 add-codefix-affinity-batching 与 add-provider-health-check 两个 spec 的 fast-track 收尾交接。已核实：两轮 run 终态均为 success，但结果文件的 verification 段（验证结论段）缺失被 fail-closed 硬校验拒收；worktree 保留复用后重跑仅 16/45 轮即通过，说明 git 成果已就位，败在结果文件交接而非实现本身。根因是 implementer 收尾写结果文件时 verification 段结构不合规；同类失败 2026-09-22 已在 add-code-fix-item-level-progress 发生一次，三连复发属系统性缺口而非一次性失误。与存量工作：spec/changes/ 活跃区无针对 fast-track 结果文件写出契约的 spec，硬校验正确拦截、未污染主分支。结论：单次代价约 11 美元级 run 作废加 1 小时级延迟，值得立项消除。
  - 建议：为 fast-track 收尾增加结果文件写后自检（run 结束前框架校验 verification 段结构，缺失当场补写）；并考虑把「校验失败」的处理从整轮作废重派改为同 worktree 补交接的轻量车道——本轮实测重跑仅 16/45 轮即过，说明补交接足够。

- **自进化分析 run 两连败 143 轮报废后重派补回**
  - 影响：两条自进化分析 run（evolution 车道，按水位推进判定成败）连败：一条跑满 143 轮后 CLI 以退出码 1 报废，另一条连产物文件都没落盘就结束；随后重派一轮 332 轮才补回，多烧约一轮半分析成本并延迟约 20 分钟。
  - 证据：日志 2026-09-25T19:01:23Z「自进化分析 run evo-1790361035 失败（水位不推进）： claude CLI failed: Exit code: 1 …143 rounds…max 305.4s」与 19:20:15Z「run evo-1790363139 失败：产物 JSON 不可读/非法: out-evo-1790363139.json 不存在」（均为本地 09-26 03:01/03:20）；.fenix/evolution/ 下仅剩 out-evo-1790361035.json.parts 与 out-evo-1790363139.json.parts 两个残片目录；后继 run evo-1790393159（03:39Z 启动，332 轮）成功。
  - 调查评估：暴露于自进化车道的常规分析轮（窗口开头时段）。已核实：残片目录与失败文案吻合，后继 run 成功说明分析可复做，损失为两条失败 run 的已耗轮数与延迟。两条失败面不同——一条 claude CLI 退出码 1（是否与本窗口全部离群 run 首条 stderr 均出现的 unrecognized_model glm-5.3-flash 告警相关，未核实），一条产物 JSON 根本未写——说明失败不止单一模式，产物落盘无保障。与存量工作：spec/changes/ 活跃区无覆盖自进化产物落盘可靠性的条目。结论：低频但每次整轮报废，且其中一条败得毫无产出，值得一个轻量的产物校验兜底。
  - 建议：自进化 run 收尾前校验产物文件存在且 JSON 可解析，缺失时先原地重写产物再判失败；对 CLI 退出码 1 的样本与 unrecognized_model stderr 做一次关联排查。

### 失误
- **两个已收口 spec 的 verification-report 漏提交入库**
  - 影响：add-codefix-affinity-batching（已 merge 入 main）与 add-help-docs-mechanism-coverage（42 项任务全部完成）两个已实质收尾的 spec，验证报告文件至今未提交入库，违反库内 41 例既有惯例，归档时需补提交，期间验证结论没有版本化留痕。
  - 证据：git status 显示 spec/changes/add-codefix-affinity-batching/verification-report.md 与 spec/changes/add-help-docs-mechanism-coverage/verification-report.md 均为未跟踪；git ls-files 统计库内已有 41 个 spec 的同名文件入库；admin 告警 6dcf374565c7（affinity-batching 验证环境处置记录）的 evidence 已引用该报告路径，说明报告已生成但未随收口提交。
  - 调查评估：暴露于两个 spec 的验证收口环节（同一晚上先后发生，非孤例）。已核实：报告文件在工作区存在、且被 admin 处置流程当作证据引用，但 affinity-batching 的 merge（本地 09-27 00:48，提交 d54c29a6）与 help-docs 的 repair 收口（含提交 b6c5fec7）都没有带上它。根因是收口链的提交步骤未把 verification-report.md 纳入清单——merge/archive 自动化只认任务产物与 spec 定义文件，属流程缺口而非单次手滑。与存量工作：归档流程（fenix-archive）入库时可能补提交，但那是靠后续环节兜底，收口与入库之间存在丢失窗口。结论：先补提交两个文件，再把该文件固化进收口清单。
  - 建议：立即补提交两份 verification-report.md 入库；在验证收口与 merge-back 流程的提交清单中加入 spec/changes/<spec>/verification-report.md，使其不再依赖归档环节兜底。

### 可改进
- **新验证流程 worktree 冲突三连败即降级旧版验证**
  - 影响：新验证流程（scenario 出题式验证）的 planner-plan（出题规划）车道已三次因 worktree 创建失败直接放弃并降级旧版 verifier（旧版验证器），单次代价为该轮出题报废加约 16 分钟延迟、验证强度降级；复发敞口是每次与并行派发撞车都重复此代价。
  - 证据：三次同签名日志「Planner plan 失败: Failed to create worktree (gave up: parallel run or manual freeze)，降级到旧版 verifier」：2026-09-21T18:46Z（add-timeline-gate-failure-display）、09-22T15:18Z（add-verify-lane-throughput）、09-26T04:13Z（evo-signal-preprobe-handled-writeback）；09-26 当次失败 run 的 metrics 为 turns=0、cost=0（未烧 token 即夭折），16 分钟后重试轮 41 轮、2.43 美元成功。
  - 调查评估：暴露于 evo-signal-preprobe-handled-writeback（信号预探针写回，自进化产物 spec）的验证出题环节（本地 09-26 12:13）。已核实：失败轮无 token 损失，降级后该 spec 最终 pushed（推送收口），损失是验证强度与一次出题延迟。根因是 planner-plan 车道在检测到并行 run 或手动冻结时，对 worktree 创建失败无退避重试、直接走降级分支。与存量工作：活跃区 evo-fix-worktree-name-collision-retry（worktree 重名换名重试）只覆盖「branch already exists」命名冲突签名，不覆盖本「并行/冻结让路」签名，两者互补不重复。结论：三连复发同签名、单次代价低但每次都静默牺牲新验证流程，值得立项加退避或排队。
  - 建议：planner-plan 车道 worktree 创建失败（并行/冻结签名）时先短退避重试或等待并行 run 排空后再试，重试耗尽才降级旧版 verifier；降级时落含计数的 WARNING，便于后续统计降级频率。

- **全仓审查一次出 191 条 消化 run 轮数三倍离群**
  - 影响：一次手动触发的仓库级全量代码审查花费 60.37 美元、1701 轮、API 纯耗时 4.4 小时，产出 191 条台账（code-review 发现条目）；随后消化链跨 5 个 code-fix 批 run、约 4 小时，每 run 290-562 轮（达同组中位数 96.5 的 3-5.8 倍），修复成本达审查本身的数倍。
  - 证据：日志 2026-09-26T09:07Z「code-review 手动审查完成：run_id=code-review-1790408884, inserted=191, updated=0, shards=26」，该 run 记录 total_cost_usd=60.372、duration_api_ms≈4.44 小时；本地 19:20-23:15 密集出现 336 个「fix: 修复 code-review 台账条目（code-fix batch）」提交与 5 次 merge implementer branch fenix/code-review-fix-*。
  - 调查评估：暴露于手动全仓审查的产出消化链（本地 09-26 17:07 审查完成、晚间消化）。已核实：191 条当日全部消化完毕、窗口内 runs 0 失败，链路健康但昂贵；审查侧已用 26 shards 分片（add-code-review-sharded-out 机制生效）。与存量工作：add-codefix-affinity-batching（选批亲和性聚类+波次上限自适应+批收尾回归两段式）恰在本窗口末尾 23:44 落地，正是针对批消化成本设计——本窗口的批次全部跑在其生效前，构成天然基线。结论：不需重复立项，应转为验证新机制有效性。
  - 建议：下个窗口以本基线（约 14 个 code-fix run、批均约 430 轮消化 191 条）对比 affinity-batching 生效后的批均轮数与 run 数，验证收敛；若仍离群，再考虑台账入库时按严重度/文件亲和性预聚类减批。
