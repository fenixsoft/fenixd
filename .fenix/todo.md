## 2026-11-02

### 知识真相源
- audit 疑点升级待人工（聚合）：13 条待人工仲裁（最长龄期 53 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

## 2026-11-03

### 浪费
- **API 停滞 11 run 合计 92 分钟纯等待，升级接线窗内未生效**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：窗口内 11 个 run 累计 API 停滞约 5530 秒（≈92 分钟）纯等待，零失败零金额损失，损失面全在墙钟；最重单 run 停滞 1219.5 秒占其 1355.7 秒时长的 90%，最长单轮 513.1 秒。
  - 证据：数据摘要第 6 节 11 行 api-stall（单轮超 60 秒的 API 往返停滞）聚合行相加得 5529.8 秒；抽 4 个 run 回源 run_metrics（run 终态指标行）原始值吻合：impl-move-distill-trigger-to-push-1793590053-a1（move-distill spec 的实现首派）latency_stalls=5/latency_max=412.94、planner-plan-move-distill-trigger-to-push-1793590053-a1（同 spec 的规划 run）stalls=4/max=513.095、spec-review-fix-distill-observation-gaps-797d21-1793594658（fix-distill spec 的评审 run）stalls=9/max=297.91、code-fix-1793561792（code-review 台账修复 run）stalls=0；窗内 admin 信号面 0 条 api_round_stall_escalated（停滞升级信号）。
  - 调查评估：在 move-distill-trigger-to-push 与 fix-distill-observation-gaps 两 spec 的规划/实现/评审车道暴露。已核实事实：停滞计数与最大值抽 4 run 逐项吻合终态指标行（合计未逐行重算——终态行无 total 字段，样本和出自事件侧聚合，故合计按第 6 节聚合行口径转引并如实标注）。根因未定、多假说并存：网关排队/长上下文/本地网络（2026-11-02-evo-add-api-stall-disposition-closeout 的非目标原文留三假说待留痕积累），不据单一假说给修复方向。与存量关系：停滞分级与第 6 节聚合行出自 2026-10-30-evo-api-stall-signal-grading，升级信号+失败零进度受控重试+终态 latency 透传出自 2026-11-02-evo-add-api-stall-disposition-closeout（21:55 归档入库，提交 1b1590634）——窗内全部停滞 run 结束于 13:31 前，早于归档时点，且 03:48/12:17 两条 stale_code 信号（daemon 持旧代码自愈链）在证 daemon 当日中午仍持旧代码，故本窗停滞未被升级面覆盖属时序而非缺口（接线实际装载时刻未核实）。结论：观测与处置面存量已闭环，本条仅留痕当日实损并立一个可证伪预期。
  - 建议：下窗若再现单轮超 300 秒停滞，核对 admin 信号面是否出现 api_round_stall_escalated，验证 21:55 接线经陈旧自愈重启后真实生效；若连续两窗停滞依旧而无升级信号，再按信号面接线缺口立项排查，不预设停滞根因。

- **蒸馏同件三派两空转，落库延迟 165 分钟并留无终态残留**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：是
  - 影响：同一归档件的知识蒸馏三派才落库，首派到落库跨 165 分钟，两次空派发 rounds=0（LLM 成本≈0），并产生窗内唯一无终态残留账目（runs 统计「无终态残留: 1」即此件）。
  - 证据：runs/archive/knowledge-distiller-2026-11-02-fix-frozen-scenario-dict-salvage-1793587613.jsonl（首派档案）全文仅一行 started（10:46:53，rounds=0，无终态行）；同件 1793597114 号档案记 started 13:25:14 后同秒被 interrupted，reason=startup terminal-state sweep（daemon 启动时对无终态 run 的终态清扫）；成功落库为提交 1998cbf35（13:31:19，[fenix] knowledge: distill，触及 spec/knowledge/ 多个知识页）。
  - 调查评估：在蒸馏车道消费 fix-frozen-scenario-dict-salvage（已归档的冻结场景修复 spec）时暴露。已核实事实：两次失败尝试 rounds=0，第三次 13:31 落库成功，无终态残留与 interrupted 各有一次在档。根因分层：第二次有直接记录——13:25 的 daemon 启动清扫把与启动同秒刚派发的蒸馏 run 判为启动前残留并中断（重启本身由清扫行在证；「13:19 merge fix-distill-observation-gaps 动了 core/ 触发陈旧自愈重启」属推断未核实）；第一次死因未定（无终态无中断行，假说：当时早死路径未落任何终态/中断行）。与存量关系：无终态残留 D4 对账桶（self_review 的 stale 桶）已能识别此类残留，但启动清扫对「重启窗口内同秒新派发」无豁免、蒸馏器早死路径无终态兜底落行。结论：单次损失极小，但属重启竞态复发行，敞口=每次陈旧自愈重启撞上新派发即再现。
  - 建议：startup sweep 对 daemon 停机/启动窗口前后数秒内新派发的 run 豁免或改记 pending 而非 interrupted；蒸馏器无论何种早死路径都补写终态行，消除 stale 桶残留。

### 失误
- **impl 收尾两处形态失配，48 分钟 run 被硬门拒收重派**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：是
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
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：是
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

### 可改进
- **startup sweep 无在途判据，当日两起错杀 62 分钟与 22 分钟在跑 run**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：是
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

## 2026-11-05

### 浪费
- **stale自愈重启再杀3个在飞run，planner与两impl约113分钟作废（恶化）**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：窗口内一次 stale_code_selfheal（daemon 检测磁盘代码比进程内存旧后自动计划重启的自愈链）计划重启经 50 秒排水窗口未能等到任何在飞 run 收尾，SIGTERM 硬杀 3 个在飞 run：planner-plan-add-systemd-hosting-1793755316-a1（40.1 分钟/111 轮出题全废）、impl-add-systemd-hosting-1793755316-a1（40.0 分钟）、impl-fix-escalation-chain-ledger-closure-1793755758-a1（32.7 分钟），合计约 113 分钟在飞时间作废并全数重派；交付零损失（分支保全、重派 45 秒至 23 分钟收尾），损失面为在飞工时加重派成本。
  - 证据：日志链：本地 10:00 fix-escalation impl 收尾提交 1b3a9904e 动 core/ → 09:24 已有 stale 检测 WARNING（磁盘 mtime 超 baseline）→ 10:01:13「Shutting down...」→ 10:02:06「Drain finished after 50s, remaining runs:[3个]」同秒三条「Sent SIGTERM to running agent」；planner run 档案尾部依次为 interrupted（reason=daemon shutdown，10:02:06.475）、run_metrics（duration_s=2403.5、turns=111、latency_max=493.3）、error「Exit code: 143」（exit 143 成批同刻出现=排水屠杀签名，见 error-attribution-denoise 能力页判读法）；两个 impl run 档案尾部仅 interrupted、均无 run_metrics 行（转写者随杀而死的指标盲区，与上窗同型）。
  - 调查评估：在 add-systemd-hosting 与 fix-escalation-chain-ledger-closure 两 spec 的 impl/planner 车道暴露。已核实事实：三个 run 的起止 span（09:22/09:29 起跑至 10:02 被杀）与 SIGTERM 行逐一度核，排水窗口 50 秒与上窗实测一致，对单轮 API 往返常态 60-490 秒的 run 结构性不够等。根因：结构性缺口——每个交付日动 core/ 的 merge 都触发 stale 自愈重启，重启必然撞上下一批在飞 run。与存量关系：这是 2026-11-04#浪费#2（上窗 4 次重启杀 6 个 run 约 114 分钟）的同族复发，其建议（排水窗口对齐 LLM 轮长、在飞 WIP checkpoint 续做、worktree 唯一性）至今未立项，spec/changes/ 无对应 spec；本例触发重启的收尾提交恰出自 fix-escalation-chain-ledger-closure spec 自身，交付税自食。结论：第二日连发证实敞口稳定，属系统性缺口非一次性失误。
  - 建议：将上窗建议立项小 spec：agents.run_drain_max_seconds 提到 ≥300 秒；drain 期间对在飞 run 落 WIP checkpoint 后即停、新进程按 checkpoint 续做而非整体重派；重启触发条件增加「在飞 run 数大于 0 时顺延重启」的最小闸门。

- **API停滞回落至20 run合计175.5分钟，升级信号面首次捕获并闭环（好转）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：窗口内 20 个 run 累计 API 停滞（单轮 API 往返超 60 秒的等待段）10529.2 秒约 175.5 分钟，较上窗 370 分钟回落过半，仍为两窗前 92 分钟的近 2 倍；最重单 run planner-plan-add-systemd-hosting-1793757731-a1 停滞 1627.3 秒、最长单轮 387.5 秒；零失败零金额损失，损失面全在墙钟。
  - 证据：数据摘要第 6 节 20 行 api-stall 聚合行相加得 10529.2 秒（终态指标行无 total 字段，按聚合行口径转引并如实标注，与上窗同口径）；抽 planner-plan-add-systemd-hosting-1793755316-a1 终态 run_metrics 原始值核对吻合（latency_rounds=52、latency_stalls=9、latency_max=493.3）；本窗 admin 信号面首次出现 api_round_stall_escalated（API 停滞升级信号）：告警 a14031730875 于本地 10:02:11 落账（latency_max=493s）、10:12:08 处置终态 resolved 并回写 handled=true。
  - 调查评估：在 planner-plan×5、impl×4、spec-review×4、planner-judge×3 等多车道暴露。已核实事实：合计按聚合行口径相加、抽样与终态指标行吻合；升级信号面在本窗真实工作——唯一超 300 秒升级线的 run（493.3 秒）恰为被排水屠杀的非 success 终态，不被 success 豁免面（曾停滞但正常完成的 run 不升级，monitor-escalated-signal-negative-controls 的有意设计）覆盖，信号落账并闭环处置，回答了上窗「接线经陈旧自愈重启后是否真实生效」的遗留问题：生效。根因仍多假说并存（网关排队/长上下文/本地网络，2026-11-02-evo-add-api-stall-disposition-closeout 留痕），不预设。与存量关系：上窗建议「不再以升级信号为验证锚，改在 cost-observability（成本观测域）为停滞聚合定义常规出口（model 字段对照/收敛试验）」未落地——该域无新增能力页，spec/changes/ 无对应 spec。结论：三窗走势 92→370→175.5 分钟属持续摩擦非失控，观测闭环、聚合出口缺口。
  - 建议：按上窗建议落最小出口：连续两窗合计超 150 分钟时按 run_metrics 的 model 字段做模型版本对照与提示词/provider 路由收敛试验（本窗 20 run 的 model 字段已齐备可支撑），替代逐窗人工对账。

### 失误
- **task_gate拒收第二例：done_ids漏勾任务4.2，收尾自检仍缺席（恶化）**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：是
  - 影响：fix-escalation-chain-ledger-closure 的实现重派 run 在终点被 task_gate（implementer 产物硬门）拒收：done_ids（TaskUpdate 完成记录）未覆盖已勾选任务 4.2，重派 a2 花 45.3 秒、12 事件补账过闸；损失约一次拒收-重派周期（分钟级），交付未损（merge 41940d213 已含全部任务提交）。
  - 证据：impl-fix-escalation-chain-ledger-closure-1793757732-a1 档案末行 gate-blocked（本地 10:06:35）reason=task_gate，error 原文「[task-gate] exit 0 但已完成任务与 TaskUpdate 记录不一致（implementer 产物硬门）: done_ids 未覆盖已勾选任务 4.2」；a2 档案 12 事件、duration 45.3 秒 result 收尾；与上窗同型：2026-11-03#失误#1 记 move-distill-trigger-to-push 首派 2895.5 秒被拒（漏任务 2.3）。
  - 调查评估：在 fix-escalation-chain-ledger-closure 实现收尾时暴露，且本例 a1 是 10:02 重启排水屠杀后的重派 run（09:29 起跑 32.7 分钟被杀→重派→收尾失配被拒），杀-重派-拒收链放大了重启税。已核实事实：拒收行与 a2 补账时长逐一度核。根因与上窗一致：run 内收尾自检不覆盖「tasks.md 勾选集合与 TaskUpdate done_ids 集合」对账，失配只能靠框架硬门终点拦截，agent 自述自检通过与硬门口径脱节。与存量关系：2026-11-03#失误#1 的第二例，其建议（收尾自检补两项对账）未落地即复发；守卫面两例均按设计工作、零漏网。结论：两窗两例构成执行惯性点，属 implementer 提示词自检清单缺口非框架缺口。
  - 建议：在 implementer 提示词收尾自检清单补两项：tasks.md 勾选集合与 TaskUpdate done_ids 集合一致、quality-gates.json 状态值在 passed 枚举内；落地后此类失配应在 run 内自纠而非终点拒收重派。

### 可改进
- **纯文本轮通胀第三窗命中且同车道三run并发，响应端仍未落地（恶化）**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：是
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

## 2026-11-06

### 浪费
- **mobile出题并行链三派两空转，串行第三派兜底落盘**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：redesign-dashboard-v2-ui-mobile 一份场景集耗三派出题才落盘：首派出题 run 整体报废（22 分钟 119 轮死于网关连接复位 ECONNRESET）、第二派被编排层超时取消（35 分钟 129 轮），三 run 合计纯 API 停滞约 58.6 分钟，出题链从 18:14 拖到 19:57，交付零损。
  - 证据：出题 a1 档案（planner-plan-redesign-dashboard-v2-ui-mobile-1793873658-a1.jsonl）末行 error「Exit code: 1」、result 行原文「API Error: Connection dropped (ECONNRESET)」、run_metrics（run 档案末尾终态指标行）turns=119/duration_s=1316.6/latency_stalls=4/max=258.1；a2 档案 cancelled 行 reason=「并行出题等待超时，取消后转串行重出」、turns=129/stalls=13/max=338.3（18:36:32 起跑，19:11:39 取消）；串行 a3（1793877098）turns=239 success、stalls=9/max=233.7；升级链三行日志：19:12「api_round_stall_escalated 信号已落」（告警 146abcebcdad，API 停滞升级信号）→ 19:17 invoking Administrator（run admin-fenixd-1793877431）→ 19:21 处置终态 resolved+handled=true。
  - 调查评估：在 mobile spec 场景出题车道暴露。已核实事实：a1/a2/a3 起止 span、终态行、停滞指标逐一度核吻合（档案 run_metrics 原值，三 run 停滞合计 577.0+1501.9+1439.1=3518 秒）；a2 的 35 分钟里停滞占 25 分钟，并行等待预算被 provider 长尾吃穿后触发取消，串行重出 45 分钟一次成功。根因分层：a1 死于网关连接复位（瞬态，错误文本自证形态）；a2 取消属编排层「并行出题等待超时→转串行」设计行为，但预算计时未区分「API 停滞等待」与「有效出题进展」，把 provider 长尾计入预算提前判死；停滞根因未定、多假说并存（网关排队/长上下文/本地网络，2026-11-02-evo-add-api-stall-disposition-closeout 留痕口径），不预设。与存量关系：Administrator 处置已定性「非产品缺陷、零干预收尾，338s 属 provider 长尾（与历史基线 514.3s 同量级）」（admin_disposition-admin-fenixd-1793877431.json 自述）；升级信号面第二次真实闭环（上窗告警 a14031730875 首例）；另注：取消事件的告警 kind 文案写作「人工取消 run」（告警 ff56c13408d7），实为编排层自动取消，处置记录特意澄清，命名易误导后续 triage。结论：串行兜底有效、交付零损，实损为两派空转轮次与约 58.6 分钟停滞等待；同窗该 spec 出题首判 17/30 场景 test-defect（其中 11 个败于夹具项目被用户级 registry 软删除，judge 补 fixture-registry-unignore seed 幂等解除后自愈）进一步拉长了验证链总时长。
  - 建议：并行出题等待预算改为停滞感知：run 处于 API 停滞区间（单轮往返超 60 秒）时预算暂停计时，避免把 provider 长尾误判为出题超时而取消重派；编排层自动取消的告警 kind 与「人工取消」文案区分开。

- **API停滞第4窗23run合计210分钟，聚合出口仍未落地（恶化）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：窗口内 23 个 run 累计 API 停滞（单轮 API 往返超 60 秒的等待段）约 12607.5 秒 ≈ 210.1 分钟纯墙钟等待，为四窗序列 92→370→175.5→210.1 的第二高位；两窗合计 385.6 分钟已越过上窗自定的「连续两窗超 150 分钟做模型对照与收敛试验」触发线且无机制承接；零失败零金额损失。
  - 证据：数据摘要第 6 节 23 行 api-stall 聚合行相加得 12607.5 秒（终态指标行无 total 字段，按聚合行口径转引并如实标注，与前三窗同口径）；抽 6 个档案终态 run_metrics 原值核对吻合：a2 stalls=13/max=338.3、a3 stalls=9/max=233.7、evo-1793877486 max=350.2、planner-judge-mobile-1793880022 stalls=5/max=266.8、impl-v2ui stalls=5/max=187.2、code-fix-1793879016 stalls=13/max=151.9；单轮超 300 秒升级线 4 run——evo-1793877486（350.2，success）、planner-plan-v2ui-1793864343（325.5，success）、planner-plan-v2ui-1793868644（315.1，success）、a2（338.3，cancelled，唯一被升级面捕获）。
  - 调查评估：在出题/评审/实现/code-fix/evo 六车道普遍暴露。已核实事实：合计按聚合行口径相加、抽 6 档案原值吻合；上窗 175.5 分钟为其回顾留痕值（同口径，抽上窗档案 planner-plan-add-systemd-hosting-1793757731-a1 复核 stalls=9/max=387.5 与留痕吻合）。升级信号面本窗再次真实工作：唯一非 success 终态的超线 run（a2）触发 api_round_stall_escalated（告警 146abcebcdad，19:12 落账、19:21 处置闭环），3 个 success 终态超线 run 被 success 豁免面放行（monitor-escalated-signal-negative-controls 修复的有意设计）。根因未定、多假说并存（网关排队/长上下文/本地网络，既有留痕），不预设。与存量关系：cost-observability 域 api-stall-observability 能力页现行文本仍无聚合出口（grep 出口/收敛/对照零命中，本窗复核）；上窗建议的触发条件（两窗合计超 150 分钟）自上窗起成立、至今两窗无承接。结论：观测闭环、升级面工作、聚合出口缺口第四窗，属既有建议的落地拖延非新缺口。
  - 建议：落 cost-observability 域聚合出口：按 run_metrics 的 model 字段出模型版本对照报告并做提示词/provider 路由收敛试验（本窗 23 run 的 model 字段全部为 glm-5.3-flash、字段齐备），替代逐窗人工对账。

### 失误
- **quality-gates.json再现形态漂移，list冒充对象被放行**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：是
  - 影响：redesign-dashboard-v2-ui-mobile 实现收尾把 quality-gates.json（验证质量门状态文件）顶层 gates 写成 list（应为对象），守卫宽松对账告警放行、本窗零拒收零重派；这是该文件形态漂移第三窗第三种形状（11-03 枚举漂移「pass」、本窗结构漂移「list」），复发敞口为下次漂移撞上严格门时重演终点拒收-重派周期（11-03 实测代价 48 分钟 run 被拒）。
  - 证据：告警 4050a28333ff 与 17940053dbf9（quality-gates 形态漂移信号，本窗 18:56 恰为 impl-mobile 合并分钟）原文「quality-gates.json 顶层 gates 键非对象（实际类型 list，宽松对账，仅告警放行）: .fenix/verify-progress/redesign-dashboard-v2-ui-mobile」；本窗日志 grep「gate-blocked」「task_gate」零命中（守卫零拒收）。
  - 调查评估：在 mobile spec 实现收尾时暴露。已核实事实：两条告警同分钟成对、对象路径指向 mobile 的 verify-progress 目录、本窗无任何 gate-blocked。根因：quality-gates.json 由实现 run 自由写盘、写侧无 schema 校验，漂移只能靠 monitor 事后对账发现；monitor 按「宽松对账、仅告警放行」设计放行，执行层得不到硬反馈，漂移惯性得以延续。与存量关系：2026-11-03#失误#1（pass/passed 枚举漂移致 48 分钟 run 被拒）与 2026-11-05#失误#1（task_gate 的 done_ids 失配第二例）同族，两例建议（implementer 收尾自检清单补对账与枚举校验）至今未落地（core/ 内 grep「收尾自检」无提示词面命中，实现提示词模板落点未核实）；本窗新增第三种漂移形状（list 冒充对象），证实漂移面在枚举维之外还有结构维。结论：守卫面按设计工作（发现+放行+留痕），缺口在写侧自检缺席，属执行惯性点非框架缺陷，两例历史建议应合并落地。
  - 建议：为 quality-gates.json 落共享写侧校验（顶层 gates 必须对象、status 枚举限 passed），并把该文件写后自检并入 implementer 收尾自检清单（与 tasks.md 勾选↔TaskUpdate done_ids 对账项同批），使形态漂移在 run 内自纠而非告警留痕。

