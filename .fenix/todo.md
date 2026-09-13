## 2026-09-13

### 浪费
- **两轮 implementer 零提交白跑 $24**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：两起 [terminal-no-commit] 拦截各消耗一整轮 try：fix-run-latency-toolresult-parser（$12.05，worktree 1 个未提交产物）与 add-stale-code-selfheal（$12.13，worktree 11 个未提交产物），均回退 ready + 退避后重新派发，合计约 $24 白跑并延迟两 spec 完成。
  - 证据：fenixd.log 3992/4445 行 'Agent run exception: [terminal-no-commit] 归因:未提交即收工'（03:25:54Z 与 07:04:28Z）；runs/impl-fix-run-latency-toolresult-parser-1789176437-a1 与 impl-add-stale-code-selfheal-1789194797-a1 的 total_cost_usd 分别为 12.052304 与 12.1257625；配套 WARNING 显示两 spec 均被 Rolled back implementing → ready。
  - 调查评估：已核实：两条 ERROR 与对应 run 成本从 runs/ jsonl 直接读到，目标 spec 与回退动作在 3994/4447 行 state_machine 更新中吻合。根因：implementer 在 fast-track 下终止时未提交产物（归因 '未提交即收工'），gate 拦截成功避免污染主树，但消耗了一轮 try 的 token。与存量 SPEC 关系：add-impl-terminal-nocommit-gate、add-impl-wip-checkpoint 正在飞（后者 verification-report 已生成），本案即该防线的触发记录，属 gate 生效后的预期内损耗；残余缺口在投射侧引导而非拦截侧。结论：单次约 $12 的重复 try 成本，复发敞口明确，建议从发生概率（implementer 收工提示）侧再削减。
  - 建议：在 implementer system prompt / 收工契约中强化「有产出必须 git commit」的强制步骤（如收工前 lint 清单包含提交检查），把 terminal-no-commit 从『拦截后重试』前移为『投射时预防』，降低每次 $12 级白跑概率。


## 2026-09-14

