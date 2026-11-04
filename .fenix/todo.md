## 2026-11-02

### 知识真相源
- audit 疑点升级待人工（聚合）：10 条待人工仲裁（最长龄期 36 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

## 2026-11-03

### 浪费
- **API 停滞 11 run 合计 92 分钟纯等待，升级接线窗内未生效**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：窗口内 11 个 run 累计 API 停滞约 5530 秒（≈92 分钟）纯等待，零失败零金额损失，损失面全在墙钟；最重单 run 停滞 1219.5 秒占其 1355.7 秒时长的 90%，最长单轮 513.1 秒。
  - 证据：数据摘要第 6 节 11 行 api-stall（单轮超 60 秒的 API 往返停滞）聚合行相加得 5529.8 秒；抽 4 个 run 回源 run_metrics（run 终态指标行）原始值吻合：impl-move-distill-trigger-to-push-1793590053-a1（move-distill spec 的实现首派）latency_stalls=5/latency_max=412.94、planner-plan-move-distill-trigger-to-push-1793590053-a1（同 spec 的规划 run）stalls=4/max=513.095、spec-review-fix-distill-observation-gaps-797d21-1793594658（fix-distill spec 的评审 run）stalls=9/max=297.91、code-fix-1793561792（code-review 台账修复 run）stalls=0；窗内 admin 信号面 0 条 api_round_stall_escalated（停滞升级信号）。
  - 调查评估：在 move-distill-trigger-to-push 与 fix-distill-observation-gaps 两 spec 的规划/实现/评审车道暴露。已核实事实：停滞计数与最大值抽 4 run 逐项吻合终态指标行（合计未逐行重算——终态行无 total 字段，样本和出自事件侧聚合，故合计按第 6 节聚合行口径转引并如实标注）。根因未定、多假说并存：网关排队/长上下文/本地网络（2026-11-02-evo-add-api-stall-disposition-closeout 的非目标原文留三假说待留痕积累），不据单一假说给修复方向。与存量关系：停滞分级与第 6 节聚合行出自 2026-10-30-evo-api-stall-signal-grading，升级信号+失败零进度受控重试+终态 latency 透传出自 2026-11-02-evo-add-api-stall-disposition-closeout（21:55 归档入库，提交 1b1590634）——窗内全部停滞 run 结束于 13:31 前，早于归档时点，且 03:48/12:17 两条 stale_code 信号（daemon 持旧代码自愈链）在证 daemon 当日中午仍持旧代码，故本窗停滞未被升级面覆盖属时序而非缺口（接线实际装载时刻未核实）。结论：观测与处置面存量已闭环，本条仅留痕当日实损并立一个可证伪预期。
  - 建议：下窗若再现单轮超 300 秒停滞，核对 admin 信号面是否出现 api_round_stall_escalated，验证 21:55 接线经陈旧自愈重启后真实生效；若连续两窗停滞依旧而无升级信号，再按信号面接线缺口立项排查，不预设停滞根因。

- **蒸馏同件三派两空转，落库延迟 165 分钟并留无终态残留**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：同一归档件的知识蒸馏三派才落库，首派到落库跨 165 分钟，两次空派发 rounds=0（LLM 成本≈0），并产生窗内唯一无终态残留账目（runs 统计「无终态残留: 1」即此件）。
  - 证据：runs/archive/knowledge-distiller-2026-11-02-fix-frozen-scenario-dict-salvage-1793587613.jsonl（首派档案）全文仅一行 started（10:46:53，rounds=0，无终态行）；同件 1793597114 号档案记 started 13:25:14 后同秒被 interrupted，reason=startup terminal-state sweep（daemon 启动时对无终态 run 的终态清扫）；成功落库为提交 1998cbf35（13:31:19，[fenix] knowledge: distill，触及 spec/knowledge/ 多个知识页）。
  - 调查评估：在蒸馏车道消费 fix-frozen-scenario-dict-salvage（已归档的冻结场景修复 spec）时暴露。已核实事实：两次失败尝试 rounds=0，第三次 13:31 落库成功，无终态残留与 interrupted 各有一次在档。根因分层：第二次有直接记录——13:25 的 daemon 启动清扫把与启动同秒刚派发的蒸馏 run 判为启动前残留并中断（重启本身由清扫行在证；「13:19 merge fix-distill-observation-gaps 动了 core/ 触发陈旧自愈重启」属推断未核实）；第一次死因未定（无终态无中断行，假说：当时早死路径未落任何终态/中断行）。与存量关系：无终态残留 D4 对账桶（self_review 的 stale 桶）已能识别此类残留，但启动清扫对「重启窗口内同秒新派发」无豁免、蒸馏器早死路径无终态兜底落行。结论：单次损失极小，但属重启竞态复发行，敞口=每次陈旧自愈重启撞上新派发即再现。
  - 建议：startup sweep 对 daemon 停机/启动窗口前后数秒内新派发的 run 豁免或改记 pending 而非 interrupted；蒸馏器无论何种早死路径都补写终态行，消除 stale 桶残留。