### 可改进
- **晋升lint不识在途依赖，mobile晋升延迟44分钟**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：是
  - 影响：redesign-dashboard-v2-ui-mobile（depends_on redesign-dashboard-v2-ui）起草晋升连续两次被产物晋升声明检查（promotion lint）拒绝，卡 drafted（草案）态 44 分钟，靠 30 分钟恢复节拍在基线 spec 合入后才自动晋升；同族前例（10-31）曾因同 lint 双失败触发 daemon_errors critical 误升级人工面并建议重启 daemon。
  - 证据：日志链：08:22:43Z 与 08:36:47Z 两条「Promotion lint failed 'redesign-dashboard-v2-ui-mobile'」ERROR（7 个 modify 声明路径——v2/theme.tsx、overview.tsx、projectDetail.tsx、specDetail.tsx、settings.tsx、help.tsx、ops.tsx——全不在主树）；08:36:47Z 与 09:06:48Z 两条「Recovery: re-triggering promote」（event_bus 恢复节拍）；09:06:48Z「Auto-promoting … drafted → reviewing」（本地 17:06:48，恰为 spec-review 起跑同一秒）；基线 v2-ui 实现分支合入主树为提交 05fa47338（16:50）；前例：fenixd.log 2026-10-31T12:33/12:34 同 lint 对 add-arbiter-backlog-sweep 双失败后，admin_monitor 以「同指纹 ≥2 次且最近两次间隔 ≤5 分钟」升级 daemon_errors critical（信号原文在档）。
  - 调查评估：在 mobile spec 起草晋升时暴露。已核实事实：双失败、两次恢复节拍 re-trigger、晋升成功时刻（17:06:48）与基线合入时刻（16:50）的先后关系逐一度核；mobile spec 对 7 个 v2 文件声明 modify 语义正确（移动端适配就是改这些文件），错不在声明而在时序——晋升发生在基线实现分支合入前 28 分钟，lint 的「modify 路径必须在主树存在」判据结构性地不兼容 depends_on 在途基线。根因属系统性缺口：晋升链现有「软化不可满足声明」步骤未覆盖「路径将由在途依赖交付」形态（spec-lifecycle 域 draft-promotion-gate 能力页现行规则无 depends_on 豁免，本窗复核），属既有规则的缺口而非重复立项。与存量关系：10-31 同 lint 双失败曾把声明类 lint 失败当 daemon 故障判读、误升级 critical 并建议重启 daemon；本窗双失败间隔 14 分钟侥幸未触发同指纹升级线，敞口仍在。结论：恢复节拍兜住了交付，代价 44 分钟管线延迟与 2 条 ERROR 噪音，值得小 spec 治本。
  - 建议：promotion lint 对「声明路径命中未合入 depends_on 基线 spec 自身 deliverables」的 modify 声明改记 existence-pending（放行加注解，或晋升触发顺延至依赖合入事件）；同步收紧 daemon_errors 指纹升级面对 pm_engine 声明类 lint 失败的判读，不再建议重启 daemon。

- **startup sweep同秒误标第三例，成功蒸馏档案裂两份（恶化）**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：是
  - 影响：04:06 daemon 陈旧自愈重启（stale_code_selfheal，检测到磁盘代码比进程内存旧后计划重启的自愈链）时，启动清扫（startup terminal-state sweep，daemon 启动时对尾部无终态 run 档案补写 interrupted 的扫描）把同秒派发、且 19 分钟后成功落库的蒸馏 run 误补 interrupted——该 run 档案裂成两份（归档侧记失败、活跃侧记成功），账面失真但交付零损；同秒竞态第三日连发，前两例实损 62/22 分钟在飞 run。
  - 证据：归档件 runs/archive/knowledge-distiller-add-systemd-hosting-1793822801.jsonl 全文两行：started（rounds=0，04:06:41）+ interrupted（reason=startup terminal-state sweep，20:06:41.721Z）；活跃件 runs/knowledge-distiller-add-systemd-hosting-1793822801.jsonl 三行：heartbeat 04:21:41 → round 04:25:05 → result 04:25:06（commit 9d5f616b9）；日志行「Startup terminal-state sweep: 补写 1 个遗留 无终态 run 的 interrupted 终态: knowledge-distiller-add-systemd-hosting-1793822801」（20:06:41.721467Z）；蒸馏产物经 git show 9d5f616b9 实锤（daemon-runtime/systemd-hosting.md 等 14 个知识文件）。
  - 调查评估：在蒸馏车道（knowledge-distill，归档件知识蒸馏）消费 add-systemd-hosting、daemon 陈旧自愈重启窗口内暴露。已核实事实：两份档案逐行核对、误标 interrupted 与成功产物共存于同 id 的两个文件、重启链闭合（03:10 stale 检测 WARNING → 04:06 空闲 301 秒触发重启 → 启动清扫同秒补写 → 恢复重派 19 分钟后成功）。根因：run-resilience 域 runtime-run-sweep 能力页明文「启动清扫既有行为（孤儿进程存活不阻塞补写）保持不变」——启动清扫只看「尾部无终态」不做在途判据，与恢复重派同秒竞态结构性无解；本例新形态是账面失真升级为档案分裂（归档侧 interrupted 与活跃侧 result 各执一词），对账时需人工拼合。与存量关系：2026-11-04#可改进#1 的第三例复发，其建议（补写前对派发记录或档案 mtime 新于停机时刻的 run 改记 pending）仍未落地；fix-distill-observation-gaps 与 move-distill-trigger-to-push 至今滞留 spec/changes/ 活跃区且均未触及 sweep 判据（11-04 代码级结论，本窗未见反证）。结论：本例零实损但证实敞口稳定（三窗三例），判据缺口仍开放，与 2026-11-04#可改进#1 同源不另立项。
  - 建议：同 2026-11-04#可改进#1：启动清扫补写前增补在途判据（派发记录或档案 mtime 新于停机时刻→改记 pending 交运行期清扫二次裁决），并补一步对账自愈——同 id 档案活跃侧已出现新终态时撤回误补的 interrupted。

- **纯文本轮通胀第4窗命中，出题车道3连窗响应仍缺席（恶化）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：planner-plan（出题）车道本窗 2 个 run 命中纯文本轮离群维（text_turns，无工具调用的模型回复轮：a1 61/119 占 51.3%、a2 70/129 占 54.3%），该形态第四窗持续命中、出题车道第三连窗（11-04 一 run、11-05 三 run、本窗两 run，同一模型 glm-5.3-flash）；复发敞口为每窗多烧一轮演化复核注意力，上窗实测曾白跑一轮复核。
  - 证据：两 run 档案终态 run_metrics 原值：a1 turns=119/text_turns=61/duration_s=1316.6、a2 turns=129/text_turns=70/duration_s=2106.6，model 均为 glm-5.3-flash（逐字段核对吻合）；检测 spec evo-refine-midflight-outlier-dims 已归档（spec/archive/2026-11-04-evo-refine-midflight-outlier-dims 在档实证），其三项交付均为观测端、无响应端定义。
  - 调查评估：在 mobile spec 出题车道暴露，为该离群维度第四窗命中。已核实事实：占比与 model 字段逐一度核，检测 spec 归档件无响应端交付。根因未定（模型输出行为漂移假说，检测 spec 原文口径），token 面不可量化（该车道 run_metrics 的 input_tokens=0 计量缺失）。与存量关系：上窗条目 2026-11-05#可改进#2 建议的「同车道连续两窗命中即按 model 字段做模型对照与提示词收敛试验」——出题车道 11-05 窗（3 run）与本窗（2 run）已两连窗命中，触发条件成立满两窗，响应端仍零机制（cost-observability 域无聚合出口能力页、spec/changes/ 无对应 spec，本窗复核）。结论：从「跨车道扩散」到「同车道聚集」再到「同车道连窗」，观测闭环后响应端落地时机已过两窗，建议不再观察直接落最小响应。
  - 建议：落最小响应机制：同车道连续两窗命中即按 model 字段出对照报告并做出题提示词收敛试验（如压缩逐轮叙述性输出指引），单窗命中仅留痕；可与 API 停滞聚合出口同一个小 spec 承接（同域 cost-observability、同数据源 run_metrics）。

- **distill重试台账成功不清账，欠账告警落库后复燃**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：add-systemd-hosting 的知识蒸馏已于 04:25 落库（提交 9d5f616b9），但「knowledge-distill 重试台账欠账超 24 小时未重试」告警在其后 17 与 20 小时仍复燃两次（21:30、次日 00:00），台账成功不清账将持续空转 warning 噪音，并误导「蒸馏仍未完成」的人工判读。
  - 证据：告警 7c529c2bdcfc（21:30）与 4834d132796d（次日 00:00）原文均为「knowledge-distill 重试台账欠账超 24 小时未重试（1 条）：add-systemd-hosting（登记 2026-11-04）」；蒸馏成功实锤：runs/knowledge-distiller-add-systemd-hosting-1793822801.jsonl result 行 commit=9d5f616b9（04:25:06），git show 该提交含 systemd-hosting.md 等 14 个知识文件；窗内该告警共 4 次（00:02/04:11 两次属落库前合法欠账提醒，21:30/00:00 两次为落库后复燃）。
  - 调查评估：在蒸馏重试台账的消费面暴露。已核实事实：4 次告警时刻与落库时刻（04:25）先后核对，后两次分别晚于落库 17/20 小时，且告警语义仍是「未重试」而实际重试已成功。根因：重试台账条目仅在人工核查或显式处置时清账，蒸馏成功路径（result 行带 commit）不回写台账，欠账检查只看登记时间不看完成状态。与存量关系：2026-11-04#知识真相源#1 预测「将由 daemon 重启续跑接管」已应验（04:06 重启→按台账恢复重派→成功），该待办可判闭环（见 resolved）；但配套告警面未同步，台账成功清账缺口此前无条目登记，属本窗新发现。结论：纯记账卫生问题、量级小（warning 级、约 8 小时一拍），但持续污染「蒸馏是否完成」的判读信号，适合随蒸馏车道下次交付顺带落地。
  - 建议：蒸馏 result 行落 commit 后同步清账（或欠账检查先核对该 spec 是否已有 distill 提交再告警），告警文案带上最近一次尝试状态防误判。

- **主树untracked探测刷屏862条，聚合改造未落地（恶化）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：主树 untracked 散件归因探测（worktree-vc 周期盘点，将主树未跟踪文件归因到在用会话后复位宽限计时的只读探测）本窗按每分钟一次全量打印 862 条 INFO 行（上窗 670 条，+29%），从 00:01 持续刷到 22:10，约 2MB 日志膨胀与检索噪音；集合构成已从 53 文件收敛到 5 文件，但逐分钟重刷行为未变。
  - 证据：窗口内 grep「主树 untracked 散件归因」862 条（日志扫描计数，UTC 2026-11-04T16:01 ~ 2026-11-05T16:01）；样例行全量列出 5 路径（docs/superpowers/specs/2026-10-28-agent-card-redesign-design.md、idea.md、spec/knowledge/domains/worktree-vc/stray-escalation-clock-persistence.md、同目录 untracked-stray-session-attribution.md、z-ignore-control-probe-file）并以「复位宽限计时（不升级不处置）」收尾；相关告警 b981cdd296c4/eca93b38939a（untracked 首现提示）与 fcf24fe41ff9（超阈值滞留，info 只告警）在档。
  - 调查评估：在 worktree-vc 主树 WIP 盘点车道暴露，为 2026-11-05#可改进#3 的第二窗复发且量升。已核实事实：条数、每分钟节奏、集合构成收敛（53→5，大头随 knowledge fold 提交入库）逐一度核；行为语义仍正确（归因活会话、非无主盲区、不升级不处置）。根因不变：缺输出聚合契约——同集合指纹未变时逐分钟全量重打。与存量关系：上窗建议（按集合指纹聚合：首次全量、其后一行计数摘要或 N 分钟降频）未落地；本窗集合里恰有该能力域自家两页知识页（untracked-stray-session-attribution、stray-escalation-clock-persistence）滞留未跟踪——蒸馏产物本身成为刷屏素材。结论：纯日志卫生问题，量级随散件滞留天数线性放大，聚合改造拖延一窗、持续恶化。
  - 建议：维持上窗建议：探测输出按集合指纹聚合（集合不变时首次全量、其后降为计数摘要或降频重打）；顺带把滞留的两页 worktree-vc 知识页与 idea.md 等散件收编提交使集合收敛。

## 2026-11-07

### 知识真相源
- audit 语义项转写失败：contradiction（spec/knowledge/domains/worktree-vc/mergeback-archive-residue-selfheal.md × spec/knowledge/domains/worktree-vc/wip-defer-merge-retry.md），请人工核查
- audit 语义项转写失败：contradiction（spec/knowledge/domains/dashboard-frontend/v2-overview-page.md × spec/knowledge/domains/dashboard-frontend/v2-project-detail-page.md），请人工核查
- audit 语义项转写失败：contradiction（spec/knowledge/domains/dashboard-frontend/unified-page-title-bar.md × spec/knowledge/domains/harness-integration/agent-harness-adapter.md），请人工核查

## 2026-11-08

### 可改进
- **[arbiter:add-inte] 集成测试交付物代理注入面缺失（GitHub 限速环境下「修环境」出口不可达）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：add-integration-test-env 及同类 Docker 克隆型 SPEC 的验证轮在国际链路限速时段必败，manual_fixed_reverify（修环境重验）出口结构性不可达，人工只剩「豁免（失覆盖面）」或「赌网络窗口重验」两选项；每次限速窗口都产生一轮豁免握手停车+人工裁决负担
  - 证据：tests/integration/run.sh 与 Dockerfile 不支持代理环境变量注入/透传（无 HTTPS_PROXY 类面）：验证轮容器内 GitHub bulk 截断时唯一失败路径无法通过环境修复翻绿（.fenix/runs/archive/admin-add-integration-test-env-1794066458.jsonl 探针：~41KB/s、8m47s 死亡、ref 协商与 npm 健康；.history/it-verify/smoke/orchestrate.log:5,11 GnuTLS -110/early EOF）；同轮证明交付物经 FENIX_IT_GIT_REPO 本地源路径实测全绿（.fenix/verify-evidence/add-integration-test-env/smoke-summary.json）；触发 run_id=arbiter-add-integration-test-env-1794067782（签名 add-integration-test-env::inconclusive_loop，来源 chain-handoff:escalation-alert）
  - 调查评估：触发信号 inconclusive_loop（spec=add-integration-test-env）：'add-integration-test-env' 连续 1 轮验证失败均被裁决归类 env（级二豁免握手首次命中即升级（judge 已裁决全 env），env 断言 2 条、blocked-env 场景 0 个），judge 已裁决全部失败归环境、等待人工豁免或修环境——自动重验已停止。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：交付物增强：run.sh 支持 FENIX_IT_HTTPS_PROXY（或透传宿主 HTTPS_PROXY/ALL_PROXY）并配置容器内 git/npm 走代理；或克隆源分级 fallback（GitHub → 镜像源 → 本地源）；契约语义边界（公开克隆契约在代理/镜像源下是否仍算覆盖）需 owner 拍板后成文

- **[arbiter:add-inte] 验证轮对网络面瞬态劣化无探针延迟重验自愈（env 失败直接烧轮进豁免握手停车）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：瞬态网络劣化把「等几小时自然恢复后重验」变成人工裁决+整轮验证预算消耗（本轮 impl 修复轮 $29 + admin run $4.2 + 验证轮与 arbiter 轮成本）；豁免握手停车频次被网络波动放大；限速窗口内立即重验还可能再烧一轮
  - 证据：验证轮 2026-11-07T15:43Z GitHub bulk 截断判 env 进豁免握手停车（.fenix/verify-progress/add-integration-test-env/judge_attribution.json + .fenix-run-result.json）；约 8.5 小时后宿主 bulk 面自然恢复（Arbiter 探针 run arbiter-add-integration-test-env-1794067782：浅克隆 44s/116MB RC=0）；现行重验前补救探针仅覆盖 dist 新鲜度面（verdict-env-exemption-handshake「重验前补救」段），无网络面探针与延迟重验窗；触发 run_id=arbiter-add-integration-test-env-1794067782（签名 add-integration-test-env::inconclusive_loop，来源 chain-handoff:escalation-alert）
  - 调查评估：触发信号 inconclusive_loop（spec=add-integration-test-env）：'add-integration-test-env' 连续 1 轮验证失败均被裁决归类 env（级二豁免握手首次命中即升级（judge 已裁决全 env），env 断言 2 条、blocked-env 场景 0 个），judge 已裁决全部失败归环境、等待人工豁免或修环境——自动重验已停止。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：verify 引擎对 env 类（网络签名）失败引入带网络探针的延迟重验窗：T+N 小时后自动 probe（浅克隆探针通过才派重验，一次为限），与豁免握手衔接（自动重验成功则免人工裁决；失败再进既有停车）；需设计自动延迟重验与人工 choices 的优先级/互斥边界，避免与 grant_env_exemption 竞态

- **[arbiter:add-inte] inconclusive 升级停车缺调度守卫（MUST NOT enqueue 承诺仅由 30 分钟退避支撑）**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：是
  - 影响：级二豁免握手/inconclusive 升级停车车道全部受影响：每次停车 30 分钟后验证轮自动重烧（预算+成本），若环境未恢复则再败再进握手+SIGNAL+Admin/Arbiter 链路重烧；「人工处置是唯一出路」的契约语义名存实亡，人工 choices 与在飞验证轮竞态（本例在飞轮结果将悬置于人工拍板之前）
  - 证据：core/pm_engine/verification/escalation.py:251-360 _escalate_inconclusive_parking docstring 承诺「升级后停止自动重验（MUST NOT enqueue verifier）——人工处置是唯一出路」，实现仅写 _dispatch_backoff_until=now+30min（注释自认用途「防 orphaned_state 误报」）；grep 全 core：_in_inconclusive_reverify 旗标消费点仅在 verification 内部（judge 预算隔离），dispatch 面无停车守卫。实测：本 spec 退避 16:17:38Z 到期后 16:19:47Z auto 重派 verifier（.fenix/logs/fenixd.log:18933 channel=auto agent_type=verifier），与 Arbiter#1 escalate 挂靠（16:18:43Z）竞态，人工裁决窗口实测仅 30 分钟。触发 run_id=arbiter-add-integration-test-env-1794068323；触发 run_id=arbiter-add-integration-test-env-1794068323（签名 add-integration-test-env::inconclusive_loop，来源 escalation-alert）
  - 调查评估：触发信号 inconclusive_loop（spec=add-integration-test-env）：'add-integration-test-env' 连续 1 轮验证失败均被裁决归类 env（级二豁免握手首次命中即升级（judge 已裁决全 env），env 断言 2 条、blocked-env 场景 0 个），judge 已裁决全部失败归环境、等待人工豁免或修环境——自动重验已停止。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：调度器派发守卫：dispatch 面对带 INCONCLUSIVE_PARKING_ERROR_MARKER（或 _in_inconclusive_reverify=True 且无 admin 放行处置记录）的 spec 跳过 enqueue（错误文案已承载判据，标记常量已存在），仅 grant_env_exemption/manual_fixed_reverify/abandon 三 choice 动作或显式 unfreeze 可解除；同时保留 _dispatch_backoff_until 的 orphaned_state 防误报原职责

- **[arbiter:add-inte] 孤儿处置生效核查无因果归属校验（状态推进冒领为处置生效证据）**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：是
  - 影响：孤儿处置收敛车道在「处置=升级移交（escalate/handoff）」形态下系统性假闭环风险：Administrator 环境核查通道 SIGNAL 被错误收口（人工三选一未发生），处置台账混入因果不符的 resolved 记录；人工 choices 告警虽仍 pending 未被吞，但 SIGNAL 收口后 AdminMonitor 不再对该 spec 做环境核查唤起，链路观感=已闭环
  - 证据：spec/knowledge/domains/admin-ops/admin-orphan-disposition-effect-check.md 设计为 fail-closed（「宁可滞留升级，不可假闭环」）且「只信外部真实状态证据」，但判据未校验状态推进与处置动作的因果归属。实测：Admin run 1794066458 处置为 escalate→handoff=arbiter（本不改 spec 状态），AdminMonitor 孤儿扫描却把调度器退避到期自然重派导致的「frozen=False status=testing」当作其生效证据，16:25:36Z 回填 resolved 并收口 Administrator 通道 SIGNAL ddaf28d7175c（.fenix/logs/fenixd.log:18967-18968，.fenix/admin_alerts.json#f08188b52aa9 evidence=『STATE frozen=False status=testing（已解冻推进）』）——与该 Admin 处置「等待人工豁免或修环境」语义相反的状态变化被采信。触发 run_id=arbiter-add-integration-test-env-1794068323；触发 run_id=arbiter-add-integration-test-env-1794068323（签名 add-integration-test-env::inconclusive_loop，来源 escalation-alert）
  - 调查评估：触发信号 inconclusive_loop（spec=add-integration-test-env）：'add-integration-test-env' 连续 1 轮验证失败均被裁决归类 env（级二豁免握手首次命中即升级（judge 已裁决全 env），env 断言 2 条、blocked-env 场景 0 个），judge 已裁决全部失败归环境、等待人工豁免或修环境——自动重验已停止。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：生效核查按处置动作形态分流判据：escalate/handoff 类处置的「生效」证据应为链上接续（Arbiter 接手记录/人工 choice 落账），而非 spec 状态推进；spec 状态推进类证据仅适用于「处置=状态动作（unfreeze/reset）」形态且需校验 Transition 的 trigger/channel 与处置动作语义一致（capability 页已有 channel/note 对账机制，收紧到逐形态匹配即可）