### 浪费
- **add-framework-self-evolution fast-track 12600s 超时**
  - 影响：impl-a1 281 rounds 后超时被杀（3.5h 空转），a2 仅 42 turns 收尾，说明 a1 大部分工作未保全；总延迟从 15:50Z 到 21:13Z ≈ 5.4h 才完成实现阶段
  - 证据：fenixd.log 5552 行 2026-09-12T19:21:05Z 'Timeout after 12600s — extension budget exhausted (2/2) | run impl-add-framework-self-evolution-1789228219-a1: 281 rounds, median 12.4s'；5554 行 19:21:15Z attempt 2 启动，5589 行 21:13:37Z a2 42 turns 成功（flash 模型）；scale-precheck 合并时间 09-13 06:07Z（52f117cf），超时发生在合并前
  - 调查评估：已核实：281 rounds 超时与 a2 快速成功均从 fenixd.log 直接读到，spec 最终 merge 成功（0ea0574e 09-13 07:21 本地）。根因与 [2026-09-13#浪费#1] import-shadow 完全同源：fast-track 统一 3.5h 硬限无法容纳大 spec。与存量 SPEC 关系：evo-add-fast-track-scale-precheck（6f279a19/52f117cf，09-13 06:07Z merge）已实现规模预估+派发预检+extension 末位 WIP 保全+higher 档提额，本超时发生在该 SPEC 合并前约 11 小时，是修复落地前的最后一大规模案例（对照同窗口内小 spec 均单轮成功）。结论：与 [2026-09-13#浪费#1] 同类复发，验证了规模预检需求的正确性；scale-precheck 已合并后窗口内无新超时，问题应已覆盖，残余在 daemon 是否重启拾取新代码。
  - 建议：确认 daemon 在 scale-precheck 合并后已重启拾取新代码（stale_code_selfheal 机制）；若 daemon 未重启则规模预检逻辑尚未生效，需手动触发重启

- **fix-run-hang-amplification 三连 implementer 中断**
  - 影响：3 次 implementer 中断（35+145+93=273 rounds 白跑）+ 1 个 admin run（19 rounds 诊断）后第 4 次（36 rounds）才成功，总消耗 345 rounds + 1 admin run，spec 完成延迟约 3.5h（07:19Z→10:46Z）
  - 证据：fenixd.log 7047 行 07:29:51Z impl-1789283942-a1 Exit 143（35 rounds）；7145 行 08:56:03Z impl-1789284770-a1 Exit 1（145 rounds, 12% stalls）；7182 行 10:33:33Z impl-1789284770-a1-r1 Exit 143（93 rounds, 1742s max stall）；之后 10:46:31Z r2 36 rounds 成功。窗口内无 daemon Shutdown 记录（07:00-11:00Z），两次 Exit 143（SIGTERM）来源不明；每次中断均触发 WIP checkpoint 保全，最终 WIP collapse 合并（10:46:35Z 2 commits collapsed）
  - 调查评估：已核实：四次 run 的轮数/退出码/时间戳均从 fenixd.log 直接读到，WIP checkpoint 与 merge 记录吻合。根因不明：窗口内无 daemon Shutdown 记录，两次 Exit 143（SIGTERM）非 daemon 重启所致；Exit 1 可能是 CLI 错误；可能是 provider 端中断或 daemon 看门狗判定 hung 后 kill。与存量 SPEC 关系：该 spec 正是修复 hang amplification 的，讽刺的是实现过程本身被反复中断——若 hang 检测机制误杀了自己（实现 hang detection 的 implementer 被 hang watchdog 判定为 hung），则属自指 bug。三次中断共 273 rounds 浪费，WIP 保全链有效但中断代价显著。结论：浪费成立，中断根因需进一步排查（hang watchdog 是否误杀自己？）。
  - 建议：排查 daemon watchdog/stuck_threshold 对 implementer run 的判定逻辑是否与 hang-discrimination 修复后的阈值冲突；确认 fix-run-hang-amplification 的自身 run 是否被自己引入的新检测误杀

- **evo 分析 run 两连败后第三轮才成功**
  - 影响：evo-1789260732（36 rounds, drain 等 972s 后 SIGTERM, 产物未落盘）+ evo-1789262165（22 rounds, Exit 143）共 58 rounds 白跑 + 16min drain 等待 + 2 条 admin 升级告警，第三次 evo-1789262556（55 rounds）成功
  - 证据：fenixd.log 6248 行 01:11:00Z drain 972s 后 SIGTERM 杀 evo-1789260732（36 rounds）；6251 行 '产物 JSON 不可读: No such file out-evo-1789260732.json'；6278 行 01:21:19Z evo-1789262165 Exit 143（22 rounds）；6289 行 01:45:09Z evo-1789262556 成功落地（55 rounds, 就绪 4 项目, 条目 20）；evolution/state.json 显示 last_run_id=evo-1789262556
  - 调查评估：已核实：时间链从 fenixd.log 行 6248-6289 逐条确认。0732 失败根因：daemon stale_code_selfheal 00:54Z 触发计划重启，drain 等待 evo run 972s 后 SIGTERM 杀掉，产物从不落盘（run 被 SIGTERM 打断时无机会写盘）。commit 3983bb6d（09-13 01:55Z 提交「修复自进化分析 run 契约产物从不落盘」）在失败后 44min 修复。165 失败根因不明（01:21Z Exit 143，01:20:36Z 有 config hot-reload 但未见 Shutdown）。与存量关系：3983bb6d 修复产物落盘 bug，stale_code_selfheal 的 drain 行为本身未改（仍会 SIGTERM 长 run）。结论：58 rounds + 16min 浪费成立，产物落盘 bug 已修，但 drain 对 evo run 的强杀策略仍可改进。
  - 建议：evo run 纳入 drain 保护清单（或 evo 分析改为写盘 checkpoint 模式：每轮迭代持久化中间结果，SIGTERM 后可从最近 checkpoint 恢复而非从零重跑）

### 失误
- **dispatch_stalled 竞态误报触发无效 admin run**
  - 影响：recovery watch 在 implementer 成功后 20s 内误判 stale 并升级 dispatch_stalled，触发 1 个 admin run（1789247771, 9 rounds），3min 后自动确认为竞态误报结案
  - 证据：fenixd.log 5589 行 21:13:37Z implementer succeeded；5596 行 21:13:57Z Recovery watch failed 'still stalled in ready'（距 succeed 仅 20s）；5617 行 21:16:11Z admin_monitor invoking Administrator；admin_alerts.json admin run 1789247771 完成于 21:19:25Z，结论 'dispatch_stalled 信号为竞态误报：recovery watch 判定 stale 后 5 秒系统即自愈'
  - 调查评估：已核实：时间链与 admin run 结论均从 fenixd.log 与 admin_alerts.json 直接读到。根因：recovery watch 检查间隔（15min recheck）与 implementer→merge 过渡窗口（implementer succeed → worktree merge → state transition 约 5-25s）存在竞态——recovery watch 在 implementer 成功但 merge 未完成的窗口内检查，读到 'implementing' 状态判定 stale。与存量：无对应 SPEC，属 recovery watch 逻辑的固有竞态窗口。结论：单次 admin run 代价小（9 rounds），但暴露 recovery watch 判定未考虑 'pending merge/transitioning' 状态的系统性缺陷，可能在其他 spec 上重复误报。
  - 建议：recovery watch 判定 stale 前增加 pending-merge 检查（worktree_manager 是否有待合并分支），或在 implementer succeed 信号后重置 recovery watch 计时器

### 可改进
- **场景生成侧 schema 持续不合法导致 100% 剔除**
  - 影响：两批次场景写端校验 100% 剔除：scale-estimate 系列 25/25（output_match 缺 expected）、blind-run-marker 系列 17/17（json_output 缺 step），合计 42 条场景全废；每批触发 plan 阶段退回+重排+重新生成 planner（各消耗一轮 planner run），回退后用 synthesis fallback 场景通过验收
  - 证据：fenixd.log 6884 行 06:55:24Z '剔除 25/25 条非法条目（超本轮20%）: scale-estimate-* 等 output_match 需要 expected'；6958 行 07:08:13Z '剔除 17/17 条非法条目: blind-run-marker-* 等 json_output 需要 step'；两次剔除均在 evo-add-frozen-scenario-schema-migration merge（17650012, 06:49Z）之后；06:55:24Z 触发退回 plan+重跑 planner（1789282524）；report.json 最终 25/21 场景全 pass（回退 fallback 场景）
  - 调查评估：已核实：两批次剔除均从 fenixd.log 直接读到，场景名与 spec 对应关系从 verify-progress/report.json 确认（evo-add-fast-track-scale-precheck 25 scenarios, evo-add-self-review-run-semantics 21 scenarios）。根因：planner 生成场景时使用的断言模板与写端校验规则不一致——output_match 断言缺 expected 字段、json_output 断言缺 step 字段，属于 schema 漂移（生成侧未跟随校验侧演进）。与存量关系：[2026-09-13#可改进#1] 冻结场景 schema 失配已由 evo-add-frozen-scenario-schema-migration（17650012）修复读侧，但写侧（生成器）的断言 schema 仍不合规——迁移解决了「旧文件加载」但未解决「新场景生成」。结论：系统性缺口成立，写端校验成功拦截（防御有效），但生成侧持续产出无效场景 = 每次 planner run token 白费 + 场景集不更新（依赖 fallback 回退），可独立立项。
  - 建议：起草 SPEC：planner 场景生成与写端校验共用 schema 定义（单源断言 schema），在 planner system prompt 中注入当前合法断言模板（output_match 必含 expected、json_output 必含 step），或在 planner 产出后增加客户端预校验（写盘前拦截）避免整批剔除