### 失误
- **impl 收尾两处形态失配，48 分钟 run 被硬门拒收重派**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：move-distill-trigger-to-push 的实现首派跑满 2895.5 秒（48.3 分钟、323 轮）在终点被产物硬门拒收，重派 a2 花 95 秒、6 轮补账过闸；交付未损（首派 12:12-12:14 的任务组提交全数进入 merge 798d3eebe），净损失约一次重派周期。
  - 证据：a1 jsonl 末行 gate-blocked（终态被产物硬门拒收）reason=task_gate，error=「exit 0 但已完成任务与 TaskUpdate 记录不一致：done_ids 未覆盖已勾选任务 2.3」（台账勾选与完成记录失配）；同分钟 12:15 admin 信号 quality-gates-form-drift 记 .fenix/verify-progress/move-distill-trigger-to-push/quality-gates.json 的 interaction-contract 门写 status='pass' 越枚举（合法值 'passed'），12:17:20 该文件已被 a2 改写为 'passed'（在证）；metrics 行 task_stall.completed_tasks=12 对 remaining_tasks=13。
  - 调查评估：在 move-distill-trigger-to-push 实现收尾时暴露。已核实事实：拒收原因行、枚举漂移信号、a2 补账时长（94.95 秒/6 轮）、补正后文件四点闭环。根因：收尾时 tasks.md 勾选与 TaskUpdate done 记录失配，叠加质量门状态词形漂移（pass/passed 混写）；agent 自述「result gate 自检通过（exit 0）」与框架硬门口径不一致——run 内自检不覆盖这两项对账，失配只能靠框架门在终点拦下。与存量关系：task_gate 硬门与 quality-gates-form-drift 信号两道守卫均按设计工作（拒收/放行提示），无 SPEC 缺口；pass/passed 词形混写在 fast-track 结果面已是再犯惯性点。结论：一次性执行失误、守卫有效，代价是终点拒收重派而非 run 内自纠。
  - 建议：implementer 收尾自检命令补两项对账（tasks.md 勾选 ↔ TaskUpdate done_ids、quality-gates 状态枚举合法值校验），使同类失配在 run 内自纠而非终点拒收重派。

### 可改进
- **纯文本轮通胀再犯触发新维度首报，响应端未定义**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：code-fix 车道（code-review 台账修复）一个成功收尾的 run 105 轮中 53 轮为纯文本轮（无工具调用，占 50.5%），触发离群新维度阈值；该形态 10-17 窗已现一次（204 轮中 61%），复发敞口为每窗可能再烧一轮演化复核注意力（10-17 条目曾白跑一轮复核）。
  - 证据：run_metrics 原始行 turns=105/text_turns=53/duration_s=676.9/latency_stalls=0（code-fix-1793561792）；evo-refine-midflight-outlier-dims（离群维度细化 spec，在 spec/changes/ 未归档）proposal 背景段载 10-17 窗 code-fix turns=204 中 125 轮纯文本（61%）同型记录；该 spec 三组任务已全勾、verification-report.md 在。
  - 调查评估：在 code-fix 台账修复车道暴露，由新落地的纯文本轮离群维度首报命中。已核实事实：本窗命中行与 10-17 窗形态同型，均无 API 停滞伴生（stalls=0），指向模型输出行为漂移假说（该 spec 原文口径），根因未定不预设。token 面不可量化：该车道 run_metrics 的 input_tokens=0，计量缺失。与存量关系：检测端已闭环（维度细化 spec 全勾待归档），提案自述命中后「仅进自省摘要」零自动动作——响应端无定义；该 spec 任务 2.1 已落 run_metrics model 字段，可支撑模型版本对照。结论：观测闭环、响应缺口，值得随归档收尾补一跳。
  - 建议：为 text_turns 维命中定义最小响应：连续 ≥2 窗同车道命中时按 model 字段对照模型版本并做提示词收敛试验，单窗命中仅留痕；可并入 evo-refine-midflight-outlier-dims 归档收尾或独立小 spec。
- **arbiter 手工唤起 Administrator 与 spec 冻结竞态无预检，run 秒死空壳产噪声**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：manual-intervention 唤起 Administrator 处置时，spec 恰处 frozen 态（或唤起与冻结同窗竞态）则 run 派发即被 frozen-terminated（0 轮空壳），留 pending disposition → 孤儿看护兜底升级人工告警（噪声）。已合并的 fix-escalation-chain-watchdog-yield-gaps 只治链头派发路径（_run_admin_phase frozen 预检）与链成员空壳不计配额；手工唤起路径不在链上，未覆盖。
  - 证据：fenixd.log 2026-11-03T11:13:05-06Z 两次 frozen-terminated 空壳（11:13:05.198 链头派发 4385、11:13:06.021 manual-intervention 唤起 4386，均 0 轮即被冻结击杀）；admin_alerts.json id=36ce0eb408ea（孤儿升级告警）/58a6bebc956d（4386 残留 pending）；arbiter 台账 arb-ledger-1793705465700 scene_snapshot「两个 admin run（4385/4386）为 frozen-terminated 空壳」。
  - 调查评估：候选方向——(a) 唤起入口加 frozen 预检（与链头预检同型闸门，frozen 时拒绝派发并明确回执）；(b) 竞态窗内 frozen-terminated 空壳不产 pending disposition（视为未尝试）。改动点在 manual-intervention 唤起入口（fenixd 手工唤起 Administrator 路径）。注意与 arbiter 禁立项治理（add-arbiter-gap-todo-routing）边界互补：本条是唤起通道自身防护，非 arbiter 动作面。
  - 建议：立项小 spec 治手工唤起路径 frozen 预检（方向 a 优先，b 作防御纵深），消 pending 空壳与孤儿告警噪声。

## 2026-11-04