## 2026-11-09

### 知识真相源
- audit 语义项转写失败：duplicate（spec/knowledge/domains/knowledge-atlas/knowledge-anchor-discipline.md × spec/knowledge/domains/knowledge-atlas/knowledge-atlas-directory.md），请人工核查

## 2026-11-11

### 可改进
- **[arbiter:redesign] judge 生命周期硬上限进度感知**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：是
  - 影响：验证车道长修复链 spec（多轮 test-defect 修复 + product 修复）在接近真实收敛点时被计数冻结打断，每次冻结消耗一次 Arbiter/人工裁决成本（本 spec $40.6、judge 侧 ~18.6M input tokens）。
  - 证据：fail_history.json（第 6 轮 4 非过）→ 修复后 report.json（20/22）：6 次派发期间失败集单调收缩（18 过→20 过），冻结发生在修复刚闭环、残留失败首次真实执行的轮界；STATE _judge_rerun_count 生命周期累计不区分「有产出的修复推进」与「空转复判」。；触发 run_id=arbiter-redesign-chain-panel-ui-1794326450（签名 redesign-chain-panel-ui::judge_rerun_cap，来源 chain-handoff:escalation-alert）
  - 调查评估：触发信号 judge_rerun_cap（spec=redesign-chain-panel-ui）：'redesign-chain-panel-ui' judge 重跑超上限（6/5 轮），已冻结等待人工裁决。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：失败集严格改进（本轮失败/级联集为上轮真子集）时对 _judge_rerun_count 衰减或部分返还；或给「修复轮闭环后的首轮裁决」设一次豁免额度；或冻结告警附「失败集改进轨迹」辅助人工快速解冻决策。

- **[arbiter:redesign] fail_history cause_type 语义与裁决归因对齐**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：bug-found→impl 修复轮的派发依据与 judge 裁决语义存在偏差：修复面被放大到 4 场景（本轮 impl 自行复核纠偏未造成错误修复，但若 impl 不复核，可能对 flaky/级联场景做空修复）。
  - 证据：第 6 轮 judge 裁决（verification-report.md）：仅 1 个 product bug（BUG-01），bento 判 flaky、两队列场景判级联「非独立缺陷」；但机械 fail_history.json 将 4 个非过场景整体记为 cause_type=real-bugs/failure_class=product。；触发 run_id=arbiter-redesign-chain-panel-ui-1794326450（签名 redesign-chain-panel-ui::judge_rerun_cap，来源 chain-handoff:escalation-alert）
  - 调查评估：触发信号 judge_rerun_cap（spec=redesign-chain-panel-ui）：'redesign-chain-panel-ui' judge 重跑超上限（6/5 轮），已冻结等待人工裁决。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：fail_history 逐场景记录 judge 归因（仅 product 子集入 real-bugs），或将 failure_class 与裁决产物对齐（1 product + 3 flaky/cascade）。

- **[arbiter:redesign] 验证侧冻结告警引用报告的时点一致性**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：judge_rerun_cap 等验证侧冻结的 error 指向裁决报告时，该报告可能不含最终引擎轮现场，人工需自行发现 report.json 才能拿到最新失败明细，增加误判面。
  - 证据：STATE error 文案「详见 spec/changes/redesign-chain-panel-ui/verification-report.md」，该文件 mtime=本地 23:43（第 6 轮裁决、修复前 18/22 现场）；修复后轮引擎现场仅存于 report.json（16:00:50Z，20/22+残留失败明细）——人工按 error 指引读到滞后一轮的现场。；触发 run_id=arbiter-redesign-chain-panel-ui-1794326450（签名 redesign-chain-panel-ui::judge_rerun_cap，来源 chain-handoff:escalation-alert）
  - 调查评估：触发信号 judge_rerun_cap（spec=redesign-chain-panel-ui）：'redesign-chain-panel-ui' judge 重跑超上限（6/5 轮），已冻结等待人工裁决。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：冻结写点把最新 report.json 摘要/逐场景表附进告警 evidence，或 error 文案并列指出 report.json 路径。

- **[arbiter:redesign] arbiter escalate 后升级告警同签名复现入链即时烧配额**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：每次 Arbiter escalate 都会立即再烧一次复现配额（缺省 3 次/签名）做零变化复查：同签名最多浪费 2 轮完整 Arbiter run（墙钟约 30 分钟、成本约 4-5 USD 量级），结论必然与首次相同；告警零噪音分层被重复 run 稀释（人类看到的是重复升级而非新信息）。
  - 证据：fenixd.log 时序：16:15:20.735（attempt 1 产裁决包升级）→ 16:15:44.099（人工告警 e9cc3a192d65 创建，endpoint=arbiter-escalated）→ 16:15:44.345（「arbiter 触发入队（单飞串行）source=escalation-alert」）——arbiter-escalated 人工告警自身作为 escalation-alert 信号在 250ms 内复现入链，场景零变化即再派发 Arbiter；本 run（arbiter-redesign-chain-panel-ui-1794327344）即该复现 attempt 2 实例（attempt 1 耗时 869.9s / 2.16 USD 量级）；arbiter_ledger.jsonl chain-ev-1794327344345 与告警 created 同秒互证。；触发 run_id=arbiter-redesign-chain-panel-ui-1794327344（签名 redesign-chain-panel-ui::judge_rerun_cap，来源 escalation-alert）
  - 调查评估：触发信号 judge_rerun_cap（spec=redesign-chain-panel-ui）：'redesign-chain-panel-ui' judge 重跑超上限（6/5 轮），已冻结等待人工裁决。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：复现入链去重面增加守卫：endpoint=arbiter-escalated 且告警 pending 未人工处置时不自动复派（或要求场景变化信号才复派，如新一轮 verify report / STATE 变更 / 告警内容更新）；或将 arbiter-escalated 产物告警改为终态人工包形态（不再作为链触发源）。方向供自进化立项裁量。

- **[arbiter:redesign] 冻结场景描述与实现传输通道漂移无守卫（alert-resolve ?project 措辞陈旧）**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：影响验证裁决面：judge 定性轮、场景修复轮与人工裁决包读者都可能沿陈旧描述向错误方向归因（多烧修复预算或误判 product-bug）；场景描述自带「路径出处」锚点机制但不含传输形态类实现细节的新鲜度约束，漂移静默存在。
  - 证据：test_scenarios.json 中 w-queue-exec-ack-self-heal 描述声称「断言裁决请求打 /api/alert-resolve?project=rcp-chain-showcase」，但实现已收敛为 body 通道（dashboard.ts:675-682，code-review item 7045ef4ae4c7 收敛旧 ?project= 双通道；alert_routes.py:539-583 query 优先/body 兜底/缺项目 400）；官方轮捕获样例亦为裸 URL（含 body）。本次 Arbiter 复查中该措辞险些引导出一条假 product-bug 机制（前端丢参致服务端失配），经代码面核查方排除。；触发 run_id=arbiter-redesign-chain-panel-ui-1794332909（签名 redesign-chain-panel-ui::judge_rerun_cap，来源 startup）
  - 调查评估：触发信号 judge_rerun_cap（spec=redesign-chain-panel-ui）：'redesign-chain-panel-ui' judge 重跑超上限（6/5 轮），已冻结等待人工裁决。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：候选方向：①场景描述 freshness 守卫——描述中出现的 URL/参数形态断言词与当前实现做静态比对（沿用既有「路径出处」锚点思路扩展到传输形态词），漂移即在 verify 预检或 repair 轮提示刷新；②端点传输通道类 code-review item（如 7045ef4ae4c7）落位时联动扫描引用该端点的冻结场景描述并触发描述刷新（复用场景修订处置出口）；③最低成本：在场景描述契约中把「请求形态措辞」降级为非断言性叙述，断言一律以 steps.network_assertions 单源为准，消除双源漂移面。

- **[arbiter:add-plat] 修复轮裁剪重验缺验证实例隔离（主树裸跑撞 merge-back 瞬态假失败）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：所有走 scenario-repaired 修复轮裁剪重验（及同缝的其他主树裸跑重验路径）的 SPEC：重验窗口与任意车道 merge-back/autostash 并发时，源码锚位类契约测试（inspect.getsource 按 co_firstlineno 切磁盘文件）确定性瞬态假失败——假失败驱动 judge 重跑，消耗生命周期累计硬上限预算，最终以 judge_rerun_cap 假冻结收场（本次即实例）。危害形态：预算被环境噪声烧穿、验证收敛被延迟、人工/arbiter 处置成本。
  - 证据：daemon 日志 18:07:26Z 重验启动无 worktree 创建行（judge#1-#5 轮均有 worktree 创建/清理日志对）；18:11:15.270-526Z code-fix-1794332918 车道对主树 Autostash→Merged→Stash popped 与 runner.py mtime 18:11:15.374Z 秒级吻合；report.json 中 full-regression 的 5 组 inspect.getsource 锚位断言摘录全部错位到相邻函数；主树稳态复跑 2 passed。两源（日志时序 + mtime/复跑）互证。；触发 run_id=arbiter-add-platform-abstraction-layer-1794334845（签名 add-platform-abstraction-layer::judge_rerun_cap，来源 chain-handoff:escalation-alert）
  - 调查评估：触发信号 judge_rerun_cap（spec=add-platform-abstraction-layer）：'add-platform-abstraction-layer' judge 重跑超上限（6/5 轮），已冻结等待人工裁决。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：①修复轮重验（scenario-repaired 重入执行路径）复用首轮验证的 worktree 隔离语义（与 judge run 同缝创建/清理）；②重验启动前探测主树 merge-back 在飞信号（worktree_manager merge 锁/日志边沿）短暂挂起；③全量回归类场景的源码锚位断言失败时自动做一次稳态复跑（如 sleep 后重测或对比 merge-base 状态）再定 fail。

- **[arbiter:add-plat] judge 生命周期累计硬上限与场景原地修复重入的结构性互掐（复裁派发注定撞墙）**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：探针债务集中型 SPEC（首轮大面积 test-defect）即使修复路径完全健康，也会在复裁步被硬上限假冻结，白名单③之外的自动化无法续走，每次都产生一轮 arbiter/人工处置成本；硬上限「防异常循环」的设计意图与「正常收敛耗尽」的真实形态混同。
  - 证据：本 spec 生命周期 5 次真实派发全为正常修复收敛（14→4→3→2→1，_scenario_repair_exhausted_rounds=0、拒收 0 轮）；judge#5 修复被采纳后重入的复裁派发是管线必经步骤（日志 18:06:55 采纳→18:07:26 重执行→18:20:45 [阶段3] 复裁），但生命周期累计 6>5 在派发门无条件拦截——即无论重执行结果如何，第 6 次派发必然撞墙冻结。冻结告警附的修复预算上下文（未耗尽）无法区分「异常重入循环」与「正常修复收敛的资源耗尽」。；触发 run_id=arbiter-add-platform-abstraction-layer-1794334845（签名 add-platform-abstraction-layer::judge_rerun_cap，来源 chain-handoff:escalation-alert）
  - 调查评估：触发信号 judge_rerun_cap（spec=add-platform-abstraction-layer）：'add-platform-abstraction-layer' judge 重跑超上限（6/5 轮），已冻结等待人工裁决。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：①scenario-repaired 重入的复裁派发改计入（spec, 验证轮）轮内计数（judge-rerun-governance 已有轮内阈值 2 先触发升级），不再烧生命周期累计预算；②硬上限派发门拦截前检查最近一轮裁决产物：若分类计数已收敛到 test-defect=0 且 product-bug=0（或仅剩已修复申报场景），放行最后一次复裁派发并告警留痕；③冻结告警 evidence 增加「最近一轮裁决收敛度」字段（上轮 vs 本轮失败数趋势），供裁决者直接判断是否正常收敛。

## 2026-11-12

### 浪费
- **stale悬空强制重启硬杀全仓审查run，106分钟作废覆盖延迟一天**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：是
  - 影响：一次全仓代码审查 run 跑了 106 分钟、694 轮后被排水硬杀，已完成 6/21 波（170/352 文件），剩余约 182 个文件的审查覆盖延迟约 22 小时才由续跑接管；这是本窗 6 次计划内重启中唯一一次杀到在飞 run（其余 5 次 drain 均为 0 秒空排水），交付零损失（已落盘分片保全）。
  - 证据：日志 17:47:29Z 告警 591f9f54784a（stale_code_dangling_timeout，陈旧悬空超时升级告警）自述「不再等待空闲、直接触发规划性重启」，17:47:31 Shutting down，17:48:24「Drain finished after 50s, remaining runs: ['code-review-1794326531']」同秒向该全仓周期审查 run 发 SIGTERM；其档案（.fenix/runs/archive/code-review-1794326531.jsonl）末三行依次为 interrupted(reason=daemon shutdown)、run_metrics(duration_s=6373.2、turns=694、Read=318/Bash=329)、error「Exit code: 143」（exit 143 成批=排水屠杀签名）；终态抢救文件 terminal-salvage-code-review-1794326531.txt 记「第六波完成（累计 170/352）」，21 个波次分片 out-*-b01..b21.jsonl 已直写落盘；续跑 code-review-1794412954 于窗口末 15:59Z 启动，其 manifest 的 redispatch_of 字段指回被杀 run。
  - 调查评估：在 code-review 车道夜间全仓审查（scheduled 周期审查）暴露。已核实事实：daemon 进程 08:36:50Z 前启动，09:47Z 主树 merge（提交 e4856d537，fix-legacy-test-failures 分支合入）动 core/ 后持旧，此后约 8 小时常规空闲自愈未获触发（该链含 300 秒空闲边沿与 1800 秒合流闸多级条件，具体为何未触发未逐项核实），至 17:47:29Z 悬空超 max_dangling_seconds（缺省 14400 秒即 4 小时，core/config.py:2760）被强制重启。根因与 2026-11-04#浪费#2、2026-11-05#浪费#1 同族：交付密集日每个动 core/ 的 merge 都让 daemon 变旧，重启必然撞上在飞 run；本窗新形态是 dangling 强制重启（设计上「不再无限等待空闲」），50 秒排水窗对 106 分钟的审查 run 结构性等不到收尾。与存量关系：11-04 窗建议（排水窗对齐 LLM 轮长 ≥300 秒、在飞 run 落 WIP checkpoint 再停、重启触发加在飞闸门）至今未立项，spec/changes/ 活跃区无承接 spec（本窗复核）；缓解面已有两道——波次分片直写落盘使 6 波发现保全、redispatch_of 续跑机制存在，把损失从「全废」收敛为「覆盖延迟」。结论：第四窗复发证实敞口稳定，属系统性缺口非一次性失误；code-review 车道被杀后需等整日调度节拍才续跑，覆盖空窗是该车道特有的加重因子。
  - 建议：重申 11-04 建议并补车道特有项：①agents.run_drain_max_seconds 提到 ≥300 秒；②dangling 强制重启前对在飞 run 落 WIP checkpoint（复用 drain-preserve 机制）再杀；③code-review 车道对被排水硬杀的全仓审查增加即时 redispatch（复用 push-retry-recovery 式周期扫描消费通道），不等下个夜间调度节拍，把剩余覆盖空窗从 22 小时压到分钟级。

- **API停滞第五窗23run合计约174分钟，聚合出口缺口五窗未落地**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：窗口内 23 个 run 累计 API 停滞（单轮 API 往返超 60 秒的等待段）约 10442 秒 ≈ 174.0 分钟纯墙钟等待，为五窗序列 92→370→175.5→210.1→174.0 的低位持平；零失败零金额损失，损失面全在墙钟，最重单 run planner-plan-redesign-chain-panel-ui（出题车道）停滞 1824.7 秒、最长单轮 352.6 秒。
  - 证据：数据摘要第 6 节 23 行 api-stall 聚合行相加得 10442.0 秒（终态指标行无 total 字段，按聚合行口径转引，与前三窗同口径）；抽 3 个档案终态 run_metrics 原值核对吻合：planner-plan-redesign-chain-panel-ui-1794364608-a1 stalls=9/max=352.6、impl-add-adjudication-auto-exec-1794367334-a1 stalls=8/max=232.7、evo-1794334713 stalls=6/max=236.1；窗口内 19 条 admin 告警中 api_round_stall_escalated（API 停滞升级信号）零出现——23 个停滞 run 全部 success 终态，被升级面 success 豁免放行（有意设计）。
  - 调查评估：在出题/实现/评审/admin/code-fix/evo 六车道普遍暴露。已核实事实：合计按聚合行口径相加、抽样与档案原值吻合；升级信号面无信号是 success 豁免使然（monitor-escalated-signal-negative-controls 修复的有意设计，2026-11-04 窗已核实），非接线缺口。根因未定、多假说并存（网关排队/长上下文/本地网络，2026-11-02-evo-add-api-stall-disposition-closeout 归档留痕口径），不预设。与存量关系：cost-observability 域 api-stall-observability 能力页现行文本仍为「纯读侧不干预」（本窗复核）；「连续两窗合计超 150 分钟即做 model 对照与收敛试验」的触发条件自 11-05 窗起持续成立，本窗两窗合计 210.1+174.0=384.1 分钟，第五窗仍无承接机制（cost-observability 域无聚合出口页、spec/changes/ 无对应 spec）。结论：持续摩擦非失控，观测闭环、聚合出口缺口第五窗，属既有建议落地拖延。
  - 建议：落 cost-observability 域聚合出口：连续两窗合计超 150 分钟时按 run_metrics 的 model 字段（本窗抽查 run 均为 glm-5.3-flash、字段齐备）出模型版本对照报告并做提示词/provider 路由收敛试验，替代逐窗人工对账；可与纯文本轮通胀响应共用一个小 spec（同数据源 run_metrics）。

### 失误
- （当日无）

### 可改进
- **daemon_errors升级面无可自愈豁免，WIP重叠重试ERROR误报重启建议**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：是
  - 影响：merge-back（实现分支合回主树）被 WIP 重叠闸门拦截期间的重复 ERROR（precheck 检查以 25-120 秒重试节奏共 4 条）被 daemon_errors 升级面判为「10 分钟窗口内复现 2 次」成 critical 告警并建议重启 daemon——该事件 7 分钟后被周期消费者自动合回自愈，重启建议零必要；若按建议重启还会硬杀当时唯一在处置的 admin run，属人工面噪音加误导 triage 的双重敞口。
  - 证据：告警 95dd9ded5c5b（daemon_errors critical，指纹 5406fd44，「10 分钟窗口内复现 2 次，建议检查根因并重启 daemon」，04:11:53Z 创建，至今 handled=False 留噪音）；ERROR 源为 worktree_manager「Merge-back blocked by WIP overlap precheck (policy=escalate)」04:11:13Z 与 04:11:38Z 两条（同一次合回的重试、间隔 25 秒）；闭环记录 c836b596ba9e（处置记录，「周期消费者 merge-only 重试成功…自动合回，无需人工处置」，04:18:12Z）；源码 core/admin_monitor.py:5065 _detect_daemon_errors 的豁免面仅有重启冷却窗、同轮孪生指纹合并与跨日同刻判别，无可自愈链路 ERROR 的签名豁免（本窗复核）。
  - 调查评估：在 add-adjudication-auto-exec 实现分支合回主树时暴露。已核实事实：ERROR 原文、告警原文、自动合回闭环记录、源码豁免面逐一度核。根因：daemon_errors 判据是纯形态级（同指纹+频次+间隔），不区分「daemon 自身故障」与「框架自愈链路的过渡态记录」——WIP 重叠 precheck 的 escalate 拦截属 wip-defer-merge-retry（WIP 阻断延迟合回，等待标志+周期自动合回）治理链的设计内中间态，自带重试与周期自动消费者，落 ERROR 行只是留痕。与存量关系：2026-11-06#可改进#1 同族（promotion lint 声明类双失败触发同类 critical 误报），其建议只点名声明类 lint、未覆盖 merge-back precheck 形态；「同 run 重试≠风暴」的判读法已入处置实践（本窗 admin 处置记录 b6e5a9c74081 即按 evidence 归属 spec 并被在飞 run 覆盖待重评），但停留在人工判读层，框架升级面未收紧。结论：判据缺口明确、同族第二例，critical 文案「建议重启 daemon」对该形态系统性误导，适合小 spec 治本。
  - 建议：二选一或并用：①daemon_errors 升级面为「带已知自愈消费者的 ERROR 签名」增加豁免名单（merge-back precheck policy=escalate、promotion lint 类），名单单源配置并注明各自的自愈消费者；②在 ERROR 源头（worktree_manager precheck）把重试窗口内的重复拦截改为同指纹聚合日志（同 run 重试不重复落 ERROR 行），从源头消除复现计数。

