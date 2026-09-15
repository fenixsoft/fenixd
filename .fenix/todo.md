## 2026-09-15

### 失误
- **stash pop 冲突再发 1 文件被丢弃**
  - 自进化：问题部分成立 / 建议部分合理 / ✓ 值得立项 · 处理：拒绝 · 删除：否
  - 影响：evo-item-retention-doc-tracking merge-back 时 1 个未提交文件（SuggestedImprovementsPanel.tsx）改动被丢弃（stash 保留可找回）；同信号 20:26 派发 Administrator 时触发 replace() 报错，自动处置失效；WIP 重叠预检命中 7 文件暴露主树残留并发改动
  - 证据：fenixd.log 9801 行 12:22:13Z（local 20:22）stash_pop_conflict 告警（conflict_files=[.../Settings/comments/SuggestedImprovementsPanel.tsx]、wip_overlap 7 文件、stash_kept=true）；9802 行 20:26「Administrator invocation failed: replace() argument 2 must be str, not dict」；fix-mergeback-stashpop-silent-loss 已于 09-09 归档（7fb43e50）——修复后 5 天仍发生同类冲突
  - 调查评估：已核实（告警记录 + 代码现场：prompt_builder.py:204 _fill_placeholders 中 {evidence} 值为 dict 未经序列化，_str_field 的 json.dumps 兜底直到 66f815db 09-15 04:36 才合入，故 20:26 报错时保护尚不存在）。双层问题：其一 merge-back 前主树有 7 个文件 in-flight 改动与分支重叠，stashpop 冲突机制（自愈+预检，fix-mergeback-stashpop-silent-loss 落地）能告警保留但无法避免丢弃，属该修复的残余缺口；其二 admin 派发链对该故障信号的处理因序列化 bug 挂掉，仅记 ERROR 无升级。两者均已达成事实修复（stash 保留可找回、（str_field 04:36 合入），但本次损失已发生。结论：merge-back 主树 WIP 残留是冲突源，需前置阻塞或自动收纳
  - 建议：merge-back 前对主树未提交改动做 WIP 扫描：与分支改动重叠时先阻塞并告警（或自动 stash + 标记待回收），从源头避免 pop 冲突；并排查故障信号派发失败为何未升级告警（见 improvements 对应条目）


## 2026-09-16

### 浪费
- **失败统计误报 10 连发全为成功**
  - 影响：数据摘要「失败 20」中列出的 10 个失败样本逐一核查全部实际成功（result 终态、结果落盘、cost 有值：1.55-11.82），真实失败集中在 impl 链；失败统计失真使每日回顾/todo.md 条目误导人工判断方向，每次自省均需人工纠偏。
  - 证据：10 个样本转录尾部均为 result 成功：spec-review-* 六条 status=repaired、repair-* 三条 conflict resolved/status=success、planner 一条 plan-ready；python 复现 self_review.py：10/10 样本 _classify_run 返回 succeeded 但 _scan_run_signals 全文件扫描命中信号词——spec-review-evo-run-failure-classification-circuitbreaker 正文讨论「预算耗尽」主题、spec-review-refactor-verification-module 转录含 _check_spec_content_missing 源码引用，即被误判 failed。
  - 调查评估：已核实（逐 run 读转录尾部 + 复现 _classify_run/_scan_run_signals）。根因：self_review.py 对 result 成功的 run 仍做全文件信号词子串扫描兜底，而评审/修复/规划任务正文必然讨论「预算耗尽/spec_content_missing/budget exhausted」等失败主题（本次 SPEC 主题恰是失败分类与预算熔断），信号词与任务主题高度重合，成功 run 必误报。属聚合器判定缺陷而非内容质量。与 evo-run-failure-artifact-first（9dd9fd08 已合入，评审结果以落盘文件为准）思路互补，不重复——该 SPEC 未覆盖自省聚合的失败统计层。结论：值得修，收益为失败统计/日小结恢复可信。
  - 建议：自省聚合以 .fenix-run-result.json 落盘 status（approved/repaired/plan-ready/success）判定成功；信号扫描仅对无结果文件或 error 终态的 run 启用；或对 spec-review/repair/planner 类 run 跳过预算词扫描。