### 浪费
- **API 停滞 58 run 合计 370 分钟纯等待，恶化 4 倍且 success 豁免面按设计工作**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：窗口内 58 个 run 累计 API 停滞（单轮 API 往返超 60 秒的等待段）约 22224.9 秒 ≈ 370 分钟，为上窗 92 分钟的 4 倍；最重单 run（impl-add-escalation-chain-admin-arbiter 首派）停滞 2456.5 秒占其 3.35 小时时长的 20%、费用 41.55 美元为同组中位 21.7 倍，最长单轮 462.7 秒；零失败零交付损失，损失面全在墙钟与轮次。
  - 证据：数据摘要第 6 节 58 行 api-stall 聚合行逐行回源 .fenix/runs/archive/ 对应档案终态 run_metrics（run 档案末尾的指标行）：52/58 为 success 终态、53/58 模型字段为 glm-5.3-flash；latency_max（单轮最长 API 往返）超 300 秒升级线的仅 3 个——planner-judge-add-escalation-chain-admin-arbiter-1793688640-a1（463 秒）、evo-1793636167（420 秒）、planner-plan-add-knowledge-inbox-pipeline-1793697665-a1（331 秒）——且全部 success 终态。
  - 调查评估：在多 SPEC 交付日的六车道（impl/planner/spec-review/admin/code-fix/evo）普遍暴露。已核实事实：58 行合计按聚合行口径相加（终态指标行无 total 字段，与上窗同口径转引并如实标注），抽档案核对终态与 latency_max 吻合；admin 告警面窗口内 api_round_stall_escalated（API 停滞升级信号）零出现。根因未定、多假说并存（网关排队/长上下文/本地网络，2026-11-02-evo-add-api-stall-disposition-closeout 归档件留痕三假说不预设）。与存量关系：core/admin_monitor.py:3392 的 _check_api_round_stall_escalated 检测面（closeout 2.1 交付，判据 latency_max>300 秒与 core/agent_runner/latency.py:43 的 STALL_ROUND_ESCALATE_SECONDS 单源）本窗已在运行（daemon 最后一次 23:48 本地启动装载现行代码），零信号的原因是检测面第 3449 行的 success 终态豁免——「曾停滞但正常完成」的 run 不升级人工面（monitor-escalated-signal-negative-controls 修复的有意设计）。结论：上窗条目「若连续两窗停滞依旧而无升级信号，再按信号面接线缺口立项排查」的可证伪预期被本窗证据修正——接线无缺口，无升级信号是设计使然；真实敞口是停滞对成功收尾的 run 无任何缓解动作，纯烧墙钟，且体量恶化 4 倍。本条按车道微调对账既有蒸馏规则（api-stall 分级与处置面均已入库），只留痕实损与修正预期框架，不重复立项升级信号面。
  - 建议：不再以「升级信号是否出现」作为停滞浪费的验证锚（success 豁免使其对成功 run 天然沉默），改在 cost-observability（成本观测域）为停滞聚合定义常规出口：连续两窗合计超阈值时按 run_metrics 的 model 字段做模型版本对照与提示词/provider 路由收敛试验（53/58 已有 model 字段可支撑），替代逐窗人工对账。