- **纯文本轮通胀第五窗扩散到admin/arbiter车道，响应端仍缺席**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：是
  - 影响：4 个 run 命中纯文本轮离群维度（轮数>100 且纯文本轮占比>50%，纯文本轮=无工具调用的模型回复轮）：admin 车道 105 轮中 65 轮（61.9%）、arbiter（自主裁决）车道 123 轮中 67 轮（54.5%）、planner-judge 车道 102 轮中 56 轮（54.9%）、planner-plan（出题）车道 244 轮中 135 轮（55.3%）——admin 与 arbiter 车道为首次命中，命中面从 planner 双车道扩散到四车道；复发敞口为每窗多烧一轮演化复核注意力（历史实测曾白跑一轮复核）。
  - 证据：四 run 终态 run_metrics 原值逐字段核对吻合（text_turns 65/67/56/135，model 均为 glm-5.3-flash，admin run admin-add-adjudication-auto-exec-1794370313 时长 931.1 秒）；检测 spec evo-refine-midflight-outlier-dims（离群维度细化）已归档于 spec/archive/2026-11-04-，三项交付均为观测端、无响应端定义；本窗复核 cost-observability 与 agent-runtime 两域均无响应端能力页、spec/changes/ 无承接 spec。
  - 调查评估：命中面跨四车道。已核实事实：占比、轮数与 model 字段按摘要+档案双源核对一致。根因未定（模型输出行为漂移假说，检测 spec 原文口径），token 面不可量化（该批 run 的 input_tokens=0 计量缺失）。与存量关系：planner-plan 车道已四连窗命中（11-04 一 run→11-05 三 run→11-06 两 run→本窗一 run），planner-judge 第二窗，「同车道连续两窗命中即按 model 字段做对照与提示词收敛试验」的触发条件自 11-05 起成立至今五窗，属建议落地拖延非新缺口；本窗新增信息是同一模型扩散到 admin/arbiter 两个处置链车道——二者提示词分属不同模板，扩散形态提示收敛对象可能在共享层（模型行为或公共提示词片段）而非单车道模板。结论：观测闭环后响应端落地时机已过四窗，命中面还在扩大，不应再观察。
  - 建议：落最小响应机制（与 API 停滞聚合出口同一小 spec 承接，同数据源 run_metrics）：按 model 字段出四车道对照报告，先对四连窗重灾区 planner-plan 做提示词收敛试验（如压缩逐轮叙述性输出指引），admin/arbiter 两车道留痕至第二窗命中后纳入；同时补 run_metrics 的 input_tokens 计量缺失面以支撑量化。

- **[arbiter:consolid] 纯归因拒收悬置态被 Recovery 重驱动复判直至硬上限伪冻结**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：所有「修复预算耗尽+申报拒收保持 testing」的 spec 都会在悬置约 13 分钟后被重驱动：复判必然复现同一未修复失败面，每轮烧一次全量验证与 judge 计数直至 6/5 冻结——judge_rerun_cap 冻结与人工裁决包被伪触发，裁决上下文污染（看似 judge 无进展循环，实为机制打架）；本次即实例（第 6 轮 fast-track 复判直接触顶）。
  - 证据：fenixd.log 04:38:33Z 受理门拒收（「保持 testing」=知识页 judge-repair-budget-alignment rev=2 明文的设计内无驱动悬置）→ 04:51:27Z event_bus「Recovery: re-triggering verify for undriven testing」直接重驱动验证 → 04:53:02Z rerun 6/5 硬上限冻结。两源互证：daemon 日志 × 知识页「纯归因收尾后车道不再调度任何后续驱动——不重验入队、不派发、不升级」口径。Recovery 的 undriven-testing 判定未豁免拒收悬置形态。；触发 run_id=arbiter-consolidate-alerts-to-ops-page-1794459182（签名 consolidate-alerts-to-ops-page::judge_rerun_cap，来源 chain-handoff:escalation-alert）
  - 调查评估：触发信号 judge_rerun_cap（spec=consolidate-alerts-to-ops-page）：'consolidate-alerts-to-ops-page' judge 重跑超上限（6/5 轮），已冻结等待人工裁决。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：Recovery 的 undriven-testing 探测豁免拒收悬置态（鉴别特征沿用知识页四项：error=拒收留痕文案 + rerun 触顶 + judge run 已归档 + verify-progress mtime 停在轮末）；或 Recovery 重驱动前查 _scenario_repair_exhausted_rounds≥1 且 error 含拒收文案时改走「唤起 Administrator 零动作结案」而非直接 re-trigger verify。

- **[arbiter:windows-] knowledge 测试基线存量簇修复（36 存量+11 顺序污染，8 文件）**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：所有带全量回归门（linux-zero-change-full-regression 型 zero-change 场景）的 SPEC 验证轮都会撞同一 47 项失败面，judge 全 env 裁决后逐一停车等人工豁免——豁免握手沦为基线腐烂的常态化绕行通道，每个含全量门的新 SPEC 都要烧一次人工裁决；11 项顺序污染（单跑通过、全量挂）持续掩盖真实通过率并放大失败面
  - 证据：.fenix/verify-evidence/windows-native-support/72-baseline-comparison.md（47 项分布与 main 2f0115801 同簇复现实测）；本 arbiter run 独立复测 pytest tests/test_knowledge.py → 13 failed, 72 passed（9.23s）；Admin 实测 .fenix/todo.md 无该基线簇登记项；触发 run_id=arbiter-windows-native-support-1794491896（签名 windows-native-support::inconclusive_loop，来源 chain-handoff:escalation-alert）
  - 调查评估：触发信号 inconclusive_loop（spec=windows-native-support）：'windows-native-support' 连续 1 轮验证失败均被裁决归类 env（级二豁免握手首次命中即升级（judge 已裁决全 env），env 断言 2 条、blocked-env 场景 0 个），judge 已裁决全部失败归环境、等待人工豁免或修环境——自动重验已停止。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：立项两条线：a) 测试隔离修复——排查 knowledge 系 fixture/全局态泄漏（11 项顺序污染的根因形态）；b) 36 项存量断言逐项定性（test-defect 修断言 vs product-bug 修实现，首败形态为纯逻辑断言如 r['committed'] False）；可一并评估全量回归门的存量基线对账机制（对比 merge 前基线而非绝对全绿），避免零变化 SPEC 被存量缺口扣押

- **[arbiter:windows-] admin 直派通道越界执行人类专属 choice（grant_env_exemption）**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：是
  - 影响：所有 auto-invoked admin_monitor 直派通道都可能自动执行人类专属的状态推进/质量豁免/预算/弃单动作（state-advance/terminal 档），与「豁免不得自我批准」及人类拍板专属设计直接冲突；本次已实际发生，形成未经人类追认的 env 豁免并让 spec 可自动 verified。
  - 证据：core/dashboard/data/adjudication_choices.py:587-595 将 grant_env_exemption 列入 ADMIN_CHAIN_EXCLUDED_CHOICE_IDS（人类专属）；core/pm_engine/escalation_chain.py:1176-1199 只在链路径做越界复核并转单 Arbiter；admin_monitor 直派路径无该复核，agents/administrator.md:130-133 与 prompt_builder 对非链派发表述为「处置面不受限」。实证：2026-11-12T14:08:51Z 直派 run admin-windows-native-support-1794492108 以 choice_id=grant_env_exemption 落 dispositions #de43f365243d/#5c74f1a2f00c/#eb0afd742714，STATE _env_exemptions 随之写入（daemon 日志 14:08:51Z 同链）。；触发 run_id=arbiter-windows-native-support-1794492545（签名 windows-native-support::inconclusive_loop，来源 escalation-alert）
  - 调查评估：触发信号 inconclusive_loop（spec=windows-native-support）：'windows-native-support' 连续 1 轮验证失败均被裁决归类 env（级二豁免握手首次命中即升级（judge 已裁决全 env），env 断言 2 条、blocked-env 场景 0 个），judge 已裁决全部失败归环境、等待人工豁免或修环境——自动重验已停止。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：把 ADMIN_CHAIN_EXCLUDED_CHOICE_IDS 复核下沉到执行机器 execute_choice_for_disposition/execute_adjudication_choice（按 actor/通道传参区分链上 Admin 与直派 Admin，或将直派 Admin 也纳入同一排除集）；或在 admin_monitor 直派执行前加同一白名单门并为越界 choice 落 handoff=arbiter；补守卫测试覆盖「直派通道 × 人类专属 choice」矩阵。

- **[arbiter:windows-] warning_stale_triage 裁决桶缺失**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：是
  - 影响：所有 warning_stale_triage 信号的处置无结构化出口：triage 结论无法留痕收口、场景修复载荷路径（revise_scenario_reverify）不可达，同类信号反复空转烧链上配额
  - 证据：core/pm_engine/verification/escalation.py:1128（_warning_stale_triage_alert 信号写入）但 core/dashboard/data/adjudication_choices.py 注册表无该 signal_type 的裁决桶：admin run admin-windows-native-support-1794495887 只能借用 ack_self_heal 收口，被 adjudication-choice-scope-guard 判「choice 越界（人类拍板面专属）」转单 Arbiter（本 run 即该转单），每轮复发烧一条 admin run + 一条 arbiter run；admin 处置记录 suggested_choice 已同此建议（id dda29de79b6e）；触发 run_id=arbiter-windows-native-support-1794497491（签名 windows-native-support::warning_stale_triage，来源 chain-handoff:escalation-alert）
  - 调查评估：触发信号 warning_stale_triage（spec=windows-native-support）：'windows-native-support' 以下场景连续多轮均为 warning，需人工 triage 甄别是否真缺陷被悬置：linux-zero-change-full-regression（连续 2 轮）。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：按 admin 建议注册桶：①ack_triage（triage 结论留痕并收口信号，不触状态机，spec_scoped）；②桶内纳入 revise_scenario_reverify（requires_payload 不变），使场景门失效类信号可经结构化载荷走既有成对写回+证明器校验通道，替代本次的 admin 直修通道

## 2026-11-13

### 可改进
- **[arbiter:windows-] 升级链 deferred-resume 复活派发不重检让位对象收口态**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：每次链头让位（yield_to）且让位对象在让位窗内完成收口的场景，复活派发都会对已收口对象再烧一条 admin run（配额、费用与时延），且冗余 run 若误执行 choice 会对重派中的 spec 产生二次扰动（本次 menu 含 grant_env_exemption/abandon 两个高危误执行面）；同签名复现时与 arbiter 再入配额叠加放大空转
  - 证据：.fenix/logs/fenixd.log 15:51:52.965Z「升级信号入处置链（链头 Admin）: sig=windows-native-support::inconclusive_loop source=chain-deferred-resume:escalation-alert」+ 15:51:53.018Z「Deferred chain item resumed: chain_id=chain-1794498224984-71b6edf8 yield_to=admin-windows-native-support-1794497512」；同链创建于 15:43:44Z（与本 arbiter run 同秒）后让位给在飞 admin-1794497512，该 admin 已于 15:49:34Z 执行 revise_scenario_reverify 清停车（STATE updated 15:49:34Z status=testing、_in_inconclusive_reverify=False），复活路径仍按原派发 15:51:53Z 派出链头 admin-1794498713，其 pending 处置 078746faf2c4 推荐菜单仍是针对已不存在的停车的三选一（admin_alerts.json 两源互证）；触发 run_id=arbiter-windows-native-support-1794498224（签名 windows-native-support::warning_stale_triage，来源 escalation-alert）
  - 调查评估：触发信号 warning_stale_triage（spec=windows-native-support）：'windows-native-support' 以下场景连续多轮均为 warning，需人工 triage 甄别是否真缺陷被悬置：linux-zero-change-full-regression（连续 2 轮）。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：deferred-resume 恢复路径在派发链头前重检让位对象的处置结果（读其 disposition/终态记录与 STATE 底层字段，如 _in_inconclusive_reverify/error 停车现场已清即取消链并静默收口源信号）；或将让位对象收口事件作为链取消信号注入链痕协调单源；守卫测试覆盖「让位窗内收口 → 复活应取消」矩阵

## 2026-11-14

### 浪费
- **bigmodel 429限流连杀4run，约35美元报废**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：bigmodel.cn 429 账户级速率限制（错误码 1302「您的账户已达到速率限制」）在一小时内连杀 4 个 run attempt，合计约 4.1 小时 run 时长与 34.9 美元成本报废；编排层候选环换道 deepseek 后全部救回，交付零损失。重述 2026-11-12#浪费#2 关联形态（新根因亚型）。
  - 证据：两个 judge 复核 run（planner-judge-windows-native-support-1794499508-a1 609 秒 1.41 美元、1794503523-a1 188 秒 0.54 美元）档案尾部各 2 次 api_retry error_status=429 耗尽后接 model=「<synthetic>」占位消息与 error「Exit code: 1」；进化复核 run evo-1794500754 首段 266 轮 2261 秒 12.07 美元后 result 行原文「API Error: Request rejected (429) · [1302]…」，换道 deepseek 二段 512 轮 532 秒成功；实现 run impl-windows-native-support-1794474838-a1（跨窗边界，自查告警 16:01:53Z 落窗内）624 轮 8466 秒 20.88 美元死于 429；fenixd.log 三条 provider switched（16:15:35Z、17:03:35Z 候选环 429 换道、17:15:31Z）。
  - 调查评估：在 windows-native-support 收尾冲刺期（本地 00:15-01:15 实现/裁决复核/进化多车道并发）暴露。已核实事实：4 个 attempt 的 429 事件数、成本与时长逐一度核，429 响应文本自证账户级速率限制——根因确定为「收尾期多车道并发打满同一 provider 账户配额」，属确定性归因，与既往 API 停滞条目的「网关排队/长上下文/本地网络」多假说口径不同类。编排层按设计工作：车道候选环与重派换道全部救回（judge a2、evo 二段均 deepseek-flash 秒级收尾），provider-models 域候选链 failover 与瞬断治理已覆盖换道面。与存量关系：既往条目未覆盖「429 确定性限流」亚型（此前停滞均按未定假说留痕）；实损集中在「每次都烧满 api_retry×2 整轮才在重派时换道」的形态，收尾密集期复发敞口高。结论：救回链有效、零交付损，浪费形态确定且可防。
  - 建议：429 形态（error_status=429）在 run 内首次命中即触发候选环换道评估，不等 api_retry 耗尽整轮报废；收尾密集期对同一 provider 的多车道并发设软上限或派发面错峰（可与 provider-models 域瞬断治理顺带落地）。

- **API停滞第六窗回落至47.7分钟，聚合出口仍缺席**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：窗口内 10 个 run 累计 API 停滞（单轮 API 往返超 60 秒的等待段）约 2861 秒 ≈ 47.7 分钟纯墙钟等待，为六窗序列 92→370→175.5→210.1→174.0→47.7 的最低位，较上窗回落 73%；零失败零金额损失。重述 2026-11-12#浪费#2（好转）。
  - 证据：数据摘要第 6 节 10 行 api-stall 聚合行相加得 2861.0 秒（终态指标行无 total 字段，按聚合行口径转引，与历窗同口径）；抽 3 个 run 终态 run_metrics 原值核对吻合：evo-1794507222（进化复核 run）stalls=4/max=170.4、planner-judge-windows-native-support-1794499508-a1 stalls=4/max=179.9、admin-fenixd-1794564788（主树散件 WIP 处置 run）stalls=3/max=106.6；单轮超 300 秒升级线的 run 为零，窗内 api_round_stall_escalated（API 停滞升级信号）告警零出现，两相吻合。
  - 调查评估：六车道普遍暴露但量级大幅回落（上窗 23 run 174 分钟→本窗 10 run 47.7 分钟）。已核实事实：合计按聚合行口径相加、3 run 抽样与档案原值逐项吻合；本窗最长单轮 179.9 秒，历史首次整窗无超 300 秒升级线样本。回落与 429 限流并发存在时间重叠，部分停滞或为 429 重试等待的前兆面（两条目相关但根因不同，不合并归因）。与存量关系：cost-observability 域 api-stall-observability 能力页现行口径仍为「纯读侧不干预」（本窗复核），「连续两窗合计超 150 分钟做 model 对照与收敛试验」的聚合出口建议连续第六窗未落地、spec/changes/ 无承接。结论：持续摩擦显著缓解，出口缺口降级为低优先，建议调整触发口径避免在下行走势上机械立项。
  - 建议：维持出口建议但改触发口径：停滞合计连续回升两窗（而非仅绝对值过线）时再按 run_metrics 的 model 字段出对照报告与收敛试验；本窗下行走势先留痕一窗。

- **dangling强制重启本窗再触发，0秒空排水零实损**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：stale_code_dangling_timeout（daemon 持旧代码悬空超时的强制规划性重启信号）本窗再触发一次：持旧 28954 秒（约 8 小时）超 max_dangling_seconds 28800 秒时限后强制重启；本次排水窗恰无在飞 run（0 秒空排水），零 run 被杀零实损——零损失纯靠时机，非守卫生效，「重启撞在飞 run」敞口原样保留。重述 2026-11-12#浪费#1（同族新实例，本窗零实损）。
  - 证据：告警 stale_code_dangling_timeout（17:38:22Z，warning）与日志三连逐一度核：「持旧代码已 28954s 超过 28800s 且不再等待空闲，已 touch .fenix/restart_request」→「Shutting down...」→「Drain: planned restart, drain window 50.0s, waiting runs: []」5 秒内完成，无任何 SIGTERM 行；对比上窗同链路杀掉 106 分钟全仓审查 run（50 秒排水未等到收尾）。
  - 调查评估：在 daemon 托管链暴露：当日 core/ 交付后 daemon 持旧约 8 小时，常规空闲自愈链未获触发，最终由 dangling 时限强制兜底。已核实事实：告警原文、持旧时长、排水 0 秒、无在飞被杀逐一度核；排水窗仍为 50 秒原值，与 LLM 单轮 API 往返常态 60-180 秒的结构性失配未变。与存量关系：2026-11-12#浪费#1 的三项建议（排水窗 ≥300 秒、强制重启前在飞 run 落 WIP checkpoint、code-review 被杀后即时 redispatch）至今未立项，spec/changes/ 活跃区无承接（本窗复核）；本窗是同族第四窗复发，本窗零实损仅因重启落在车道间隙。结论：敞口稳定，属系统性缺口非一次性失误，本次结果不可复制。
  - 建议：重申 2026-11-12#浪费#1 建议立项：agents.run_drain_max_seconds 提到 ≥300 秒；强制重启前对在飞 run 落 WIP checkpoint（复用 drain-preserve 机制）再杀；code-review 车道被排水硬杀后即时 redispatch 不等夜间调度节拍。

### 失误
- （当日无）

### 可改进
- **429死亡run被收尾链记success，幻影成功3例**
  - 自进化：问题部分成立 / 建议不合理 / — 不需要
  - 影响：3 个死于 429 的 run（1 个实现 run 624 轮 2.35 小时、2 个裁决复核 run）被 daemon 收尾链记 terminal=success，窗内 runs 统计「失败: 0」失真；框架自查信号 self_review_phantom_failure（自省分类疑幻影失败）窗内 3 连发留人工核对，无自动重定性动作。复发敞口：每次 429 死亡都会污染成功统计并烧一轮人工核对注意力。
  - 证据：三条自查告警（16:01:53Z impl-windows-native-support-1794474838-a1、16:03:19Z 两个 judge run 同秒成对）原文「按产物侧归因（Exit code: 1）判 failed，但 daemon 侧 run_metrics terminal=success——不计入失败统计，请人工核对分类器是否仍有漏网」；两个 judge run 档案尾部形态一致：api_retry error_status=429 两次耗尽 → model=「<synthetic>」占位 assistant 消息 → result 行（成本已计 1.41/0.54 美元）→ error「Exit code: 1」，daemon 收尾链按 result 行存在记 success。
  - 调查评估：在 windows-native-support 验证/实现收尾链暴露，由自省分类器自查面捕获。已核实事实：三 run 的 429 事件与「合成消息+result 行+非零退出」收尾形态逐一度核；judge 链的重派（a2）正常发生，说明产物级重派判定与 run 级 success 分类并存、重派未受影响。根因：收尾分类以「result 行存在」为主判据，未交叉核验 exit_code 与尾部 synthetic 标记，产物侧失败被记账面吞掉；自查信号已按设计捕获并豁免失败计数（负控面工作正常），但信号止于留人工核对、不回写终态。与存量关系：run-resilience 域失败分类与错误归因降噪能力页未覆盖「CLI 合成收尾」形态；CLI 退出码与 result 行分叉此前以「已知 CLI 启动噪声」口径带过，本窗实锤为 429 死亡的系统性形态（3/3 同型）。结论：观测已闭环（信号+豁免双保险），缺口在收尾分类的终态写点，确定性可修。
  - 建议：收尾链对「exit_code≠0 且尾部 assistant 为 <synthetic>」的 run 改记 failed（或 partial），使失败统计与幻影识别不依赖自查信号兜底；self_review_phantom_failure 信号降级为回归守卫。