- **add-control-plane 六连失败 6h 才收敛**
  - 影响：该 SPEC 从 09-14 20:53 首派到 09-15 02:55 成功约 6 小时、6+ 次派发：a1 停滞超时 9007s（约 2.5h 空转）+ a2/a1-r1/a1-r3 三连 Exit 143，最终 1789437665-a1 成功（cost 2.70），期间失败 run 消耗大量 token 与墙钟。
  - 证据：run 文件：impl-add-control-plane-silent-failure-guards-1789419210-a1 error=Timeout after 9007s judged stagnant（09-14 20:53 开始 23:24 失败）；-a2 Exit 143；1789431431-a1/-a1-r1/-a1-r3 三连 143（00:17-01:21）；1789437665-a1 成功（02:55）；fenixd.log 11271 行标 [provider-transient]。
  - 调查评估：已核实（run 文件 + fenixd.log）。根因：agent 在「等待监控空转态」225 次心跳零实质推进，停滞判定 9007s 才触发（窗口过宽）；随后 claude CLI 多次被 SIGTERM（Exit 143）且仅归 provider-transient 无限 in-place 重试，直至 frozen 终止、人工 resume 才成功。属执行层中断 + 判定参数偏宽的复合，非内容质量。事件发生在 evo-run-failure-classification-circuitbreaker 合入（17:47）之前，熔断生效后该模式已被覆盖，但停滞 9007s 窗口与 143 无根因记录仍存。
  - 建议：停滞判定窗口从 9007s 缩短并计入心跳推进；排查 Exit 143 SIGTERM 来源；143 类 provider-transient 连续失败应触发熔断冷却而非无限重试。

- **dashboard impl 单 run 42 美元**
  - 影响：impl-refactor-dashboard-data-module-1789476918-a2 单 run 成本 42.22 美元（窗口内成本峰值），a1-r1 因 Max turns (900) reached 失败（exit -9）；该 SPEC 窗口内共 7 个 impl run，收尾阶段 a2-r1/r2/r3 三次「核查收工」重复派发。
  - 证据：impl-refactor-dashboard-data-module-1789476918-a2 转录尾部 total_cost_usd=42.2213；-a1-r1 error=Max turns (900) reached — turn extension budget exhausted (2/2)；窗口内 7 个 impl-refactor-dashboard-data-module-*.jsonl（a1/a2/a3 + a1-r1 + a2-r1/r2/r3）。
  - 调查评估：已核实（run 文件）。根因：dashboard data 模块体量大、实现轮反复「核查收工」派发（a2-r1/r2/r3 三次才收敛），单 run 冲到 900 轮 turn 上限耗尽；42 美元单 run 是窗口内最高成本。与 supervision 兜底 18600s（见 M2）相关——监督上限高于 4h 使长 run 无截停。属大重构任务拆分不足 + 收尾核查幂等缺失。
  - 建议：大体量重构 SPEC 拆更小交付单元；impl run turn 上限 900 评估下调；收尾核查 run 幂等去重（已确认交付则不重派）。

### 失误
- **stash pop 冲突再发 1 文件丢弃**
  - 影响：00:09:44Z（本地 08:09）evo-admin-signal-consolidation merge-back 时 core/admin_store.py 1 个未提交改动被丢弃（stash 保留可找回），wip_overlap 预检命中 3 文件；同日 09:56 aa4a3f6f 修复的 AdminStore 序列化缺陷恰在被丢弃文件中，说明丢弃的可能包含必要改动。
  - 证据：admin_alerts.json 8742ae7357f9（00:09:44Z stash_pop_conflict，conflict_files=[core/admin_store.py]，stash_kept=true，wip_overlap 3 文件）+ aa406224349b（00:10:55Z Administrator 唤起失败: replace() 2 must be str, not dict）；昨日 todo 失误#2 同型事件。
  - 调查评估：已核实（告警记录 + 代码现场）。根因：merge-back 前主树仍有 3 个文件 in-flight 改动与分支重叠，stash pop 冲突自愈丢弃 1 文件；昨日建议「merge-back 前主树 WIP 扫描前置阻塞」未落地（09-15 处置为拒绝），本次复发证明该缺口仍开放。且处置链又被 replace() 序列化 bug 卡死（修复 431f714c 17:43 合入前最后一例）。结论：昨日失误#2 未闭环，需重提前置阻塞立项；被丢弃改动需 git stash 找回核对。
  - 建议：落地 merge-back 前主树 WIP 重叠前置阻塞/自动 stash 收纳；对本次 core/admin_store.py 被丢弃改动执行 git stash show 核对落回。