- **stale 自愈 4 次计划内重启全数硬杀在飞 run，6 个 run 约 114 分钟作废**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：当日 stale_code_selfheal（daemon 检测到磁盘代码比进程内存旧、自动计划重启的自愈链）触发 4 次计划内重启（本地 18:11:38、22:33:34、22:45:36、23:08:11），drain（关停前等待在飞 run 收尾的排水窗口）50/50/50/29 秒全数未能等到自然收尾，6 个在飞 run 被 SIGTERM 或启动扫描终结：51.5 分钟 impl（add-knowledge-inbox-pipeline 首派）、14 分钟 impl 与 13.7 分钟 planner-plan 与 96 秒 admin（均为 add-arbiter-gap-todo-routing 同件或同窗）、11.9 分钟 impl（正在跑全量回归后台任务时被杀、Exit 143）、22 分钟 impl（被启动扫描补写 interrupted）——纯 run 时间损失约 114 分钟（impl 99 + planner 13.7 + admin 1.6），另烧全部重派；交付零损失（worktree 分支保全、重派 6 分钟即收尾）。
  - 证据：fenixd.log 四组「Shutting down.../Drain finished after 50s（或 29s）, remaining runs:[…]/Sent SIGTERM to running agent/fenixd stopped」行（10:11:38Z、14:33:34Z、14:45:36Z、15:08:11Z，各接 3 秒级重启）；六个 run 档案尾部终态行逐一度核：impl-add-knowledge-inbox-pipeline-1793697665-a1 与 impl-add-arbiter-gap-todo-routing-1793715648-a1、planner-plan-add-arbiter-gap-todo-routing-1793715648-a1、admin-stale-code-governance-activation-window-1793716373 为 interrupted（reason=daemon shutdown），impl-add-arbiter-gap-todo-routing-1793716475-a1 为 error Exit code:143（141 轮后后台任务 task_updated status=killed），impl-add-arbiter-gap-todo-routing-1793717195-a1 为 interrupted（reason=startup terminal-state sweep）；首次重启前 14:29:02Z 有 stale_code_selfheal WARNING（磁盘 core/** mtime 超 baseline）+300 秒边沿等待行；drain 期间 checkpoint broadcast 3/3 全无响应后硬杀。
  - 调查评估：在 add-knowledge-inbox-pipeline 与 add-arbiter-gap-todo-routing 实现车道暴露，根因是交付密集日的结构性交互：当日 5 个以上 SPEC 交付均动 core/（escalation-chain、judge-repair、watchdog-yield、register-revise、arbiter-gap 等），每次 merge 后 daemon 检测 stale 即计划重启，重启必然撞上下一批在飞 run。已核实事实：重启决策与 drain 窗口值均出自日志原文；排水窗口量级受 agents.run_drain_max_seconds（缺省 60 秒，core/config.py:1930）控制，与 LLM run 单轮时长（本窗 API 往返常态 60-462 秒）结构性失配，窗口内自然收尾近乎不可能；restart checkpoint 广播（reason=planned restart 旗标）为 best-effort 无响应语义，3/3 零响应。次生噪音：同 spec 双 worktree 并存（.claude/worktrees/impl-add-arbiter-gap-todo-routing-1793715648 与 -1793715649）使 find_worktree_by_spec 歧义 4 次 WARNING、preserve 保全降级记 branch='none'，产物靠 drain-preserve checkpoint 提交与 cleanup 保护集兜住。与存量关系：stale-selfheal-cooldown（300 秒边沿防抖）与本窗 add-arbiter-gap-todo-routing 刚交付的 restart_request 机制（core/signals.py 等，JSON reason/origin/date 防重语义，提交 a9557cf02）治理的是「重复重启」，未覆盖「重启打断在飞」。结论：系统性缺口非一次性失误——交付密集日每个动 core/ 的交付都要付一轮打断-重派税，交付零损失全靠 worktree 保全链兜底。
  - 建议：立项小 spec 治排水-在飞失配：①把 run_drain_max_seconds 提到与 LLM 轮长对齐（≥300 秒）并在 drain 期间感知在飞 run 的后台任务（如全量回归）等待任务边界再放行；②重启前对在飞 run 统一落 WIP checkpoint（复用 drain-preserve 机制）后即停，新进程按 checkpoint 续做而非整体重派；③同 spec worktree 唯一性约束（重派复用既有目录而非新播种），消除命名歧义导致的 preserve 降级。

- **code-fix 唯一失败为 unrecognized_model 秒败，31 分钟后自愈**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：code-fix 车道当日唯一失败：05:24 的 run 零轮 API 往返、秒败退出码 1，车道修复窗口延迟约 31 分钟（05:55 下一 run 起恢复成功），损失一次派发与一条 critical daemon_errors 记账。
  - 证据：code-fix-1793654666（code-review 台账修复 run）档案 stderr 行原文 `[claude-code:unrecognized_model] {"model":"glm-5.3-flash","query_source":"sdk"}` + error 行 Exit code:1 + run_metrics 零轮次；同日同模型 glm-5.3-flash 的 60+ 个 run 全部正常收尾（停滞聚合行 53/58 的 model 字段即此模型），05:55 的 code-fix-1793656527 起车道连续成功。
  - 调查评估：在 code-review 台账修复车道暴露。已核实事实：stderr 与退出码逐字核实；失败时刻 05:24（本地）在每日 04:30 网络断供窗口（历史记录 enp42s0 掉 carrier 时段）之后约 54 分钟。根因未定、多假说并存：①CLI 启动时模型名校验抖动（网关/CLI 瞬态）；②网络瞬断被 CLI 伪装成 unrecognized_model 报错——同模型同日高成功率不支持「配置错模型名」的单因叙事，故只写形态层（0 轮 + exit 1 + unrecognized_model stderr）不裁决单因。与存量关系：run-resilience 域已有 CLI 重试退避与 daemon_errors 指纹归一面（同 run 重试合并计数），本例单次即愈、未进入重试面。结论：瞬断型秒败、自愈，按既有「0 轮+exit1 才致命」判别法不值得重启 daemon（实际未重启也自愈）。
  - 建议：0 轮+exit1 秒败按「连续 ≥2 次同指纹」再升级处置，单次留痕即可；不按单一根因假说（如改模型配置）误修，失败档案已留存 stderr 原文可回溯。

### 可改进
- **startup sweep 无在途判据，当日两起错杀 62 分钟与 22 分钟在跑 run**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：startup terminal-state sweep（daemon 启动时对尾部无终态事件的 run 档案补写 interrupted 标记的扫描）当日错杀两个实际在途的 impl run：watchdog-yield-gaps 首派（20:12-21:14 跑 62 分钟，21:14:53 被 sweep 补 interrupted，与 worktree 收尾提交 aab45e481 同分钟，产物靠分支入库救回、账面失真）；add-arbiter-gap-todo-routing 第三派（22:46 派发跑 22 分钟，23:08:48 被打断后重走 merge）。复发敞口=每次 stale 自愈重启撞上在途 run 即再现（当日 2 起，上窗蒸馏车道 1 起），单次代价约一个完整实现 run（当日实测 22-62 分钟）。
  - 证据：两 run 档案尾部 interrupted（reason=startup terminal-state sweep，13:14:53Z 与 15:08:48Z）；sweep 实现 core/agent_runner/liveness.py:361 sweep_runs_without_terminal_state——判据只有「尾部无终态事件」，docstring 明示「孤儿 claude 进程存活不阻塞补写」，无停机/启动窗口豁免；watchdog-yield impl run 的停滞指标（stalls=8、合计 837.1 秒）证明被打断时仍在活跃跑；两 run 被补写后均无 run_metrics 行（无 latency_max 字段）。
  - 调查评估：在 impl 车道两个 SPEC 的收尾/中段暴露。已核实事实：21:14 案产物已提交分支（aab45e481 21:14、merge a45efc362 21:17）零交付损失，23:08 案同（merge 36095b1eb 23:09）；sweep 只补 interrupted 不补指标行。根因：sweep 的「残留」判定把「转写者（旧 daemon）已死但 run 在途/刚收尾未落 result」与「真残留」同判——上窗 #浪费#2 建议的「停机/启动窗口前后数秒豁免」不足以覆盖本窗形态（62/22 分钟长跑在途被杀）。与存量关系：fix-distill-observation-gaps 与 move-distill-trigger-to-push 两 spec 已全勾待归档（治蒸馏器早死终态兜底与触发面迁移），本窗蒸馏链未复发空转（runs 统计无终态残留 0）；但 sweep 判据本身两个 spec 均未触及，属残余缺口（代码级实锤）。结论：同族复发、判据缺口明确，值得在归档收尾时顺带补跳。
  - 建议：sweep 补写前增补在途判据：run 派发记录或 worktree 活跃分支 mtime 新于停机时刻则改记 pending（待定）而非 interrupted，交由运行期清扫器（runtime terminal-state sweep，liveness.py:562）按进程存活二次裁决；可并入 fix-distill-observation-gaps 归档收尾或独立小 spec。

- **纯文本轮通胀连续第二窗命中且跨车道扩散，响应端仍未定义、检测 spec 滞留未归档**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：planner-judge 车道 run（add-escalation-chain-admin-arbiter 的 1793691083）178 轮中 111 轮纯文本（无工具调用的模型回复轮，占 62.4%）、planner-plan 同 spec run 125 轮中 65 轮（52.0%），双双越过离群阈值（轮数>100 且占比>50%）；与上窗 code-fix 命中（50.5%）合计，同一模型 glm-5.3-flash 已在 3 个车道命中，复发敞口为每窗多烧一轮演化复核注意力（上窗实测白跑一轮复核）。
  - 证据：数据摘要第 6 节初筛离群两行的 turns/text_turns 原始值；两 run 档案 run_metrics 的 model 字段均为 glm-5.3-flash；spec/changes/evo-refine-midflight-outlier-dims/（离群维度细化 spec）仍含 proposal/design/tasks/verification-report 全套（tasks.md 6 处勾选全完成）滞留活跃区未归档。
  - 调查评估：在 planner 双车道暴露，为该离群维度首报后的第二窗命中。已核实事实：阈值与占比按摘要原始值转引；检测 spec 全勾待归档、归档动作拖延是响应端未落的一部分。根因未定（模型输出行为漂移假说，该 spec 原文口径），token 面不可量化（该车道 run_metrics 的 input_tokens=0 计量缺失）。与存量关系：检测端已闭环（维度细化 spec 全勾），提案自述命中后「仅进自省摘要」零自动动作——上窗建议「连续 ≥2 窗同车道命中再做收敛试验」，本窗两处命中均为不同车道（planner-judge/planner-plan 首窗），按该规则属留痕；但命中面从 code-fix 单车道扩散为三车道同模型形态，叠加检测 spec 归档拖延，构成恶化。结论：响应端缺口已从「单车道等待观察」升级为「跨车道系统性形态」，归档收尾是当前最小可行动作。
  - 建议：推动滞留的 evo-refine-midflight-outlier-dims 归档收尾，并在此过程中落最小响应定义：同车道连续两窗命中即按 model 字段做模型版本对照与提示词收敛试验（planner 车道当前为首窗命中，下窗再命中即触发）；归档拖延本身列入自进化车道跟进清单。

### 知识真相源
- [ ] knowledge-distill 重试：归档 add-systemd-hosting — run 失败: claude 进程非零退出（exit=1）；stderr 尾部: Claude Code doesn't recognize the model "glm-5.3-flash", so it assumes a context window of 200k tokens. Update Claude Code, or see https://code.claude.com/docs/en/model-config#correct-the-window-for-a-gateway-or-custom-model-id to set the window. [claude-code:unrecognized_model] {"model":"glm-5.3-flash","query_source":"sdk"}；拒识形态 unrecognized_model（生效模型名 glm-5.3-flash，显式传名仍被拒属确定性失败），不重试（spec/knowledge/ 回滚未确认，半成品滞留工作区，请人工核查；pending 台账条目保留，将由 daemon 重启续跑接管）

## 2026-11-05

### 浪费
- **stale自愈重启再杀3个在飞run，planner与两impl约113分钟作废（恶化）**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：窗口内一次 stale_code_selfheal（daemon 检测磁盘代码比进程内存旧后自动计划重启的自愈链）计划重启经 50 秒排水窗口未能等到任何在飞 run 收尾，SIGTERM 硬杀 3 个在飞 run：planner-plan-add-systemd-hosting-1793755316-a1（40.1 分钟/111 轮出题全废）、impl-add-systemd-hosting-1793755316-a1（40.0 分钟）、impl-fix-escalation-chain-ledger-closure-1793755758-a1（32.7 分钟），合计约 113 分钟在飞时间作废并全数重派；交付零损失（分支保全、重派 45 秒至 23 分钟收尾），损失面为在飞工时加重派成本。
  - 证据：日志链：本地 10:00 fix-escalation impl 收尾提交 1b3a9904e 动 core/ → 09:24 已有 stale 检测 WARNING（磁盘 mtime 超 baseline）→ 10:01:13「Shutting down...」→ 10:02:06「Drain finished after 50s, remaining runs:[3个]」同秒三条「Sent SIGTERM to running agent」；planner run 档案尾部依次为 interrupted（reason=daemon shutdown，10:02:06.475）、run_metrics（duration_s=2403.5、turns=111、latency_max=493.3）、error「Exit code: 143」（exit 143 成批同刻出现=排水屠杀签名，见 error-attribution-denoise 能力页判读法）；两个 impl run 档案尾部仅 interrupted、均无 run_metrics 行（转写者随杀而死的指标盲区，与上窗同型）。
  - 调查评估：在 add-systemd-hosting 与 fix-escalation-chain-ledger-closure 两 spec 的 impl/planner 车道暴露。已核实事实：三个 run 的起止 span（09:22/09:29 起跑至 10:02 被杀）与 SIGTERM 行逐一度核，排水窗口 50 秒与上窗实测一致，对单轮 API 往返常态 60-490 秒的 run 结构性不够等。根因：结构性缺口——每个交付日动 core/ 的 merge 都触发 stale 自愈重启，重启必然撞上下一批在飞 run。与存量关系：这是 2026-11-04#浪费#2（上窗 4 次重启杀 6 个 run 约 114 分钟）的同族复发，其建议（排水窗口对齐 LLM 轮长、在飞 WIP checkpoint 续做、worktree 唯一性）至今未立项，spec/changes/ 无对应 spec；本例触发重启的收尾提交恰出自 fix-escalation-chain-ledger-closure spec 自身，交付税自食。结论：第二日连发证实敞口稳定，属系统性缺口非一次性失误。
  - 建议：将上窗建议立项小 spec：agents.run_drain_max_seconds 提到 ≥300 秒；drain 期间对在飞 run 落 WIP checkpoint 后即停、新进程按 checkpoint 续做而非整体重派；重启触发条件增加「在飞 run 数大于 0 时顺延重启」的最小闸门。

- **add-systemd-hosting蒸馏三派两败一误杀未落库，归档链卡死（恶化）**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：add-systemd-hosting（systemd 托管改造 spec）的归档蒸馏（归档链末段的知识蒸馏环节）三次派发全部失败：第一次 11:31 秒败（unrecognized_model 拒识，14.5 分钟仅 1 轮后 exit=1）、第二次 11:51 恢复重派与 daemon 启动清扫同秒互杀（0 轮从未起跑）；蒸馏至今未落库，spec 滞留 spec/changes/ 活跃区，todo「knowledge-distill 重试」条目挂起待人工，净消耗 2 次派发加 1 次恢复重派。
  - 证据：knowledge-distiller-add-systemd-hosting-1793763090 档案 3 行：started 11:31:30、round 11:46:04、error 原文「claude 进程非零退出（exit=1）…unrecognized_model {"model":"glm-5.3-flash"}」；1793764278 档案 created 与 interrupted（reason=startup terminal-state sweep，即 daemon 启动时对尾部无终态 run 补写中断标记的扫描）同为 11:51:18——这正是 daemon-drain-integrity 能力页登记为「未修」的顺序缺口签名（恢复重派先于启动清扫执行，新 run 被毫秒级误补 interrupted）；spec/knowledge/log.md 留 11:46 与 12:03 两条 distill 失败记录；spec/changes/add-systemd-hosting/ 至今在活跃区。
  - 调查评估：在蒸馏车道消费 add-systemd-hosting 归档件时暴露。已核实事实：三次尝试的档案与日志逐一度核；11:51:10 本地「陈旧自愈触发：连续空闲 300s 已 touch restart_request」→11:51:18 新 daemon 启动→recover_pending（蒸馏 pending 台账的启动恢复重派）先派发、start() 头部清扫同秒补写 interrupted，与能力页签名逐字吻合。根因两层：①unrecognized_model 对生效模型名 glm-5.3-flash 拒识属确定性失败，重试无效；②恢复重派与启动清扫的挂载顺序缺口使第三次尝试零消耗即死。与存量关系：2026-11-03#浪费#2（蒸馏三派两空转）同族第三例、2026-11-04#浪费#3（unrecognized_model 秒败）跨车道再现、2026-11-04#知识真相源#1（todo 挂起）即本条——三个既有条目在本窗交汇于同一 spec。结论：单 spec 归档卡死量级小，但归档堵点会连锁滞留活跃区（spec/changes/ 现存 24 个收尾目录），敞口为每次陈旧自愈重启撞上 pending 恢复即再现。
  - 建议：落地顺序缺口修复：启动清扫对恢复重派窗口内新派发的 run 改记 pending 交运行期清扫二次裁决；unrecognized_model 拒识走显式修复（网关注册或换模型名）而非重试，人工核查 spec/knowledge/ 半成品后人工触发一次蒸馏即可解卡本 spec 归档。

- **API停滞回落至20 run合计175.5分钟，升级信号面首次捕获并闭环（好转）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：窗口内 20 个 run 累计 API 停滞（单轮 API 往返超 60 秒的等待段）10529.2 秒约 175.5 分钟，较上窗 370 分钟回落过半，仍为两窗前 92 分钟的近 2 倍；最重单 run planner-plan-add-systemd-hosting-1793757731-a1 停滞 1627.3 秒、最长单轮 387.5 秒；零失败零金额损失，损失面全在墙钟。
  - 证据：数据摘要第 6 节 20 行 api-stall 聚合行相加得 10529.2 秒（终态指标行无 total 字段，按聚合行口径转引并如实标注，与上窗同口径）；抽 planner-plan-add-systemd-hosting-1793755316-a1 终态 run_metrics 原始值核对吻合（latency_rounds=52、latency_stalls=9、latency_max=493.3）；本窗 admin 信号面首次出现 api_round_stall_escalated（API 停滞升级信号）：告警 a14031730875 于本地 10:02:11 落账（latency_max=493s）、10:12:08 处置终态 resolved 并回写 handled=true。
  - 调查评估：在 planner-plan×5、impl×4、spec-review×4、planner-judge×3 等多车道暴露。已核实事实：合计按聚合行口径相加、抽样与终态指标行吻合；升级信号面在本窗真实工作——唯一超 300 秒升级线的 run（493.3 秒）恰为被排水屠杀的非 success 终态，不被 success 豁免面（曾停滞但正常完成的 run 不升级，monitor-escalated-signal-negative-controls 的有意设计）覆盖，信号落账并闭环处置，回答了上窗「接线经陈旧自愈重启后是否真实生效」的遗留问题：生效。根因仍多假说并存（网关排队/长上下文/本地网络，2026-11-02-evo-add-api-stall-disposition-closeout 留痕），不预设。与存量关系：上窗建议「不再以升级信号为验证锚，改在 cost-observability（成本观测域）为停滞聚合定义常规出口（model 字段对照/收敛试验）」未落地——该域无新增能力页，spec/changes/ 无对应 spec。结论：三窗走势 92→370→175.5 分钟属持续摩擦非失控，观测闭环、聚合出口缺口。
  - 建议：按上窗建议落最小出口：连续两窗合计超 150 分钟时按 run_metrics 的 model 字段做模型版本对照与提示词/provider 路由收敛试验（本窗 20 run 的 model 字段已齐备可支撑），替代逐窗人工对账。

### 失误
- **task_gate拒收第二例：done_ids漏勾任务4.2，收尾自检仍缺席（恶化）**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：fix-escalation-chain-ledger-closure 的实现重派 run 在终点被 task_gate（implementer 产物硬门）拒收：done_ids（TaskUpdate 完成记录）未覆盖已勾选任务 4.2，重派 a2 花 45.3 秒、12 事件补账过闸；损失约一次拒收-重派周期（分钟级），交付未损（merge 41940d213 已含全部任务提交）。
  - 证据：impl-fix-escalation-chain-ledger-closure-1793757732-a1 档案末行 gate-blocked（本地 10:06:35）reason=task_gate，error 原文「[task-gate] exit 0 但已完成任务与 TaskUpdate 记录不一致（implementer 产物硬门）: done_ids 未覆盖已勾选任务 4.2」；a2 档案 12 事件、duration 45.3 秒 result 收尾；与上窗同型：2026-11-03#失误#1 记 move-distill-trigger-to-push 首派 2895.5 秒被拒（漏任务 2.3）。
  - 调查评估：在 fix-escalation-chain-ledger-closure 实现收尾时暴露，且本例 a1 是 10:02 重启排水屠杀后的重派 run（09:29 起跑 32.7 分钟被杀→重派→收尾失配被拒），杀-重派-拒收链放大了重启税。已核实事实：拒收行与 a2 补账时长逐一度核。根因与上窗一致：run 内收尾自检不覆盖「tasks.md 勾选集合与 TaskUpdate done_ids 集合」对账，失配只能靠框架硬门终点拦截，agent 自述自检通过与硬门口径脱节。与存量关系：2026-11-03#失误#1 的第二例，其建议（收尾自检补两项对账）未落地即复发；守卫面两例均按设计工作、零漏网。结论：两窗两例构成执行惯性点，属 implementer 提示词自检清单缺口非框架缺口。
  - 建议：在 implementer 提示词收尾自检清单补两项：tasks.md 勾选集合与 TaskUpdate done_ids 集合一致、quality-gates.json 状态值在 passed 枚举内；落地后此类失配应在 run 内自纠而非终点拒收重派。

### 可改进
- **daemon非优雅死亡停摆7.8小时，evo复核与周期审查两run蒸发（新增）**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：daemon 于 11-04 00:53 本地前后非优雅死亡（无 Shutting down 行、无 supervisor 退出记录），fenixd.log 随之零行 7.77 小时，直到 08:39 本地才被拉起；死亡时刻在飞的两个长跑 run——evo-1793723033（演化复核，30 分钟 1014 事件）与 code-review-1793721816（周期代码审查，50 分钟 2624 事件）——在飞工作蒸发，账面悬空 7.8 小时后才由启动清扫补写 interrupted 终态。
  - 证据：fenixd.log 在 2026-11-03T16:54Z 至 2026-11-04T00:38Z（本地 00:54-08:38）区间 0 行（脚本统计）；两 run 最后事件均停在本地 00:52-00:53；supervisor.log 最后记录 11-03 16:13:32Z（supervisor_runtime written pid=1946442）其后无 daemon exited/restarting 行；08:39:37 本地新 daemon（PID 2080813）启动行无 supervisor 拉起对应记录（裸启动），首屏「Startup terminal-state sweep: 补写 2 个遗留 无终态 run」；evo 复核工作由 5 分钟后派发的 evo-1793753078 接续成功（cost 15.96）。
  - 调查评估：在演化复核与周期审查车道暴露。已核实事实：日志空窗 0 行、两 run 事件停止时刻、supervisor 静默、sweep 补写行均逐一核实。根因未定、多假说并存：宿主重启/OOM/手动 kill/托管链断裂（supervisor 16:13Z 后无记录、新 daemon 绕过 supervisor 裸启动均支持托管链当时不在位），死亡在本地夜间无人值守段。归因证据边界：上窗 2026-11-04#可改进#1 判「startup sweep 无在途判据错杀在途 run」，本窗 08:39 两案证据形态不同——两 run 悬空 7.8 小时无任何新事件，sweep 补写时「在途」已不可证，按悬空 run 判读（daemon-rules 能力页口径）直接死因是 daemon 非优雅死亡，sweep 仅兜底补写；对上窗条目作显式更正：本窗两案不构成「错杀在途」新实锤。与存量关系：supervisor-hosting 与 daemon-drain-integrity 能力页覆盖排水一致性与托管语义，但「非优雅死亡后无人拉起」的监督缺口在案发时不在位；本窗 10:30 merge 的 add-systemd-hosting（systemd 托管改造）正是治此，落地后宿主级拉起应消除长时间无人值守停摆。结论：一次宿主级事件暴露托管链断裂窗口，交付未丢失（重派接续），实损约 80 分钟工作量与 7.8 小时框架不可用。
  - 建议：观察 add-systemd-hosting 托管落地后是否再现无人拉起停摆；将本例死亡痕迹（supervisor 静默＋日志空窗＋悬空补写）沉淀为非优雅死亡的判读签名；不做无根因预设的修复。

- **纯文本轮通胀第三窗命中且同车道三run并发，响应端仍未落地（恶化）**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：planner-plan（出题）车道同窗 3 个 run 命中纯文本轮离群维度（turns>100 且纯文本轮占比>50%）：add-systemd-hosting 两派 58/111（52.3%）与 88/169（52.1%）、fix-escalation-chain-ledger-closure 一派 59/108（54.6%），合计 388 轮中 205 轮无工具调用；该形态第三窗持续命中且首次同车道多 run 并发，复发敞口为每窗多烧一轮演化复核注意力（上窗实测曾白跑一轮复核）。
  - 证据：数据摘要第 6 节三行初筛离群 run 原始值；三 run 终态 run_metrics 的 model 字段均为 glm-5.3-flash（其中 1793755316-a1 的 metrics 原文逐字段核对吻合）；检测 spec evo-refine-midflight-outlier-dims 已归档（提交 0c17b596f，11-04 08:44），其 proposal 三项交付均为观测端（text_turns 维度、取数修正、model 字段落行），响应端零定义。
  - 调查评估：在 planner-plan 车道暴露，为该维度第三窗命中且首次同车道聚集。已核实事实：三 run 占比与 model 字段逐一度核，检测 spec 归档件无响应端交付。根因未定（模型输出行为漂移假说，spec 原文口径），token 面不可量化（该车道 input_tokens=0 计量缺失）。与存量关系：上窗建议「同车道连续两窗命中即按 model 字段做模型版本对照与提示词收敛试验」——planner-plan 上窗首窗命中、本窗再命中 3 run，触发条件已达成，但响应端无机制承接（cost-observability 域无聚合出口能力页、无对应 spec）。结论：命中从跨车道扩散转为同车道聚集，收敛试验触发条件已满足，属观测闭环后响应端的最小落地时机。
  - 建议：落最小响应机制：同车道连续两窗命中即按 model 字段出对照报告并做 planner 提示词收敛试验（如压缩逐轮叙述性输出指引），单窗命中仅留痕；可挂靠 cost-observability 域新增能力页。

- **主树untracked散件探测逐分钟全量刷日志670条约1.7MB（新增）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：主树 untracked 散件归因探测（worktree-vc 周期盘点，将主树未跟踪文件归因到在用会话后复位宽限计时的只读探测）以每分钟一次的频率全量打印 53 个文件路径，窗口内 670 条 INFO 行（单条约 2.5KB，合计约 1.7MB 日志）；集合构成整天不变（.verify-fixture-sdh/ 验证夹具残留、spec/knowledge/_inbox 三件、idea.md 等）仍逐分钟重刷，属日志膨胀与检索噪音，零 run 损耗。
  - 证据：grep「主树 untracked 散件归因」全日志 1121 条（2026-10-30 起），其中 2026-11-04 当日 670 条，窗口末条 16:03:59Z（本地 11-05 00:03）；样例行每分钟一条、全量列出 53 个文件路径并以「复位宽限计时（不升级不处置）」收尾；集合中 .verify-fixture-sdh/ 为 add-systemd-hosting 验证夹具残留（git status 至今 untracked 未清理）。
  - 调查评估：在 worktree-vc 主树 WIP 盘点车道暴露。已核实事实：条数、每分钟频次、单条体积与集合构成逐一度核；行为语义本身正确（归因到主树活交互会话、非无主盲区、不升级不处置），缺的只是输出聚合——同集合指纹未变时逐分钟重复全量打印。与存量关系：worktree-vc 域「主树 WIP 占用归因单源、周期盘点与滞留升级」能力页已入库，覆盖归因与升级语义但未见日志聚合契约；spec/changes/evo-merge-back-wip-overlap-gate 带 SUPERSEDED.md（已被取代）非承接方。结论：纯日志卫生问题，量级随夹具滞留天数线性放大，适合小改随其他 worktree-vc 交付顺带落地。
  - 建议：探测输出按集合指纹聚合：集合不变时首次全量、其后降为一行计数摘要或每 N 分钟才重打；同时清理验证夹具目录或纳入 .gitignore 使集合收敛。