- **spec_amendment双告警唤起admin并发处置**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：windows-native-support 的 spec_amendment_inflight（主树 spec 目录在实现分支在飞期间被修订的观察型预警）两条不同指纹告警在 18 秒内先后唤起两条 admin run，并发处置同一主题约 3 分钟，结论完全相同——重复约 8 分钟 run 时长与双份处置劳动；若两条 run 结论分歧会对同 spec 形成二次处置扰动，属竞态风险面。
  - 证据：两条处置终态日志「处置终态（result=resolved）已回写信号 handled=true」分别指向告警 c837797b2022 与 42f1ed95c621（均为 spec_amendment_inflight）；两 run 档案 span 重叠：admin-windows-native-support-1794503555（17:12:35→17:15:55Z，9 轮）与 admin-windows-native-support-1794503573（17:12:53→17:17:27Z，11 轮）；两告警指纹不同（d686660e6ab1 1 个修订 / 9a08ceaed5c8 2 个修订）系指纹机制设计内行为（提交集变化即新指纹）。
  - 调查评估：在 windows-native-support 收尾期暴露：验证修复轮在主树提交 spec 文档修订（0e0c67d68、8e712ff69）恰逢实现分支在飞，观察型预警两次成条。已核实事实：双 run span 重叠 3 分钟、两条 handled 回写、两告警指纹差异逐一度核；指纹去重按 spec-amendment-watch 能力页设计工作（同提交集合不成条，窗内无同指纹重复），缺口在唤起侧——「同 spec 已有处置中 admin run」时第二次唤起未让位、未合并、未去重。与存量关系：2026-11-13#可改进#1（升级链 deferred-resume 复活派发不重检让位对象收口态）同族——同属 admin 唤起协调面缺状态重检，本窗实例是「唤起侧并发」形态，补齐该条目未覆盖的半边；处置结论一致零损害（两者均定性观察型预警、风险已自然消解）。结论：本窗代价小（约 8 分钟重复劳动），但双 run 真并发实锤了竞态敞口，与 11-13 条目合并立项最小。
  - 建议：admin 唤起入口加同 spec 在飞守卫：已有处置中 admin run 时第二次唤起改登记关联或让位等待；与 2026-11-13#可改进#1 的复活重检合并为「admin 唤起协调守卫」小 spec（唤起前重检在飞与收口态两个方向），守卫测试覆盖「并发唤起×复活」矩阵。

- **纯文本轮通胀扩散到impl车道，响应端仍缺席**
  - 自进化：问题部分成立 / 建议合理 / — 不需要
  - 影响：本窗仅 1 个 run 命中纯文本轮离群维（无工具调用的模型回复轮，轮数>100 且占比>50%）：实现 run impl-windows-native-support-1794501550-a1 145 轮中 82 轮（56.6%），同一模型 glm-5.3-flash——命中量从上窗 4 run 收敛至 1，但车道面新增 impl（累计六车道）；响应端（模型对照+提示词收敛试验）连续第六窗无机制承接。重述 2026-11-12#可改进#2（命中收敛但车道扩散）。
  - 证据：数据摘要初筛离群行与该 run 终态 run_metrics 原值逐字段吻合（turns=145/text_turns=82/model=glm-5.3-flash，停滞后 success 收尾）；上窗命中的 planner-plan（三连窗重灾区）、planner-judge、admin、arbiter、code-fix 车道本窗全部零命中；cost-observability 域无响应端能力页、spec/changes/ 无承接 spec（本窗复核）。
  - 调查评估：在 windows-native-support 实现车道暴露，为该离群维第六窗命中。已核实事实：唯一命中 run 的指标与模型字段逐一度核；换道 deepseek 收尾的 run 纯文本占比仅 7%（evo-1794500754 二段 512 轮 36 轮），与 glm 命中 run 形成鲜明对照——「模型输出行为漂移」假说获得新的旁证方向（可能收敛于 provider/模型混合路由），但样本不足、假说未证实仅留痕。与存量关系：检测端（evo-refine-midflight-outlier-dims 归档件）闭环，「同车道连续两窗命中即做收敛试验」的触发条件自 11-05 起持续成立，本窗 planner-plan 中断使同车道连窗计数归零、impl 车道则记首窗。结论：恶化趋势暂缓，响应端缺口原样，impl 车道若下窗再命中即构成新连窗。
  - 建议：维持既有最小响应定义（同车道连续两窗命中→按 model 字段对照+提示词收敛试验，可与 API 停滞出口同一小 spec 承接，同数据源 run_metrics）；本窗 impl 命中留痕为该车道首窗，并留一窗观察「deepseek 占比低」的旁证是否复现。

## 2026-11-15

### 失误
- （当日无）

### 可改进
- **幻影成功分类缺口未修，两条自查告警超24小时无人消费**
  - 自进化：问题部分成立 / 建议不合理 / — 不需要
  - 影响：上窗 3 例幻影成功（死于 429 限流的 run 被收尾链按 result 行存在记 terminal=success）的分类写点缺口未修复，本窗零新实例（runs 统计失败 0、无新 429 死亡）；但对应两条升级告警已超 24 小时未处理并各触发一次超期提醒，人工核对请求持续空挂成提醒面噪音。重述 2026-11-14#可改进#1（持续）。
  - 证据：告警 cbfda9c9f490 与 aad34f3dea9b（self_review_phantom_failure——自省分类疑幻影失败信号，指向 1794499508-a1/1794503523-a1 两个裁决复核 run）created 均为 11-14 00:03-00:04 本地、handled=false 至今，即数据摘要「超24h 未处理提醒 2 条」本体；grep core/ 该信号仅 core/self_review.py 一处（产出侧），无裁决桶或自动消费面；本窗 core/self_review.py 唯一改动为提交 9ab956db4（code-fix 批次，尾窗读内存 deque 改造）与收尾分类无关。
  - 调查评估：在 windows-native-support 收尾链遗留（上窗 429 收尾密集期死亡 3 run）暴露。已核实事实：两告警台账原文、created/handled 字段、信号消费面（仅人工）、本窗零新实例逐一度核。根因同 2026-11-14#可改进#1：收尾分类以 result 行存在为主判据、不交叉核验 exit_code 与尾部 synthetic（CLI 合成占位）标记，产物侧失败被记账面吞掉；自查信号按设计止于人工核对（负控豁免面工作正常），但无人值守夜间系统里人工核对天然滞后，告警即老化。与存量关系：run-resilience 域失败分类能力页未覆盖 CLI 合成收尾形态，缺口开放；修复未落地期间每次 429 收尾期复发都会再污染成功统计并新增老化告警。结论：确定性可修、等待落实，本窗唯一新信息是告警老化进入超期提醒循环。
  - 建议：同 2026-11-14#可改进#1：收尾链对「exit_code≠0 且尾部 assistant 为 <synthetic>」的 run 改记 failed/partial，使失败统计与幻影识别不依赖自查信号兜底；两条存量告警在人工核对或修复落地时清账，防提醒面持续空转。

## 2026-11-16

### 失误
- （当日无）

### 可改进
- **[arbiter:evo-fix-] 自进化立项同根因查重缺失（56 秒窗口双 SPEC 同目标）**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：自进化车道同根因双立项时，重复 SPEC 必然走完 评审×2 否决→冻结→升级链（Admin 让位+Arbiter 调查）→人工裁决 全链：每次实测浪费 2 轮评审 run（本次复评 $0.633）+ 1 轮 arbiter 预算 + 人工裁决成本，并在 STATE 留下占位冻结条目；若兄弟交付晚于重复 SPEC 评审，还会产出重复实现撞车。
  - 证据：.fenix/STATE.md:2764-2767（evo-self-review-window-terminal-attribution created 2026-11-16T13:28:36Z）与 :2999-3002（evo-fix-self-review-window-gap created 2026-11-16T13:29:32Z，晚 56 秒）：两者 proposal 同述「夜间审查 run 起点亚秒级早于窗口锚点被整只漏计」，交付面完全重叠（core/self_review.py 改造 + tests/test_self_review_window_attribution.py）；兄弟已 pushed 合入（commit 7bbc1712c..14796d7ea），本 SPEC 评审两轮否决冻结转人工（.fenix/runs/spec-review-evo-fix-self-review-window-gap-a79f32-1794839434.jsonl），升级链空烧 Arbiter 一轮。既有查重仅在 drafts 消费侧按能力名目录查重，SPEC 注册层（物化 spec/changes 条目时刻）无同根因/同交付面对账。；触发 run_id=arbiter-evo-fix-self-review-window-gap-1794839678（签名 evo-fix-self-review-window-gap::spec-review-rejected，来源 chain-handoff:escalation-alert）
  - 调查评估：触发信号 spec-review-rejected（spec=evo-fix-self-review-window-gap）：'evo-fix-self-review-window-gap' 方案连续 2 次被评审否决（已自动复评 1 次仍不成立），需人工修订方案或撤销（blocking findings: 复评逐条重裁上轮 blocking（非沿用）：本 SPEC 的前提是「core/self_review.py 窗口归属判据按 run 起点时刻过滤、两窗都不可见、属待修观测缺口」（proposal.md:3、tasks.md:12 单点改造 _bounded_per_run_scan）。实测 main 树：该判据已被兄弟 SPEC 的合入实现改为终态归属——core/self_review.py:462 _run。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，超出处置白名单，记 todo 由自进化统一立项。
  - 建议：①SPEC 物化注册前对 spec/changes/ 与 STATE 活跃条目做主题/交付面对账（同改文件+同能力域即拦截或合并）；②蒸馏条目消费侧按发现指纹（同根因证据锚点，如同指 core/self_review.py 窗口归属）单飞；③把「目标能力是否已在主干交付」的实测预检从评审门前移到立项 lint（立项前抽查主干代码锚点），命中即拒绝物化并回写 todo。

- **幻影成功分类缺口未修，两条自查告警超期翻倍至48小时（恶化）**
  - 自进化：问题部分成立 / 建议不合理 / — 不需要
  - 影响：上上窗 3 例幻影成功（死于 429 限流的 run 被收尾链按 result 行存在记 terminal=success）的分类写点缺口连续第三窗未修复，本窗零新实例（runs 统计失败 0、窗内零 429 事件）；但对应两条升级告警的超期龄期从 24 小时翻倍到 48.06 小时，超期提醒持续空挂成提醒面噪音。重述 2026-11-14#可改进#1、2026-11-15#可改进#3（持续，超期恶化）。
  - 证据：告警 cbfda9c9f490 与 aad34f3dea9b（self_review_phantom_failure，自省分类疑幻影失败信号，分别指向裁决复核 run planner-judge-windows-native-support-1794499508-a1 与 1794503523-a1）created 均为 2026-11-13T16:03:19Z、handled=false 至本窗窗末（48.06 小时），即数据摘要「超24h 未处理提醒 2 条」本体；grep core/ 该信号仅 core/self_review.py 产出侧一处、无裁决桶或自动消费面；本窗 core/self_review.py 零改动；窗内 grep 429/限流关键词零真实命中（3 条为数字巧合）。
  - 调查评估：在 windows-native-support 收尾链遗留暴露（429 死亡 run 的收尾分类写点缺口）。已核实事实：两告警台账字段、48.06 小时超期、产出侧唯一、本窗零新实例与零 429 逐一度核。根因同前两窗结论：收尾分类以 result 行存在为主判据、不交叉核验 exit_code 与尾部 assistant 为 <synthetic>（CLI 合成占位消息）标记，产物侧失败被记账面吞掉；自查信号按设计止于人工核对（负控豁免面工作正常），无人值守夜间系统里人工核对天然滞后，告警即老化。与存量关系：run-resilience 域失败分类能力页未覆盖 CLI 合成收尾形态，spec/changes/ 55 个活跃 spec 无承接（本窗复核）。结论：确定性可修、等待落实第三窗；修复未落地期间每次 429 收尾期复发都会再污染成功统计并新增老化告警，本窗零复发属 provider 侧平静非防线生效。
  - 建议：同 2026-11-14#可改进#1：收尾链对「exit_code≠0 且尾部 assistant 为 <synthetic>」的 run 改记 failed/partial，使失败统计与幻影识别不依赖自查信号兜底；两条存量告警在人工核对或修复落地时清账，防提醒面持续空转。

## 2026-11-17

### 浪费
- **merge-back WIP重叠拦截空转12分钟：6轮ERROR循环、误报重启建议、闭环后冗余唤起与迟到重投**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：fix-windows-service-userprofile（Windows 服务 USERPROFILE 修复 spec）实现分支合回主树被用户主树未提交改动重叠闸门拦截，11:43:47Z 起以约 2 分钟节奏重试 6 轮后于 11:53:53Z 等待超限转人工，实际 11:55:58Z 由 admin 收编 WIP 后 11:56:00Z 合回成功——管线净延迟约 12 分钟，交付零损失，噪音代价为 6 条 ERROR、5 条告警（含 2 条 daemon_errors critical 误建议重启 daemon 且至今未处理）与 1 次闭环后的冗余 admin 唤起。
  - 证据：ERROR 循环：worktree_manager「Merge-back blocked by WIP overlap precheck (policy=escalate)」11:43:47-11:53:53 共 6 条（间隔约 2 分钟）加 pm_engine「WIP 延迟合回等待超限——已停止自动重试」收尾；daemon_errors critical 告警 d8ef701ddc92 与 dfc9977c57cb（指纹 abbcf28b，11:45:16Z，「建议检查根因并重启 daemon」，handled=False 至窗末）；mergeback_wip_defer_stuck（WIP 延迟合回等待超限信号）告警链 703904266295（11:53:53Z）→ 5354c859723c（12:00:17Z「Administrator 处置中」，唤起 run admin-fix-windows-service-userprofile-1794830417）→ de3f9e698b59（12:05:32Z「降级告警迟到重投：分支已成功合回、告警 pending 滞留被周期重投唤起处置已闭环的困境」）；收编提交 132490e0c（11:55:58Z「admin: 收编 settings 深链预选 WIP 解除 merge-back 重叠闸门」）与合回提交 9df3de055（11:56:00Z）；该 spec 五个分支经 git branch --merged main 核对全部已并入、分支相对 main 零残留提交。
  - 调查评估：在该 spec 实现分支合回主树时暴露，重叠源是用户在主树的 settings 页未提交改动（已知摩擦面）。已核实事实：ERROR 节奏、超限时点、admin 收编、两秒后合回、五分支零丢弃逐一度核。根因分层：拦截与等待超限是 wip-defer-merge-retry（WIP 阻断延迟合回，等待标志+周期自动合回）治理链的设计内行为，收编出口有效；噪音面有三——daemon_errors 升级面把自愈链过渡态 ERROR 判 critical（修复合入见 resolved）、等待超限升级路径与 admin 收编竞态产生冗余二次唤起（12:00 唤起时 11:56 已合回）、告警闭环后 pending 滞留仍被周期重投（12:05 迟到重投自证）。与存量关系：11-12#可改进#1 已修复合入；冗余唤起与 11-13/11-14 admin 唤起协调条目同族但属「超限升级不重检收口态」形态。结论：交付零损、实损为约 12 分钟管线延迟与告警噪音，收编出口按设计工作。
  - 建议：等待超限升级派发前重检合回收口态（分支已并入或 spec 已推进 testing 即取消唤起）；告警闭环时同步撤 pending 防迟到重投；两条 daemon_errors 告警（指纹 abbcf28b）人工清账。

### 失误
- （当日无）

### 可改进
- **自进化条目批量接受失败20条：进程内NameError被fail-closed误标SPEC名冲突，验收延迟约4.2小时**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：自进化车道（蒸馏条目复核→SPEC 立项）一批 20 个条目在 3 秒内全部接受失败，被误报为「SPEC 名冲突无法消解」，实际根因是 STATE 读取路径抛出 name 'self' is not defined 内部异常、被 fail-closed 保守判冲突；条目延至当晚 23:00-23:01 下一接受批次才恢复立项，净损失约 4.2 小时验收延迟，外加 20 条误导性升级告警全部滞留未处理（复发敞口：每次同类异常都会整批毒化且无自动重试）。
  - 证据：admin_alerts 台账 2026-11-16T10:44:21.107 至 10:44:24.128Z 连续 20 条 self-evolution 告警「自进化条目 <hash> 接受失败：SPEC 名冲突无法消解」全部 handled=False（数据摘要第 3 节只列出其中 4 条）；fenixd.log 同批 40 条 WARNING「evolution: 读取 STATE 判定重名失败，保守按冲突处理: name 'self' is not defined」（first/last 均在该 3 秒窗内，每条目基名与加后缀名各判一次）；误报文案出处 core/evolution.py:1750 resolve_spec_name 的 fail-closed 分支（STATE 读取故障保守判冲突）；.fenix/evolution/items.jsonl 台账现存 100 条目仅 analyzed=65/accepted=35、零 draft_failed 残留（已全部恢复），本地 23:00-23:01 的 15 条 spec 提交与 4 条标记回写提交即恢复批次。
  - 调查评估：在自进化条目接受车道批量消费蒸馏产物时暴露。已核实事实：告警条数、异常文本、时间聚集、台账恢复、恢复批次提交逐一度核；异常「name 'self' is not defined」说明 state_machine 对象的 read_all 在旧 daemon 进程内处于坏形态（具体缺陷点未核实——重启后 23:00 批次正常暗示进程局部性，但无直接代码锚点，根因写到形态层不预设）。与存量关系：2026-11-16#可改进#1（立项同根因查重缺失）同在物化层但根因不同（那是真查重缺失，本例是内部异常误标）；fail-closed 设计本身正确（防覆盖同名条目），缺口在异常文本不进告警导致误标排障方向，以及 draft_failed 无自动重试通道（本次靠 daemon 重启恢复属偶然）。结论：可起草性高的小 spec，双改动点明确。
  - 建议：①resolve_spec_name 的保守冲突告警把异常文本（如 NameError 详情）带进 admin 告警 description，区分「内部异常」与「真名冲突」；②draft_failed 条目增加低频自动重试（随下一接受批次重试一次为限）；③排查 read_all 在接受路径抛 NameError 的具体缺陷点（当前代码未复现，需对旧进程对象形态取证或补诊断日志）。

- **蒸馏run统计面假失败：窗内唯一失败实为成功落库，疑似把result文本「ADR零产出」误当失败标记**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：本窗运行摘要把唯一的「失败」记在知识蒸馏 run（knowledge-distiller-evo-fix-distill-retry-ledger-auto-close）头上，标失败 marker=零产出；但该 run 实际成功完成并把蒸馏内容落库（提交 e47694b87），run 档案自查六项全部通过——统计面与事实相反，属假失败（幻影成功的镜像形态）；复发敞口为每轮摘要的失败计数不可信，消费方（含每日自省的失败判读与告警分诊）会被系统性误导。
  - 证据：run 档案 .fenix/runs/archive/knowledge-distiller-evo-fix-distill-retry-ledger-auto-close-1794838627.jsonl 仅三行：started 22:17:07（本地 UTC+8）、round 22:25:06、result 22:25:08，result 文本「机器校验 0 违规，自查六项全部通过…ADR 零产出…」并载 commit=e47694b87；git show e47694b87 核实为蒸馏落库提交（22:25:08）内容属实；同一摘要却将该 run 记为「失败 marker=零产出」。
  - 调查评估：在每日自省对失败计数取数时暴露：成功 run 的 result 文本里出现「ADR 零产出」这类正常自述（该轮蒸馏产出知识页而非 ADR），统计取数点疑似把 result 文本子串当失败标记匹配（子串匹配假说未核实代码，判据缺陷或取数错位两假说并存，根因未定）。与存量关系：2026-11-14#可改进#1 的幻影成功是「失败被记成功」，本例是反向「成功被记失败」，同门（收尾分类与 result 行矛盾的对账缺失）镜像两态。结论：失败分类应以结构化字段（status/exit 码/commit 非空）为准，文本匹配取数点需定位修复；证据只到形态层，不预设具体实现。
  - 建议：①失败判读改以结构化字段为准：result 行含非空 commit 或 status=success 即成功；②定位摘要「零产出」marker 的取数点，消除对 result 文本的子串匹配；③下窗核对失败计数应归零（该 run 已成功），若仍非零说明判据未修。

