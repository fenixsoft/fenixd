
## 2026-11-02
### 知识真相源
- audit 疑点升级待人工（聚合）：10 条待人工仲裁（最长龄期 35 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

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

### 失误
- **arbiter 提案三连烧六轮评审全否决，靠软删除收场暴露提案质关前移缺口**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：三条 arbiter（自主裁决车道）立项提案各烧两轮 spec-review 全被否决（escalation critical ×3）后软删除收场：fix-escalation-freeze-vs-parallel-admin-race、fix-scenario-revision-choice-registration-surface（评审否决×2 后撤销、race 主题转 todo 由自进化接手）、stale-code-governance-activation-window（评审否决×2 冻结后撤销），共 6 个评审 run 与 3 次 admin 升级处置的纯消耗，无交付产出。
  - 证据：git 提交链：0793024d6/02166efcc/e953…（21:25/19:31 arbiter 提案最小成文）、795e9f6b4 等评审留痕、90d04f003（22:32 软删除 stale-code-governance-activation-window）、28eab64ff（22:12 撤销两条冻结件）；admin_alerts.json 窗内 spec-review-rejected 升级告警 77705c61638b、2e80fc90bf39（critical）及对应 disposition（裁决处置记录）escalated 各一条；停滞聚合行中三条提案的 spec-review run 各 2 个在档。
  - 调查评估：在 arbiter 立项通道退役过渡期暴露。已核实事实：三条提案的创建-评审否决-软删除全链提交与告警均在档；评审 run 共 6 个（每条 2 轮）。根因评估：arbiter 立项通道退役注记（arbiter-proposal-filing 能力页，本窗 23:39 蒸馏入库）落地前，通道仍允许最小成文提案进入评审，提案质量闸门只有评审兜底、无入口预检，形成「提案-否决-再提案-再否决-撤销」的固定消耗模式；评审门本身按设计工作（有效拦截低质提案），消耗集中在入口端。与存量关系：add-arbiter-gap-todo-routing（本窗交付归档中）已把 gaps 改路由 todo，退役注记生效后同类提案不再入评审；本条为过渡期成本的留痕确认。结论：通道治理已闭环、过渡消耗已发生，无残余敞口，不建议再立项。
  - 建议：无需新立项：退役注记与 gaps→todo 路由本窗已落地，后续窗口观察 arbiter 提案入口零新增即可；如再现提案入评审即按退役注记打回。

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
