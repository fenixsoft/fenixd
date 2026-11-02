
## 2026-11-02
### 知识真相源
- audit 疑点升级待人工（聚合）：10 条待人工仲裁（最长龄期 34 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

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