### 知识真相源
- [ ] knowledge-distill 重试：归档 evo-impl-worktree-preservation-refs, evo-scenario-exec-tree-isolation — run 失败: claude 进程非零退出（exit=1）；stderr 尾部: Claude Code doesn't recognize the model "glm-5.3-flash", so it assumes a context window of 200k tokens. Update Claude Code, or see https://code.claude.com/docs/en/model-config#correct-the-window-for-a-gateway-or-custom-model-id to set the window. [claude-code:unrecognized_model] {"model":"glm-5.3-flash","query_source":"sdk"}；拒识形态 unrecognized_model（生效模型名 glm-5.3-flash，显式传名仍被拒属确定性失败），不重试

## 2026-11-18

### 失误
- **quality-gates.json形态漂移再现双spec四告警，写侧校验缺口持续开放**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：两个 spec 的实现收尾把 quality-gates.json（验证质量门状态文件）写坏，四条宽松对账告警放行零拒收零重派；形状清单新增第四种形状「顶层缺 gates 对象」，复发敞口为下次漂移撞严格门时重演终点拒收-重派周期（11-03 实测代价 48 分钟 run 被拒），且本窗一次连坏两个 spec 显示惯性面在扩大。
  - 证据：告警 80d9aaa834bd 与 9f93452252b6（evo-drain-inflight-run-protection，11-16T16:11Z，「顶层缺 gates 对象」）与 f345240f1af1、6e97006e2b6d（evo-scenario-exec-tree-isolation，11-16T16:26Z，「顶层 gates 键非对象（实际类型 list）」），四条 handled=False 至今；两 spec 实现分支分别于 11-17 00:11（b75f35fd2）与 00:26（721ec20b6）合入主树。
  - 调查评估：在两 spec 实现收尾写盘时暴露，为 2026-11-06#失误#1 的复发（该条目已滚出近 3 日窗口，本条重新登记）。已核实事实：四条告警原文、对象路径、两 spec 合入时刻逐一度核。根因同 11-06 结论：quality-gates.json 由实现 run 自由写盘、写侧无 schema 校验，monitor 按「宽松对账、仅告警放行」设计放行，执行层得不到硬反馈，漂移惯性延续。形状史盘点：11-03 枚举漂移「pass」（合法值 passed）、11-06 结构漂移「list 冒充对象」、本窗「缺 gates 对象」新增存在维且「list」形状再现——枚举、结构、存在三个维度均有实例。与存量关系：11-06 建议（共享写侧校验：顶层 gates 必须对象、status 枚举限 passed；写后自检并入 implementer 收尾自检清单）至今未立项，grep spec/changes/ 全部 proposal 无 quality-gates 写侧校验承接（本窗复核）；同族 11-05#失误#1 的 task_gate 对账建议同样未落地。结论：执行惯性点+写侧校验缺口，确定性可修，双 spec 同窗复发证明靠告警留痕无法自愈。
  - 建议：落共享写侧校验（顶层 gates 必须对象、status 枚举限 passed），并把写后自检并入 implementer 收尾自检清单（与 tasks.md 勾选↔TaskUpdate done_ids 对账项同批落地）；四条存量告警随修复落地人工清账。

### 可改进
- **蒸馏重试欠账无终局出口，同日8例成功反证unrecognized_model确定性判读**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：两个已归档 spec（evo-impl-worktree-preservation-refs、evo-scenario-exec-tree-isolation）的知识蒸馏自 11-17 00:29 失败后 24 小时+无人重试，归档件知识页持续缺位，重试欠账催办告警每 24 小时空转一拍；失败被标「确定性失败不重试」导致永不重试，但同日 08:51-11:22 的 8 个蒸馏 run 同模型全部成功，反证其为瞬态故障。
  - 证据：失败档案 knowledge-distiller-evo-impl-worktree-preservation-refs-1794846597.jsonl 仅 3 行：started（11-17T00:29:57+08:00）+ error「Claude Code doesn't recognize the model "glm-5.3-flash"…（exit=1）」（即数据摘要「秒挂: 1」本体）；留痕提交 78864f6b8（11-17 00:34，仅 spec/knowledge/log.md +1 行，失败登记非落库）；催办告警 6e387534fa53（11-17T16:04Z，「重试台账欠账超 24 小时未重试（1 条）」）；对照同日 8 个 knowledge-distiller run 档案尾部全部 result 成功且产物落库（提交 209591335、02b84e16d、8e739ce28、138e5f330 等），模型同为 glm-5.3-flash。
  - 调查评估：在蒸馏车道消费两归档件时暴露，同时构成对 2026-11-17#知识真相源#1 归因的显式更正。已核实事实：失败档案 3 行形态、留痕提交仅改 log.md、催办时刻（失败后约 23.6 小时）、同模型 8 连成功逐一度核。归因更正：上窗判读「生效模型名 glm-5.3-flash 显式传名仍被拒属确定性失败，不重试」被同日 8 小时后同模型蒸馏 8 连成功证伪——00:29 的拒识是瞬态（CLI/网关瞬时故障假说，具体机制未核实不预设），按确定性终局处理使两条归档知识（实现产物保全引用、场景执行树隔离）欠账至今。与存量关系：spec/changes/evo-fix-distill-retry-ledger-auto-close（已合入）只治「成功落库的假欠账自动闭环」与「催办去重持久化」，其范围外明文「不自动重试蒸馏」——本窗缺口恰在其范围外：被判定「不重试」的行无终局出口（无放弃登记、无自动勾选、无降频），欠账行将每 24 小时催办空转直至人工介入；该两 spec 恰是 11-17 窗重试登记（提交 55ad46ead）的对象，欠账即其延续。结论：瞬态被误标确定性+台账无终局出口，双缺口确定性可修。
  - 建议：①unrecognized_model 形态改判「疑似瞬态」，允许次日节拍低频重试一次验证后再降级不重试；②重试台账对「决定不重试」的行补终局出口（登记放弃原因并自动勾选，或降级为低频月度提醒），消除每 24 小时催办空转；③人工触发一次两 spec 蒸馏补账或勾选 todo 台账行。

- **归档spec的冻结告警滞留近一天，归档后仍老化升级至critical**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：重复立项 spec evo-fix-self-review-window-gap（11-16 窗 56 秒双 SPEC 同目标的重复方）已于 11-16 归档出清，但其评审否决冻结挂起的 pending 处置告警在归档后继续老化升级两次（120 分钟 warning、360 分钟 critical），两条 handled=False 滞留约 19-23 小时，人工面持续挂无效待办。
  - 证据：归档提交 3e18548f3（11-16 23:18 本地，把该 spec 移入 spec/archive/2026-11-16-）；告警 60b032af99b0（disposition，「告警老化升级（warning）：pending 超 120 分钟仍未人工处置（推荐 abandon）」，11-16T16:43Z=归档后约 85 分钟）与 b1b142eb677a（「告警老化升级（critical）：pending 超 360 分钟」，11-16T20:43Z=归档后约 5.4 小时），两条 handled=False 至今。
  - 调查评估：在该重复 spec 走完全链（评审否决×2→冻结挂 pending→归档出清）后暴露。已核实事实：归档提交时刻、两条 aging 告警创建时刻均在归档之后、handled 状态逐一度核。根因：告警生命周期与 spec 终态无联动——spec 归档/撤销后其关联 pending 告警不被扫描闭合，aging 升级器只看告警自身 pending 时长、不核验关联 spec 是否已终态，于是对已不存在的裁决对象继续按节拍升级。与存量关系：该 spec 是 2026-11-16#可改进#1（自进化立项同根因查重缺失）的实证件，其走完全链后残留告警尾账属该条目成本预估的追加验证；add-spec-softdelete-alert-linkage（11-17 10:48 合入）已建「软删除联动关闭关联告警」通道，但归档与撤销终态路径无同类联动。结论：告警卫生缺口，单例代价小（告警噪音与人工核对注意力）但每例滞留以小时-天计，与软删除联动同模式可修。
  - 建议：把软删除联动模式扩展到归档/撤销终态：spec 终态迁移时联动关闭其关联 pending/aging 告警；或在 aging 升级前核验关联 spec 是否已终态，终态即静默闭合留痕；两条存量告警人工清账。

- **幻影成功分类缺口未修超96小时，两条自查告警四天无人消费（恶化）**
  - 自进化：问题部分成立 / 建议不合理 / — 不需要
  - 影响：3 例幻影成功（死于 429 限流的 run 被收尾链按 result 行存在记 terminal=success）的分类写点缺口连续第四窗未修复，本窗零新实例（窗内零 429 死亡）；对应两条升级告警超期龄期达 4 天（96 小时），超期提醒持续空挂成提醒面噪音。
  - 证据：告警 cbfda9c9f490 与 aad34f3dea9b（self_review_phantom_failure，自省分类疑幻影失败信号，分别指向裁决复核 run planner-judge-windows-native-support-1794499508-a1 与 1794503523-a1）created 均为 11-13T16:03Z、handled=False 至本窗窗末恰 4 天（数据摘要「已登记 4 天 0 小时未处理」两条即此）；grep core/ 该信号仅产出侧一处、无裁决桶或自动消费面；窗内收尾分类相关代码零改动。
  - 调查评估：在 windows-native-support 收尾链遗留（11-13 窗 429 收尾密集期死亡 3 run）暴露。已核实事实：两条告警台账字段、4 天龄期、产出侧唯一、本窗零新实例与零 429 事件逐一度核。根因同前三窗结论：收尾分类以 result 行存在为主判据，不交叉核验 exit_code 与尾部 assistant 为 <synthetic>（CLI 合成占位消息）标记，产物侧失败被记账面吞掉；自查信号按设计止于人工核对（负控豁免面正常），无人值守夜间系统里人工核对天然滞后，告警持续老化。与存量关系：run-resilience 域失败分类能力页未覆盖 CLI 合成收尾形态；11-17 窗自省因窗内零复发未重述，本窗摘要超期提醒再现证明问题仍开放。结论：确定性可修、第四窗开放；本窗零复发属 provider 侧平静非防线生效。
  - 建议：收尾链对「exit_code≠0 且尾部 assistant 为 <synthetic>」的 run 改记 failed/partial，使失败统计与幻影识别不依赖自查信号兜底；两条存量告警在修复落地或人工核对时清账，防提醒面持续空转。

- **纯文本轮通胀第十窗2命中，机制生效后占比未收敛且回填一成一败**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：纯文本轮离群维（无工具调用的模型回复轮，轮数>100 且占比>50%）本窗 2 个 run 命中且同车道（impl）：占比 51.1% 与 50.4%，均为 glm-5.3-flash 成功收尾——输出纪律机制生效后首窗即见命中，占比与历史七窗命中形态同量级未收敛；input_tokens 回填机制一成一败，token 量化面仍半盲。
  - 证据：数据摘要第 6 节初筛离群两行原始值；两 run 终态 run_metrics 逐字段核对：impl-add-chain-quota-paging-1794880658-a1（turns=225/text_turns=115/input_tokens=134950，回填生效）与 impl-evo-scenario-exec-tree-isolation-1794842615-a1（turns=371/text_turns=187/input_tokens=0，回填未生效）；响应机制 evo-text-turn-inflation-response 的 2.1 输出纪律仅覆盖 planner-plan 车道，impl 不在其覆盖面。
  - 调查评估：在两个 impl run 暴露，为响应机制（11-17 00:01 合入、随 daemon 11-17 10:59:29 重启生效）生效后首窗观察。已核实事实：两 run 占比、model 字段、input_tokens 值逐一度核。机制覆盖面：输出纪律按设计先治重灾区 planner-plan 车道，impl 车道命中属预期内未覆盖面而非机制失效；1.1 的 input_tokens 回填对同窗两 run 一成一败，1794842615-a1 的流内 usage 缺失形态未核实，回填源依赖待查。样本一窗不足以判定机制有效性：planner-plan 车道本窗零命中是初步正面信号，但 impl 占比 50.4%/51.1% 与历史同量级。结论：观察性条目——机制方向未证伪，覆盖面扩展与回填补盲留痕待续窗验证。
  - 建议：连续观察 2-3 窗 impl 车道占比与 planner-plan 占比分化（若 planner-plan 收敛而 impl 持续超线，则评估输出纪律扩展到 impl 车道）；核查 1.1 回填对 1794842615-a1 形态未生效的具体缺失源并补齐。

## 2026-11-19

### 失误
- （当日无）

### 可改进
- **幻影成功分类缺口第五窗开放，两条自查告警满5天无人消费（恶化）**
  - 自进化：问题部分成立 / 建议不合理 / — 不需要
  - 影响：3 例幻影成功（死于 429 限流的 run 被收尾链按 result 行存在记 terminal=success）的分类写点缺口连续第五窗未修复，本窗零新实例（窗内零 429 死亡、失败统计零失真）；但两条升级告警龄期恰满 5 天，超期提醒持续空挂。修复缺位下每次 429 收尾期复发都会再污染成功统计并新增老化告警（11-14 窗实测单次复发伴生约 35 美元 run 报废）。
  - 证据：告警 cbfda9c9f490 与 aad34f3dea9b（self_review_phantom_failure，自省分类疑幻影失败信号，分别指向裁决复核 run planner-judge-windows-native-support-1794499508-a1 与 1794503523-a1）created 均为 2026-11-13T16:03 UTC、handled=false 至本窗窗末恰 5 天（数据摘要「已登记 5 天 0 小时未处理」两条即此）；同族第三条 287fbb68e971（11-12 创建）已人工清账（handled=true），证明清账动作可行但未覆盖剩余两条。grep core/ 该信号仅 core/self_review.py 产出侧一处、无裁决桶或自动消费面，窗内收尾分类相关代码零改动。
  - 调查评估：在 windows-native-support 收尾链遗留（11-13 窗 429 收尾密集期死亡 3 run）暴露，重述 2026-11-18#可改进#3（恶化）。已核实事实：两条告警台账字段、5 天龄期、产出侧唯一、本窗零新实例与零 429 事件逐一度核。根因同前四窗结论：收尾分类以 result 行存在为主判据，不交叉核验 exit_code 与尾部 assistant 为 <synthetic>（CLI 合成占位消息）标记，产物侧失败被记账面吞掉；自查信号按设计止于人工核对（负控豁免面正常），无人值守夜间系统里人工核对天然滞后。与存量关系：run-resilience 域失败分类能力页未覆盖 CLI 合成收尾形态；spec/changes/ 54 个活跃 spec 无承接 proposal（grep synthetic/幻影 零命中，本窗复核）；窗内自进化复核亦未将其裁为 worth_spec（台账 6f9a9e96eb54 status=analyzed，复核完毕不立项）。结论：确定性可修、第五窗开放；本窗零复发属 provider 侧平静非防线生效。
  - 建议：收尾链对「exit_code≠0 且尾部 assistant 为 <synthetic>」的 run 改记 failed/partial，使失败统计与幻影识别不依赖自查信号兜底；两条存量告警（cbfda9c9f490/aad34f3dea9b）比照第三条同族告警的先例人工清账。

- **蒸馏欠账进入第3天，窗末催办告警再落一拍，worth_spec立项仍待接受批次消费（持续）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：两个已归档 spec（evo-impl-worktree-preservation-refs、evo-scenario-exec-tree-isolation）的知识蒸馏欠账进入第 3 天，归档件知识页持续缺位；催办告警 24 小时一拍空转（台账 2 条全部未处置），unrecognized_model 判读修正与台账终局出口两缺口未动。复发敞口：同日 8 例成功已反证拒识为瞬态，下次瞬态拒识仍会被「确定性失败不重试」永久搁置。
  - 证据：告警 ec470e51ad01（knowledge_distill_retry_stale，蒸馏重试台账欠账催办 warning）2026-11-18T16:03 UTC（本地 11-19 00:03 窗末）落账：「欠账超 24 小时未重试（1 条）：evo-impl-worktree-preservation-refs, evo-scenario-exec-tree-isolation（登记 2026-11-17，欠账 2 天）」，与前一拍（11-17T16:04）构成该信号族台账仅有的 2 条且全部 handled=false；.fenix/todo.md 第 461 行对应待办行仍在；两 spec 的蒸馏落库提交窗内零出现（git log 核实）。自进化复核台账 6033534dfc34（蒸馏终局出口+unrecognized_model 瞬态改判条目）窗内被裁 worth_spec=true、status=pending 待接受立项，约 22 小时未消费。
  - 调查评估：在蒸馏车道（knowledge-distill，归档件知识蒸馏）消费两个归档件时持续暴露，重述 2026-11-18#可改进#1（持续），并覆盖 2026-11-17#知识真相源#1 的行动欠账。已核实事实：催办节拍（24 小时一拍共 2 条）、欠账天数、todo 行在档、零补账提交、worth_spec 裁决在档逐一度核。根因同上窗：11-17 00:29 的模型拒识是瞬态（同日同模型蒸馏 8 连成功反证确定性判读），被按确定性终局处理后无重试通道；台账对「决定不重试」的行无终局出口（无放弃登记/无自动勾选/无降频），欠账行每 24 小时催办空转。与存量关系：evo-fix-distill-retry-ledger-auto-close（已合入）范围外明文「不自动重试蒸馏」，缺口恰在其范围外；evo-add-distill-retry-ledger-aging 提供催办节拍本体；本窗自进化车道已裁 worth_spec=true（run evo-1794932384 复核 6 条产出 2 条 worth_spec，另一条为 quality-gates 写侧校验），立项落地后承接建议①②。结论：双缺口确定性可修、承接件已排队待接受批次消费；欠账本身需人工触发一次补账或勾选 todo 行止血。
  - 建议：①自进化车道尽快消费 pending 批次，把「蒸馏终局出口+unrecognized_model 瞬态改判」立项落地（台账 6033534dfc34）；②落地前人工触发一次两 spec 蒸馏补账，或勾选 .fenix/todo.md 第 461 行待办使催办停止空转；③催办告警随立项一并接入终局出口的放弃登记语义。

- **audit疑点13条待人工仲裁积压50天，聚合提醒每日一拍空转且仲裁文件从未创建**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：知识体检（knowledge audit，知识真相源周期体检车道）的 13 条疑点待人工仲裁积压至最长龄期 50 天，人工仲裁文件 .fenix/knowledge_audit_arbitration.json 至今不存在（仲裁决定从未登记过一次）；聚合提醒以每日一拍节奏重复追加 todo 与单行提交，近 8 天即 8 拍——提醒面空转约 50 天零消费，13 条疑点悬置同时使知识真相源的潜在矛盾持续无仲裁出口。
  - 证据：todo.md 2026-11-02 节聚合条目原文「audit 疑点升级待人工（聚合）：13 条待人工仲裁（最长龄期 50 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note）」；窗末提交 fce861a9a（11-19 00:03「todo: audit 疑点升级待人工（聚合）……最长龄期 50 天」）与前日 3e68e149f（11-18 00:04，49 天）构成每日一拍序列，git log --since=2026-11-10 计同文案提交 8 条；疑点台账 .fenix/knowledge_audit_findings.json 在档且 status=escalated 恰 13 条（suspected 5、exempt 24），全部条目无 decision/arbitration 字段，与仲裁文件不存在互证人工从未消费。
  - 调查评估：在知识体检疑点的仲裁消费面暴露（非本窗新发生，龄期证明长期积压，本窗龄期+1 达 50 天故立条）。已核实事实：聚合提交频率（8 拍/8 天）、仲裁文件缺位、findings 台账 13 条 escalated 且零仲裁字段逐一度核；13 条疑点的逐条内容未展开（属人工仲裁职责，本条只处置提醒面与积压事实）。根因分层：体检车道的疑点升级与聚合提醒按设计工作（每日一拍防遗忘），但人工面 50 天未消费，且提醒对无响应场景无上限升级/降频机制——只会无限重复同一文案。与存量关系：2026-11-07 窗曾有 3 条 contradiction（知识页互相矛盾）转写失败待人工核查同门；本条与幻影告警条目同属「人工面长期未消费的告警/待办积压」形态，但对象是知识治理仲裁待办。结论：提醒噪音量小（每日一条单行提交）但 50 天零消费证明「每日一拍」节奏对长期积压无效，13 条疑点悬置是真实的知识治理缺口。
  - 建议：①人工一次性消费：按 .fenix/knowledge_audit_findings.json 的 13 条 escalated 指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核、聚合提醒即停；②提醒面改造：同指纹聚合提醒超 7 天未消费即降频为每周一拍（或龄期超 30 天冻结重复、仅保留 todo 单条），消除每日一拍的提交噪音。