- **supervision 上限低于生效超时**
  - 影响：implementer 生效超时 15000s + 续期 2×1800s = 18600s（5h10m）> supervision absolute_max 14400s（4h），按 18600s 兜底生效——supervision 无法在 4h 截停，与 900 轮 turn 耗尽、9007s 停滞空转（见 W2/W3）直接相关，窗口内 2 条 ERROR。
  - 证据：fenixd.log 2026-09-15T15:49:54.498628Z 与 16:19:54.518657Z 两条同文案：supervision absolute_max_seconds(14400s) 低于 生效超时 15000s + 续期总额 2×1800s = 18600s，按 18600s 兜底生效（agent_type=implementer）。
  - 调查评估：已核实（ERROR 样本）。根因：implementer 生效超时配置（15000s）与 supervision absolute_max（14400s）配置不一致，兜底取 18600s 使监督上限形同虚设。属框架配置漂移/未对齐，非代码 bug 但长期放大长 run 失控风险。结论：配置对齐类失误，易修高收益。
  - 建议：统一配置派生：supervision absolute_max_seconds ≥ 生效超时+续期总额，或生效超时下调至 supervision 上限内；增加启动时一致性校验，不一致即告警而非静默兜底。

- **orphaned_state 三连发处置 Exit 1**
  - 影响：新防线四 orphaned_state 探测（c07475ff 合入）对 evo-run-failure-classification-circuitbreaker 在 4 分钟内连发 3 条 major 告警（09:45:52Z×2 + 09:49:23Z），派发的 Administrator 处置 run admin-evo-run-failure-classification-circuitbreaker-1789465552 以 Exit code 1 失败，处置中断。
  - 证据：admin_alerts.json 793eba911996/7117157adf3e/1ffa07c51200（09:45-09:49Z orphaned_state，same spec）；run 文件 admin-evo-run-failure-classification-circuitbreaker-1789465552 尾部 error=Exit code: 1 无 cost；repair-evo-run-failure-classification-circuitbreaker-1789464612-a1 09:30 开始 09:46 完成（repair 活跃期间即告警）。
  - 调查评估：已核实（告警 + run 文件 + repair 时间线）。根因：orphaned_state 三条件（无活动 run/无存活子进程/无待派发）在 repair run 活跃推进期间误触发（09:45 判定无驱动，但 repair 09:46 才完成），疑似探测与 repair 交接竞态；且同 spec 4 分钟 3 连发无去重/静默期。admin run Exit 1 失败原因无日志。结论：新探测上线首日即暴露误报 + 重复告警 + 处置失败三问题，需校准。
  - 建议：orphaned_state 判定叠加 run 文件活跃度（转录 mtime 近期增长即非孤儿）；同 spec 短时间重复告警去重；admin 处置 run Exit 1 失败补错误日志定位。

### 可改进
- **自省失败判定以结果文件为准**
  - 影响：每日自省「失败 N」统计失真（本次 20 个失败里 10 个为误报），todo.md 条目与人工判断被系统性地误导；复发敞口：任何以「预算耗尽/内容缺失/熔断」为主题的 SPEC 评审轮都会触发误报。
  - 证据：10/10 失败样本 _classify_run 返回 succeeded、_scan_run_signals 命中主题词；spec-review-evo-run-failure-classification-circuitbreaker 正文必然含「预算耗尽」、spec-review-refactor-verification-module 转录引用 _check_spec_content_missing 源码。
  - 调查评估：已核实（python 复现聚合逻辑）。根因：自省聚合对成功 run 仍做全文件信号词扫描兜底，信号词与评审/修复任务主题高度重合。与 in-flight evo-run-failure-artifact-first（结果文件硬门，已合入）互补——该 SPEC 未覆盖自省统计层。结论：可起草 SPEC 立项，低风险高收益。
  - 建议：自省判定以 .fenix-run-result.json 落盘 status 为准；信号扫描仅用于 error 终态或结果缺失兜底；对 spec-review/repair/planner 类 run 移除预算词扫描。

- **Exit 143 无根因记录反复重试**
  - 影响：窗口内 5+ 个 impl run 以 Exit 143 被终止（add-control-plane 系列三连），日志仅标 [provider-transient]，无 SIGTERM 来源记录，导致 in-place 重试空转数小时才 frozen。
  - 证据：fenixd.log 11271 行 [provider-transient] claude CLI failed: Exit code: 143；run 文件 -a2/-a1-r1/-a1-r3 三连 143；11272 行 frozen 终止重试链。
  - 调查评估：已核实（日志 + run 文件）。根因：agent_runner 捕获 CLI 子进程非零退出即归 provider-transient，未区分 SIGTERM 来源（daemon 重启 drain？外部 kill？资源回收？），无告警无升级，靠重试撞运气。与 evo-run-failure-classification-circuitbreaker 三级分类互补但需接入 SIGTERM 归类。结论：可并入 circuitbreaker 后续迭代，记录信号来源并冷却。
  - 建议：记录 SIGTERM 来源（父进程/信号者）；143 连续出现触发熔断冷却而非无限重试；daemon drain/重启对 in-flight run 打 shutdown 标记避免误归 provider-transient。