## 2026-11-20

### 浪费
- **API停滞第十二窗回落至18.6分钟三连降出口条件持续不成立**
  - 自进化：问题不成立 / 建议合理 / — 不需要
  - 影响：本窗三个在跑 run 的 API 停滞（单轮 API 往返等待超 60 秒的记账段）合计 1115.3 秒约 18.6 分钟纯墙钟等待，为十二窗序列 92→370→175.5→210.1→174.0→51.1→78.8→31.7→416.6→68.2→50.7→18.6 的最低位、连续第三窗回落，属有利走势；零失败零金额损失，损失面全在墙钟。
  - 证据：数据摘要第 6 节 3 行 run 级 api-stall 行与 run 档案终态 run_metrics（run 结束时写入档案的结构化计量行）回源逐项吻合：code-review-1795017829（夜间全仓代码审查 run，本地 2026-11-19 00:03-02:17，2.22 小时 2213 轮）停滞 7 次合计 610.406 秒、单次最长 131.588 秒；evo-1795018686（自进化复核 run）1 次 275.68 秒；evo-1795025603 3 次 229.2 秒，合计 1115.286 秒；车道级日汇总行（按车道×日累计的停滞记账）code-review 610.4 秒 1 run、evolution 504.9 秒 2 run 与逐 run 相加精确自洽，均低于 30 分钟预算线；api_round_stall_escalated（单轮停滞超 300 秒的升级信号）窗内日志零出现与之吻合；夜审 run 成本 107.02 美元与前三晚 103.6/113.5/115.3 基线持平，模型均 glm-5.3-flash；摘要「在跑无终态 1」即出窗前新起的 code-review-1795104099（本地 2026-11-20 00:01:39），为正常夜间审查起点、非滞留残留。
  - 调查评估：核实：三 run 终态计量与摘要、车道日汇总三方对账一致，跨窗单次入账无重复。归因：停滞根因沿用多假说并存口径（网关排队、长上下文、本地网络、provider 限流），本窗无新增归因证据，不预设单因。与存量关系：检测、记账、车道日汇总、预算信号四层链（evo-add-lane-stall-daily-budget-accounting 交付）连续在账生效；cost-observability 域 api-stall-observability 能力页现行文本仍为「观测纯读侧不干预」（本窗复核域导航页确认），无重复立项对象；出口试验按 2026-11-14#浪费#2 修正口径（停滞合计连续回升两窗才动）持续不成立。结论：三连降至序列最低位（18.6 低于此前最低 31.7），观察链条闭合，本条作走势留痕并构成 2026-11-19#浪费#1 与 2026-11-17#浪费#1 的闭环依据。
  - 建议：维持触发口径与纯读侧不干预约定不动，零代码动作；顺带推动 evo-add-lane-stall-daily-budget-accounting 归档收尾（已生效交付滞留活跃区，按每日滞留盘点口径 49 个终态未归档属阈值排水设计内，归档完成后其规则才入知识真相源）。

### 可改进
- **幻影成功分类缺口第六窗两条告警龄满6天无消费（恶化）**
  - 自进化：问题不成立 / 建议部分合理 / — 不需要
  - 影响：死于 429 限流（上游请求过量拒绝）的 run 仍会被收尾链按结果行存在记成 success（幻影成功，失败统计被污染的分类缺口），两条自查告警龄期达 5 天 23 小时近 6 天无人消费，较上窗继续恶化；复发时将再污染成功统计并新增老化告警（11-14 窗实测单次复发伴生约 35 美元 run 报废）。
  - 证据：告警 cbfda9c9f490 与 aad34f3dea9b（.fenix/admin_alerts.json 中 self_review_phantom_failure 自查信号，本地 2026-11-14 00:03 产生，分别指向裁决复核 run planner-judge-windows-native-support-1794499508-a1 与 1794503523-a1 的收尾疑点）handled=false 至本窗窗末满 5 天 23 小时；同族第三条 287fbb68e971 已按先例人工清账（handled=true），证明清账通道可行；本窗零 429、零新实例（run 统计 3 成功均真实、失败 0）；grep 全仓该信号仅 core/self_review.py 产出侧一处、无消费桶；git log 自 11-17 起收尾分类相关代码零改动；判别幻影的两个结构化标记为 exit_code 与尾部 <synthetic>（CLI 断流时以合成占位 assistant 消息代收尾的标记）。
  - 调查评估：核实：告警台账、产出侧代码、收尾链代码三处只读回源，缺口未修、窗内零复发。根因同前五窗结论：收尾分类以结果行存在为主判据，不交叉核验 exit_code 与尾部 synthetic 标记，产物侧失败被记账面误记成功，属确定性可修的产出侧小改。与存量关系：run-resilience 域失败分类能力页 grep 实测无 synthetic 与合成收尾形态覆盖（本窗复核），属既有缺口龄期恶化非新发现；该修复建议在前窗自进化复核中被判「建议不合理」，框架车道不会自动承接，只能人工修码或人工清账。结论：第六窗重述（恶化），龄期加一天、零新增实例。
  - 建议：①人工在收尾分类点补「exit_code 不为 0 且尾部 assistant 行为 <synthetic> 时改记 failed 或 partial」小改，使失败统计不依赖自查信号兜底；②两条告警比照 287fbb68e971 先例先清账止住提醒空转，待修复落地后新机制自动兜底。

- **蒸馏欠账升级major接受批次空转14草稿滞留（恶化）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：两个归档 spec 的知识蒸馏（归档件提炼知识页的车道）欠账满 3 天并在窗末升级 major 告警仍零补账；同源地自进化接受闸门（worth_spec 条目的草稿等用户在设置页点「同意」才物化为 SPEC 的人工环节）已空转 3 天，14 条 worth_spec（复核判定值得立项的条目）草稿滞留队列、最老约 3 天，含两条可闭环既有缺口的承接种子，属持续恶化。
  - 证据：告警 aae995bcdf2b（knowledge_distill_retry_stale 蒸馏重试欠账信号窗末一拍，2026-11-19T16:01 UTC 原文「欠账超 24 小时未重试（1 条）：evo-impl-worktree-preservation-refs, evo-scenario-exec-tree-isolation（登记 2026-11-17，欠账 3 天）；欠账已超 3 天 未处置，升级为 major」，handled=false，同族前两拍 6e387534fa53 与 ec470e51ad01 同未处置）；.fenix/knowledge-distill-retry-state.json 实测 last_severity=major、last_reminded_date=2026-11-20；todo.md 蒸馏补账待办行（11-19 窗引用为第 461 行）仍未勾选；两欠账 spec 自 11-17 失败留痕提交后零补账提交。接受面：.fenix/evolution/items.jsonl（自进化条目台账）14 条 status=pending，最老 13dbc65e1557 登记 2026-11-16T16:57 UTC（本地 11-17 00:57，约 3.0 天）；承接种子 6033534dfc34（蒸馏「决定不重试」行无终局出口缺口修复）与 deb14643f2be（quality-gates.json 写侧校验，同 11-18#失误#1 的承接）滞留约 2 天；另有 2b343adf6c0c（merge-back 空转，用户已标值得立项）、4a6939ce81bf（蒸馏统计面假失败承接，其「下窗核对失败计数归零」验证项本窗实测通过：摘要失败 run 数为 0）、f0ec16490cea（本窗新增，API 停滞缺请求体积字段）；.fenix/evolution/drafts/ 实测 14 个草稿目录、每目录 proposal.md/design.md/tasks.md/specs 四件齐全；最后接受批次为本地 2026-11-16 23:00-23:01 的 15 条 spec: evo-* 提交（git log 实证），至窗末空转整 3 天；本窗两个自进化分析 run 日志自述「接受 0」（落地完成行：条目 5 加条目 4，草稿 1，接受 0，失败 0）。
  - 调查评估：核实：告警原文、重试状态文件、todo 待办行、git log、条目台账、草稿目录六处只读回源，欠账升级与接受停摆双双实锤，且本窗两个分析 run 复核 9 条条目仅新增 1 条 pending、零接受。根因：接受是设计内人工闸门——self-evolution 域能力页明文「立项默认等用户点『同意』，打开自动接受后才由框架闭环到流水线」且「auto_accept 开关为假（含配置缺失）时保持 pending 等待用户决定」，停摆直接原因是 11-16 晚之后人工审批未再发生，非调度故障（此前「接受批次调度缺失」假说被该规则证伪，不采信）；蒸馏欠账同样需人工补账或勾选台账行，自动面仅按 24 小时节拍催办并按约升级 major。与存量关系：老化催办机制（evo-add-distill-retry-ledger-aging 交付）工作正常且升级节拍符合设计；「不重试终局出口」缺口已有 6033534dfc34 种子承接但滞留待批，与存量规则不重复。结论：合并重述 2026-11-19#可改进#2、2026-11-18#可改进#1 及 2026-11-17#知识真相源#1 的更正后实质（恶化），两条线同源于人工闭环面未动作。
  - 建议：①在 dashboard 设置页「自进化」页签对 14 条 pending 批量裁决（逐条同意或拒绝），优先放行 6033534dfc34 与 deb14643f2be 两条承接种子；若信任自动闭环可打开 self_evolution.auto_accept 配置根除排队；②人工触发一次两 spec 蒸馏补账或勾选 todo 蒸馏待办行，止住 major 告警逐日升级；③顺带人工清账 dfc9977c57cb（merge-back 误报重启建议的残余告警，同族 d8ef701ddc92 已清）。

- **知识体检疑点积压至51天仲裁文件仍未创建（恶化）**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：知识真相源体检（对 spec/knowledge 规则冲突与过期项的自动巡检）发现的 13 条待人工仲裁疑点积压至 51 天（上窗 50 天），仲裁登记文件至今未创建，每日一拍聚合提醒持续空转，属持续恶化的人工闭环欠账。
  - 证据：窗末成对提交 86462796a（todo: audit 疑点升级待人工（聚合）：13 条待人工仲裁（最长龄期 51 天））与 c17ba4595（knowledge: log audit 体检留痕）于本地 2026-11-20 00:01 落库；上一拍 fce861a9a 为 50 天版，逐日加一的提醒序列完整；.fenix/knowledge_audit_arbitration.json 实测不存在（该文件为仲裁登记文件，人工按 fingerprint/decision/decided_at/note 逐条登记后框架检查点自动消费、聚合提醒即停）。
  - 调查评估：核实：提醒提交序列与仲裁文件存在性两处只读回源，积压持续、登记通道零进展。根因：仲裁动作只能由人工按指纹逐条登记（框架仅负责每日聚合提醒与龄期计数），自首条提醒以来用户侧未执行，属人工闭环缺失非框架缺陷。与存量关系：体检与聚合提醒机制本身工作正常（提醒逐日落库、龄期计数准确），闭环判定不成立、龄期加一天。结论：51 天欠账继续挂账，第 52 天提醒已在途。
  - 建议：①用户一次性按 .fenix/knowledge_audit_findings.json 的 13 条 escalated 指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定，框架自动消费后提醒即停；②采纳前窗建议把同指纹超 7 天未消费的聚合提醒降频为每周一拍，消除每日一拍的提交噪音。

- **归档spec冻结告警两条滞留critical无清账（恶化）**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：两条已归档 spec 的冻结类告警（spec 归档后其关联告警未联动闭合而滞留老化面）已满约 3 天无人清账，其中已升级 critical，较上窗登记时的「近一天」显著恶化，且归档与撤销终态的告警联动闭合缺口仍无承接。
  - 证据：告警 60b032af99b0（2026-11-16T16:43 UTC）与 b1b142eb677a（11-16T20:43 UTC）为归档 spec 的 frozen 类告警，handled=false 至本窗窗末满约 3 天（11-18 窗登记时龄期仅近一天）；git log 自 11-17 起无 admin_monitor 告警联动相关改动；admin-ops 域已有「SPEC 软删除联动关闭关联告警」能力（域导航页在案），归档与撤销终态不在其覆盖列。
  - 调查评估：核实：告警台账龄期与修复面代码只读回源，滞留持续、缺口未修。根因：告警生命周期联动只覆盖软删除终态，归档与撤销终态迁移不触发关联告警闭合，aging 升级面前也无终态核验，滞留告警沿老化阶梯升级至 critical。与存量关系：软删除联动为既有能力，扩展到归档与撤销终态属既有模式边界补全非新能力；前窗已登记、本窗零进展。结论：重述（恶化），龄期近一天到约 3 天。
  - 建议：①把软删除联动模式扩展到归档与撤销终态（spec 终态迁移时联动关闭关联 pending 与 aging 告警），或在 aging 升级前核验关联 spec 是否已终态、终态即静默闭合留痕；②两条存量告警人工清账，止住 critical 空挂。

## 2026-11-21

### 浪费
- **API停滞回升至63分钟，code-review车道首破30分钟预算线**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：窗口内 10 个 run 累计 API 停滞（单轮 API 往返等待超 60 秒的记账段）3789.3 秒约 63.2 分钟纯墙钟等待，为十三窗序列 92→370→175.5→210.1→174.0→51.1→78.8→31.7→416.6→68.2→50.7→18.6→63.2 的回升第一窗（18.6 为上窗回顾留痕值）；重灾区是夜间全仓代码审查 run 单 run 停滞 41.1 分钟、占其 3.8 小时时长的 18%。零失败零金额损失，损失面全在墙钟。
  - 证据：车道停滞预算告警 a61ce1ab10e6（lane_stall_daily_budget，code-review 车道当日累计超阈值的首条信号）创建于 11-19T19:51Z、severity=info、handled=False，原文自带口径「当日累计 2463s 超阈值 30 分钟……停滞已被编排层吸收、属墙钟税非报废」；run 档案回源逐项吻合：code-review-1795104099（夜间全仓审查 run）终态 run_metrics 记 26 次停滞/最长 182.0 秒、code-fix-1795125181 记 2 次/最长 226.5 秒、admin-fenixd-1795130729 记 1 次/66.9 秒；四车道合计由摘要逐 run 行精确自洽（code-fix 6 run 1052.8 秒、evolution 2 run 206.3 秒、administrator 1 run 66.9 秒、code-review 1 run 2463.3 秒）。
  - 调查评估：核实：合计 3789.3 秒由摘要 10 行逐 run 行相加重算吻合，抽 3 档案终态指标逐项核对一致；单轮超 300 秒升级线的 run 为零（全窗最长 226.5 秒），api_round_stall_escalated（单轮停滞超 300 秒的人工升级信号）窗内零出现与之吻合。新事实是车道预算信号首次真实触发——code-review 车道 41.1 分钟越过 30 分钟预算线，该记账与告警面出自已 pushed 的 evo-add-lane-stall-daily-budget-accounting（该 spec 仍滞留活跃区未归档，上窗已建议收尾）。根因未定、多假说并存（网关排队/长上下文/本地网络/provider 限流，既有留痕口径），告警自述 provider 拥塞候选、只荐观察。编排层救回痕迹仅 1 条：code-fix-1795122037 因连接故障从 glm-5.3-flash 换道 deepseek-flash 后照常收尾，属候选环 failover 按设计工作。初筛离群 run code-fix-1795125181（2305 秒为组中位 662 秒的 3.5 倍）经查收尾自述为双后台验证套件（定向 pytest 2383 项+前端 node 471 项）的合法工作时长、停滞仅占 358 秒，非浪费。另核实本窗唯一一次计划重启（11-19T22:50Z 陈旧自愈）排水 0 秒、零在飞被杀，系多窗「重启杀 run」后首次干净重启。结论：回升第一窗，按 2026-11-14 修正口径（连续回升两窗才动）出口试验条件未成立，留痕即可。
  - 建议：维持纯读侧不干预与「连续回升两窗」触发口径；推动 evo-add-lane-stall-daily-budget-accounting 归档收尾（已生效交付滞留活跃区第二窗）；下窗若再回升即按 run_metrics 的 model 字段出模型对照报告。

### 失误
- （当日无）

### 可改进
- **幻影成功分类缺口第七窗两条告警近7天无人消费**
  - 自进化：问题部分成立 / 建议不合理 / — 不需要
  - 影响：死于 429 限流（上游请求过量拒绝）的 run 仍会被收尾链按结果行存在记成 success（幻影成功，污染失败统计的分类缺口），两条自查告警龄期达 6 天 23 小时近 7 天无人消费，第七窗持续恶化；复发敞口为每次 429 收尾期复发都再污染成功统计并新增老化告警（11-14 窗实测单次复发伴生约 35 美元 run 报废）。
  - 证据：告警 cbfda9c9f490 与 aad34f3dea9b（self_review_phantom_failure 自查信号，分别指向裁决复核 run planner-judge-windows-native-support-1794499508-a1 与 1794503523-a1）created 均为 11-13T16:03Z、handled=false 至窗末近 7 天，即数据摘要「超24h 未处理提醒 2 条（已登记 6 天 23 小时）」本体；本窗零 429 事件（日志 grep 末次命中停留在 11-16）、runs 统计失败 0、零新实例；判别幻影的两个结构化标记为 exit_code 与尾部 <synthetic>（CLI 断流时以合成占位 assistant 消息代收尾的标记）。
  - 调查评估：核实：两告警台账 handled=false、窗内零 429、零新实例逐一度核。根因同前六窗：收尾分类以结果行存在为主判据，不交叉核验 exit_code 与尾部 synthetic 标记；自查信号按设计止于人工核对（负控豁免面正常），人工面七天未动作。与存量关系：run-resilience 域失败分类能力页无合成收尾形态覆盖；该修复建议在前窗自进化复核中被判「建议不合理」，框架车道不会自动承接，只能人工修码或人工清账——同族第三条 287fbb68e971 已按先例清账成功证明通道可行。结论：第七窗重述（恶化），龄期加一天、零新增实例，本窗零复发属 provider 平静非防线生效。
  - 建议：人工在收尾分类点补「exit_code 不为 0 且尾部 assistant 为 <synthetic> 时改记 failed/partial」小改，使失败统计不依赖自查信号兜底；两条告警比照 287fbb68e971 先例先清账止住提醒空转。

- **蒸馏欠账第4天major再落，接受批次空转4天14草稿滞留**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：两个已归档 spec 的知识蒸馏（归档件提炼知识页的车道）欠账进入第 4 天且窗末催办升级 major 仍零补账，归档件知识页持续缺位；同源的自进化接受闸门（worth_spec 条目等用户在设置页点同意才物化为 SPEC 的人工环节）连续约 4 天无接受批次，14 条草稿滞留队列、最老约 4 天，含两条可闭环既有缺口的承接种子。
  - 证据：告警 38e1a8c719e6（knowledge_distill_retry_stale 蒸馏重试欠账信号窗末一拍，11-20T16:02Z 即本地 11-21 00:02）原文「欠账 4 天、升级为 major」，与前三拍（aae995bcdf2b 等）全部 handled=false；.fenix/knowledge-distill-retry-state.json 实测 last_severity=major、last_reminded_date=2026-11-21；.fenix/evolution/items.jsonl 实测 pending 恰 14 条、最老 11-16T16:57Z，drafts 目录 14 个，与上窗完全相同即零消费；两欠账 spec（evo-impl-worktree-preservation-refs、evo-scenario-exec-tree-isolation）窗内零补账提交。
  - 调查评估：核实：催办节拍、重试状态文件、条目台账、drafts 目录四处只读回源，欠账升级与接受停摆双双实锤，且队列纹丝未动（最老条目时间戳与上窗逐字相同）。根因同前两窗：接受是设计内人工闸门（self-evolution 域能力页明文 auto_accept 缺省假时保持 pending 等用户决定），非调度故障；蒸馏欠账同样需人工补账或勾选台账行，自动面仅按 24 小时节拍催办并逐日升级。与存量关系：催办与升级机制（evo-add-distill-retry-ledger-aging）按设计工作；「决定不重试行无终局出口」缺口有 6033534dfc34 种子承接、quality-gates 写侧校验缺口有 deb14643f2be 种子承接，双双滞留队列，quality-gates 本窗零复发但缺口未修。结论：合并重述（恶化），两条线同源于人工闭环面未动作。
  - 建议：在 dashboard 设置页自进化页签对 14 条 pending 批量裁决（逐条同意或拒绝，优先放行 6033534dfc34 与 deb14643f2be 两条种子），或打开 self_evolution.auto_accept 根除排队；人工触发一次两 spec 蒸馏补账或勾选 todo 蒸馏待办行，止住 major 告警逐日升级。

- **知识体检疑点积压至52天仲裁文件仍未创建（恶化）**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：知识真相源体检（对 spec/knowledge 规则冲突与过期项的自动巡检）发现的 13 条待人工仲裁疑点积压至 52 天，仲裁登记文件至今未创建，每日一拍聚合提醒持续空转，属持续恶化的人工闭环欠账。
  - 证据：窗末成对提交 b8211c7f3（todo 聚合提醒「13 条待人工仲裁（最长龄期 52 天）」）与 65602e716（体检留痕）于本地 11-21 00:02 落库；上一拍 86462796a 为 51 天版，逐日加一的提醒序列完整；.fenix/knowledge_audit_arbitration.json（人工按 fingerprint/decision/decided_at/note 逐条登记仲裁决定、框架检查点自动消费的文件）实测不存在。
  - 调查评估：核实：提醒提交序列与仲裁文件存在性两处只读回源，积压持续、登记通道零进展。根因：仲裁动作只能由人工按指纹逐条登记（框架仅负责每日聚合提醒与龄期计数），用户侧长期未执行，属人工闭环缺失非框架缺陷。与存量关系：体检与聚合提醒机制本身工作正常；前窗已登记的「同指纹超 7 天未消费降频为每周一拍」提醒面改造建议未承接。结论：52 天欠账继续挂账，第 53 天提醒已在途。
  - 建议：用户一次性按 .fenix/knowledge_audit_findings.json 的 13 条 escalated 指纹登记仲裁决定，框架自动消费后提醒即停；同指纹超 7 天未消费的聚合提醒降频为每周一拍，消除每日提交噪音。

- **归档spec冻结告警两条滞留约4天critical无清账（恶化）**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：两条已归档 spec 的冻结类告警（spec 归档后其关联告警未联动闭合而滞留老化面）已满约 4 天无人清账，其中已升级 critical，人工面持续挂无效待办；归档与撤销终态的告警联动闭合缺口仍无承接。
  - 证据：告警 60b032af99b0（处置告警老化升级 warning，pending 超 120 分钟未人工处置时落账，11-16T16:43Z）与 b1b142eb677a（同族 aging critical，11-16T20:43Z），对象均为已归档的重复立项 spec evo-fix-self-review-window-gap，handled=false 至窗末约 4 天；admin-ops 域「SPEC 软删除联动关闭关联告警」能力（add-spec-softdelete-alert-linkage 交付）只覆盖软删除终态，归档与撤销不在覆盖列。
  - 调查评估：核实：两告警台账龄期与联动面覆盖范围只读回源，滞留持续、缺口未修。根因：告警生命周期联动只覆盖软删除终态，归档与撤销终态迁移不触发关联告警闭合，aging 升级器（pending 超时逐级加码的升级器）只看 pending 时长、不核验关联 spec 是否已终态。与存量关系：软删除联动为既有能力模式，扩展到归档与撤销属边界补全非新能力；前两窗已登记、本窗零进展。结论：重述（恶化），龄期约 3 天到约 4 天。
  - 建议：把软删除联动模式扩展到归档与撤销终态（spec 终态迁移时联动关闭关联 pending 与 aging 告警），或在 aging 升级前核验关联 spec 已终态即静默闭合留痕；两条存量告警人工清账。

## 2026-11-22

### 浪费
- **API停滞第十四窗回落至38.3分钟，出口条件持续不成立**
  - 影响：窗口内 10 个 run 累计 API 停滞（单轮 API 往返等待超 60 秒的记账段）2297.5 秒约 38.3 分钟纯墙钟等待，为十四窗序列 92→370→175.5→210.1→174.0→51.1→78.8→31.7→416.6→68.2→50.7→18.6→63.2→38.3 的回落窗；零失败零金额损失，三车道日累计全部低于 30 分钟预算线、零预算告警。
  - 证据：数据摘要第 6 节车道级日汇总三行相加：code-fix 1150.0s/7run、code-review 421.6s/1run、evolution 725.9s/2run＝2297.5s；抽 code-fix-1795242082（code-review 台账修复 run）终态 run_metrics 原值核对吻合（daemon 日志 2026-11-21T06:43:06Z run metrics 行：latency_stalls=2、latency_max=128.713、stall 合计 254.826）；本窗唯一单轮超 300 秒升级线的样本为 evo-1795191422（自进化复核 run）max=347.5s、终态 success（档案 result 行收尾 $9.04），api_round_stall_escalated（单轮停滞超 300 秒的人工升级信号）窗内零出现属 success 豁免面的设计内沉默；窗内 lane_stall_daily_budget（车道停滞日累计超阈值信号）零出现。
  - 调查评估：核实：合计按摘要逐 run 行相加重算，抽 1 档案终态指标逐项吻合，唯一超线样本的终态与豁免面核对一致；两窗合计 63.2+38.3=101.5 分钟未越过 150 分钟对照线。根因沿用多假说并存口径（网关排队/长上下文/本地网络/provider 限流，既有留痕），不预设。与存量关系：检测、记账与车道日预算三层（evo-add-lane-stall-daily-budget-accounting 交付）持续在账生效；出口试验按 2026-11-14 修正口径（停滞合计连续回升两窗才动）本窗不成立——上窗 63.2 为回升第一窗、本窗即回落。另发现上窗越线的存量告警 a61ce1ab10e6（code-review 车道预算越线 info，11-19 创建）仍 handled=False 挂账，其越线窗口已翻页、留账只添提醒噪音。结论：有利走势留痕，零代码动作。
  - 建议：维持纯读侧不干预与「连续回升两窗」触发口径不动；顺带人工清账 a61ce1ab10e6 这条已过时的 info 告警。

### 失误
- （当日无）

### 可改进
- **夜审79文件零覆盖仍记成功，覆盖对账门缺失**
  - 影响：11-21 夜间全仓代码审查 run 跑 2.08 小时、花费 109.79 美元，但审查范围 362 个文件中 79 个（21.8%）无任何审查产出，当轮审查价值缩水约两成；run 被记 success、零告警，覆盖缺口只能靠次夜全量审查兜底（延迟约 24 小时），且当轮未安排任何续审。复发敞口=每次父 run 提前收工或批次静默失败都再现两成级缺口且不可见。
  - 证据：审查清单 manifest-code-review-1795190463.json 记 scope 362 文件；.fenix/code-review/ 下 34 个分片（out-*-bNN.jsonl，批内直写落盘的审查产物）合计仅覆盖 283 文件、差集 79；对照前夜 code-review-1795104099（同 scope 362、43 分片、覆盖 360、缺口 2 即 0.6%）证本窗为异常。run 结果行自述「b39 已派出。在飞 3 个（b32/b38/b39）」——父 run 带 3 个在飞批次收工（stop_reason=end_turn），stderr 记 CLI 在最后一轮 10 分钟后停止后台批次（subagent 审查批次 b38（5 文件）/b39（8 文件））；实测 b32 分片仅 1 文件、b38 4/5、b39 2/8，批号 b8/b11/b14/b15/b18 零分片；次夜 manifest-code-review-1795277035.json 的 redispatch_of=None 即无续审挂接。
  - 调查评估：核实：覆盖差集由 manifest scope 与 34 个分片逐文件对账重算得出，前夜基线同法对照；3 个在飞批次与 5 个零分片批号从分片清单与结果行原文核实。根因分层：在飞 3 批次被停是父 run「派完即收」与 CLI 10 分钟后台宽限的形态碰撞；而占大头的 5 个零分片批号（合计约 64 文件）根因未定、假说并存——子代理静默死亡零产物、Task 派发失败未留痕、或父 run 批次计划结构性偏短（前夜同 scope 需 43 批、本夜仅派到 b39），证据不足不裁决。机制缺口确定：success 终态的审查 run 不做 scope↔分片覆盖对账，code-review-lane 域现行能力页的分片直写落盘、进度聚合、停滞看门狗、限流终局续跑与 writeoff 锚续审均不以「干净收尾但覆盖不全」为触发面。与存量关系：2026-11-12 窗建议的即时 redispatch 针对排水硬杀触发面，本窗是无打断的干净收尾形态，属新缺口非重复。结论：对账门缺口确定性可修，当轮实损约两成覆盖。
  - 建议：审查收尾聚合以 manifest scope 为单源做覆盖对账：缺口超阈值（如 2%）即不记纯 success——改记 partial 并武装 redispatch 续审（复用既有 redispatch_of/writeoff 锚机制）或在台账显式登记未覆盖文件清单；同时对「批次号已消耗但零分片」形态补派发侧留痕（Task 派发失败与子代理零产物落事件行），使下例根因可裁决。

- **散件WIP核销只覆盖基线信号，裁决后3条链上告警悬置**
  - 影响：用户已裁决主树 16+4 个滞留文件全量提交（提交 e62a0200a，11-21 11:18），工作树转净、两条基线信号已自动核销，但第 11 度人工升级告警与第 12 度处置链两条共 3 条告警仍 pending，将持续挂超期提醒面并沿老化阶梯升级；复发敞口=每次同类事件都以「基线核销、链上悬置」收尾，链上告警靠人工逐条清账。
  - 证据：提交 e62a0200a（20 文件：16 modified+4 untracked，提交说明自载指纹 b2409791a7c421ad 与用户裁决全量提交）；daemon 日志 2026-11-21T03:18:57Z「maintree_stray_wip_stale: 认领核销 1 条已写回（指纹文件集全部入库且集合 clean）」——距提交仅 16 秒；当前主树 git status 零输出（零脏零 untracked）；核销实现 core/worktree_manager/stray_wip.py:829-831 按 kind==SIGNAL 过滤候选——升级（kind=escalation）与处置（kind=disposition）条目设计上不在核销面；告警台账 4cfe4cd1b14d（第 11 度人工升级告警，11-19T23:31Z）、f65493462940（第 12 度处置中标记）、aa6b451d461d（第 12 度复发再告警）三条 handled=False，数据摘要超 24h 提醒面仍载 4cfe4cd1b14d（已登记 40.5 小时）。
  - 调查评估：核实：提交内容（git show 20 文件与说明）、核销日志时刻、代码过滤面、三条告警 handled 状态逐一度核。根因：认领核销机制（evo-add-stray-wip-claim-reconcile 交付）的署名互斥条款刻意把人工处置轮排除在自动核销外（防误核销吞掉真问题，保守侧正确）；但本形态下升级告警的推荐菜单（16 文件归宿三选一）已因全量提交失去对象，「指纹文件集全部入库+集合 clean」的机械判据同样成立，链上条目却不跟进，形成「问题已解、告警不灭」。与存量关系：stray-wip-claim-reconcile 能力页只载基线信号核销语义；与归档 spec 冻结告警不联动闭合条目同属「告警生命周期与终态无联动」家族，但触发面（认领核销命中）不同、不重复。结论：单次代价 3 条告警人工清账，机制缺口确定性可修、小改。
  - 建议：认领核销命中时对同指纹的 escalation/disposition 链上条目做联动收口或注记（resolve_note 带覆盖提交 SHA、保留人工追认位）；短期人工把 3 条告警按先例清账（handled=true 并注记指向提交 e62a0200a）。

- **幻影成功分类缺口第八窗，两条告警满8天无人消费**
  - 影响：死于 429 限流（上游请求过量拒绝）的 run 仍会被收尾链按结果行存在记成 success（幻影成功，污染失败统计的分类缺口）连续第八窗未修复；两条自查告警龄期恰满 8 天无人消费；本窗零 429 事件、零新实例，修复缺位下每次 429 收尾期复发都会再污染成功统计（11-14 窗实测单次复发伴生约 35 美元 run 报废）。
  - 证据：告警 cbfda9c9f490 与 aad34f3dea9b（self_review_phantom_failure 自查信号，分别指向裁决复核 run planner-judge-windows-native-support-1794499508-a1 与 1794503523-a1 的收尾疑点）created 均为 2026-11-13T16:03Z、handled=false 至窗末恰 8.0 天（数据摘要「已登记 8 天 0 小时」两条即此）；窗内 API 429 类事件精确检索计数为 0、runs 统计失败 0；判别幻影的两个结构化标记为 exit_code 与尾部 <synthetic>（CLI 断流时以合成占位 assistant 消息代收尾的标记）。
  - 调查评估：核实：两告警台账 handled 状态、窗内零 429、零新实例逐一度核。根因同前七窗：收尾分类以结果行存在为主判据、不交叉核验 exit_code 与尾部 synthetic 标记；自查信号按设计止于人工核对（负控豁免面正常），人工面八天未动作。与存量关系：该修复建议在前窗自进化复核中被判「建议不合理」，框架车道不会自动承接，只能人工修码或人工清账——同族第三条 287fbb68e971 已按先例清账成功证明通道可行。结论：第八窗重述，本窗零复发属 provider 平静非防线生效。
  - 建议：人工在收尾分类点补「exit_code 不为 0 且尾部 assistant 为 <synthetic> 时改记 failed/partial」小改，使失败统计不依赖自查信号兜底；两条告警比照 287fbb68e971 先例清账止住提醒空转。

- **蒸馏欠账第5天major再落，接受批次空转5天队列涨至16条**
  - 影响：两个已归档 spec 的知识蒸馏（归档件提炼知识页的车道）欠账进入第 5 天（登记 11-17）零补账，窗末第 5 拍 major 催办告警落账；同源的自进化接受闸门（worth_spec 条目等用户在设置页点同意才物化为 SPEC 的人工环节）连续约 5 天无接受批次，pending 队列从 14 条涨至 16 条、两条可闭环既有缺口的承接种子继续滞留，属持续恶化。
  - 证据：告警 cfe4d03e869a（knowledge_distill_retry_stale 蒸馏重试欠账催办信号第 5 拍，2026-11-21T16:04Z=本地 11-22 00:04）与前一拍 38e1a8c719e6 均 handled=false；.fenix/knowledge-distill-retry-state.json 实测 last_severity=major、last_reminded_date=2026-11-22；.fenix/evolution/items.jsonl 实测 pending 恰 16 条（上窗 14）、最老 13dbc65e1557 登记 2026-11-16T16:57Z，drafts 目录 16 个；新增 2 条系 11-21 自省条目自动登记（5ae00be13f08「知识体检疑点积压至52天」与 1db75a2d7775「timelib守卫主树连红4天半」，登记于本地 11-21 00:47），其中 timelib 一条当天已被 code-fix 批次修复（提交 4fec3994c）致其 pending 语义过时；两欠账 spec 窗内零补账提交。
  - 调查评估：核实：催办节拍（第 5 拍）、重试状态文件、pending/drafts 计数 14→16、新增条目来源与时刻逐一度核。根因同前三窗：接受是设计内人工闸门（self-evolution 域能力页明文 auto_accept 缺省假时保持 pending 等用户决定），蒸馏欠账需人工补账或勾选台账行，自动面仅按 24 小时节拍催办并维持 major。与存量关系：6033534dfc34（蒸馏「决定不重试」行终局出口+unrecognized_model 瞬态改判）与 deb14643f2be（quality-gates.json 写侧校验）两条承接种子仍在队列滞留；队列反向增长证明纯提醒无法收敛。结论：合并重述（恶化），新增事实是队列 14→16 与登记条目本身过时（timelib 已修）。
  - 建议：在 dashboard 设置页自进化页签对 16 条 pending 批量裁决（逐条同意或拒绝，优先放行 6033534dfc34 与 deb14643f2be 两条种子），或打开 self_evolution.auto_accept 根除排队；人工触发一次两 spec 蒸馏补账或勾选台账行；已被修复兑现的条目（timelib 守卫）裁决时直接拒绝以免空转立项。

- **知识体检疑点积压至53天，仲裁文件仍未创建（恶化）**
  - 影响：知识真相源体检（对 spec/knowledge 规则冲突与过期项的自动巡检）发现的 13 条待人工仲裁疑点积压至 53 天，仲裁登记文件至今不存在，每日一拍聚合提醒继续空转并在窗末落库第 53 拍，属持续恶化的人工闭环欠账。
  - 证据：成对提交 443333304（todo 聚合提醒「13 条待人工仲裁（最长龄期 53 天）」）与 b2b4a0064（体检留痕）于本地 2026-11-22 00:04 落库；上一拍 b8211c7f3 为 52 天版，逐日加一的提醒序列完整；.fenix/knowledge_audit_arbitration.json（人工按 fingerprint/decision/decided_at/note 逐条登记、框架检查点自动消费的仲裁文件）实测不存在。
  - 调查评估：核实：提醒提交序列与仲裁文件存在性两处只读回源，积压持续、登记通道零进展。根因：仲裁动作只能由人工按指纹逐条登记（框架仅负责每日聚合提醒与龄期计数），用户侧长期未执行，属人工闭环缺失非框架缺陷。与存量关系：体检与聚合提醒机制本身工作正常（提醒逐日落库、龄期计数准确）；「同指纹超 7 天未消费降频为每周一拍」的提醒面改造建议连续四窗未承接。结论：53 天欠账继续挂账，构成提醒面提交噪音与知识矛盾悬置双重成本，第 54 拍已在途。
  - 建议：用户一次性按 .fenix/knowledge_audit_findings.json 的 13 条 escalated 指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定，框架自动消费后提醒即停；或采纳降频改造建议（同指纹超 7 天未消费降为每周一拍）消除每日提交噪音。

- **归档spec冻结告警两条滞留约5天critical无清账（恶化）**
  - 影响：两条已归档 spec 的冻结类告警（spec 归档后其关联告警未联动闭合而滞留老化面）已满约 5 天无人清账，其中一条已升级 critical，人工面持续挂无效待办；归档与撤销终态的告警联动闭合缺口连续第四窗无承接。
  - 证据：告警 60b032af99b0（处置告警老化升级 warning，pending 超 120 分钟未人工处置时落账，11-16T16:43Z）与 b1b142eb677a（同族 aging critical，11-16T20:43Z），对象均为已归档的重复立项 spec evo-fix-self-review-window-gap，handled=false 至窗末约 5 天（4d23h/4d19h）；admin-ops 域「SPEC 软删除联动关闭关联告警」能力（add-spec-softdelete-alert-linkage 交付）只覆盖软删除终态，归档与撤销不在覆盖列。
  - 调查评估：核实：两告警台账 handled=false、龄期、联动面覆盖范围只读回源，滞留持续、缺口未修。根因：告警生命周期联动只覆盖软删除终态，归档与撤销终态迁移不触发关联告警闭合，aging 升级器（pending 超时逐级加码的升级器）只看 pending 时长、不核验关联 spec 是否已终态。与存量关系：软删除联动为既有能力模式，扩展到归档与撤销属边界补全非新能力；前三窗已登记、本窗零进展。结论：重述（恶化），龄期约 4 天到约 5 天。
  - 建议：把软删除联动模式扩展到归档与撤销终态（spec 终态迁移时联动关闭关联 pending 与 aging 告警），或 aging 升级前核验关联 spec 已终态即静默闭合留痕；两条存量告警人工清账。

- **纯文本轮通胀命中code-review车道首窗，model字段回填退化**
  - 影响：纯文本轮离群维（无工具调用的模型回复轮，轮数>100 且占比>50%）本窗命中夜审 run（事件侧聚合 2364 轮中 1193 轮纯文本、占 50.5%），为 code-review 车道首窗命中——至此七类车道均已命中过该形态；按现行响应规则（同车道连续两窗命中才做收敛试验）本窗仅留痕，复发敞口为同车道下窗再命中即触发一轮对照试验；另发现 run_metrics 的 model 字段本窗为 null，历窗「字段齐备可支撑对照」的前提出现退化。
  - 证据：数据摘要初筛离群行 code-review-1795190463（text_turns=1193/2364，50.5%）；该 run 34 个分片直写落盘完整，被停后台批次 b38/b39 的分片各含完整 JSON 行（b38 4 文件含 findings、b39 2 文件），stderr「Background tasks still running 10m after the last turn…stopping them」未造成分片损坏；终态 run_metrics 行 turns=3（父 run 为编排层、2364/1193 为事件侧子代理聚合）、duration 7492.7s、$109.79 与前夜 103.6-115.3 美元基线持平、model=null（run 头部 provider_marker 行记 bigmodel.cn/glm-5.3-flash）；本窗 impl 与 planner 车道零命中。
  - 调查评估：核实：离群原始值按摘要与分片/指标行双源核对一致；model=null 与 provider_marker 的 glm-5.3-flash 并存，说明终态指标行的 model 回填在本窗未生效（历窗如 11-18 曾逐 run 齐备），具体缺失源未核实。根因未定（模型输出行为漂移假说，检测 spec 原文口径）。与存量关系：响应机制 evo-text-turn-inflation-response 的输出纪律仅覆盖 planner-plan 车道；现行触发口径下 code-review 车道记首窗、留痕即可；11-21 窗命中的 impl 车道本窗零命中、连窗计数归零。结论：留痕条目，两个观察点——code-review 同车道连窗计数起点、model 字段回填需在收敛试验触发前修复。
  - 建议：留痕 code-review 车道首窗；若下窗同车道再命中即按现行规则做模型对照与提示词收敛试验；顺带核查 run_metrics model 字段本窗为 null 的回填缺口（对照 11-18 窗回填生效的 run 形态找差异），避免触发收敛试验时无字段可对照。
