## 2026-09-18

### 浪费
- **孤儿交付物声明致重构空转 78 分钟**
  - 影响：已完成 37/37 任务的巨型重构 spec 因一条从未被要求创建的交付物声明卡在 blocked 空转约 78 分钟（16:37Z→17:53Z），期间下游依赖 spec 每轮巡检被拒，另耗 44 分钟 admin 人工裁决并连带一次 dispatch_stalled 误报升级。
  - 证据：2026-09-17T16:37:29Z 交付物守卫缺件异议 tests/test_giant_classes_contract.py（全仓/全历史零引用）置 blocked（run=impl-refactor-giant-classes-1789641481-a2）；17:09Z blocked_stuck 信号 bfbcffb0b07a 唤起 admin；bd1a309e（09-18 01:48 本地）机械删除孤儿声明后三道门归零；4056032c（01:55 本地）合并完成；.fenix/admin_disposition-admin-refactor-giant-classes-1789664978.json 自述「76 分钟空转」。
  - 调查评估：已核实：bd1a309e 提交信息确认 tests/test_giant_classes_contract.py 全仓 grep 命中=1（仅声明行自身）、tasks.md 37 条任务无此交付需求、design/proposal/spec 三文档无提及；admin 处置记录详述 blocked→处置完成 76 分钟空转、处置本身 44 分钟。根因：spec 立项（commit 8dd71903）时声明了从未要求的交付物，交付物守卫（按分支 HEAD 对账声明文件是否存在、缺件即 blocked 的机制）与实现者 deliverable-dispute 异议（实现者对缺件提出异议、待人工裁决的通道）僵持——守卫「质疑不得自动放行」设计正确，但裁决无自动出口，而孤儿声明本可由机械事实判定。与存量关系：add-declaration-premechanize 只覆盖另一形态，无 spec 覆盖裁决通道缺口；16:33 的 dispatch_stalled（派发滞留升级告警）系 recovery watch 复查与 blocked 写入竞态产物，admin 已定性。结论：声明残留 + 裁决无自动出口的一次空转浪费，建议可立项（见 improvements）。
  - 建议：为 dispute 裁决通道补孤儿声明机械预分类（缺件路径在全仓/全历史/任务清单三方零引用 → 直接机械删除并留审计），并把「声明路径在任务清单零出现且全仓零引用」纳入晋升期 lint_declared 检查。

- **场景缺陷三耗改道预算致测试卡 264 分钟**
  - 影响：同一 spec 的场景缺陷 5 小时内 3 次耗尽改道预算升级人工（深度 2→1→1），spec 卡 testing 264 分钟越过 260 分钟阈值触发 blocker，期间下游 fix-robustness-edge-cases 每轮巡检被依赖拒绝，重复验证轮次白耗。
  - 证据：fenixd.log 16319/16619/17781 行：09-16T19:43:13Z / 19:50:58Z / 09-17T00:21:01Z 三条「场景缺陷改道预算耗尽 'fix-dashboard-read-path-performance'（深度 2/1/1）— 升级人工」；19:48:18Z 改道门触发「失败 2 个全部显式 test-defect/flaky（{'test-defect': 2}），product-bug=0」；00:15:34Z blocker「Stuck in 'testing' for 264 minutes (threshold: 260.0m)」。
  - 调查评估：已核实（fenixd.log 16319-17781 行）：该 spec 合并后进入 verify（18 个场景），judge 两次收敛到 2 个 test-defect（场景自身缺陷归类，非产品缺陷）失败，场景缺陷改道门（add-scenario-defect-triage-gate 建立的让 planner 修场景的通道）触发；改道后重跑仍同缺陷，改道预算（修场景的次数上限）耗尽升级人工，人工收尾后 spec 最终 pushed（STATE.md status=pushed）。根因：改道机制只按次数预算运行，改道修复是否真正生效缺中途校验——改道后仍是同一批 test-defect，说明改道无效或场景缺陷顽固，白白消耗到预算尽头才升级。与存量关系：add-scenario-defect-triage-gate（2026-09-15 已归档）已建门，本次是门内预算耗尽的升级路径，残余缺口为「改道无效时止损」判据缺失。结论：一次性重复验证轮次浪费，同类场景缺陷再发生属复发敞口。
  - 建议：核查 fix-dashboard-read-path-performance 验证场景中两个 test-defect 的根因是否已修；为场景缺陷改道增加「改道后重跑仍同批失败 → 提前止损升级人工」的判据，避免预算耗尽才升级。

### 失误
- **毒化选择器致判官 6 轮冻结且同型漏修**
  - 影响：选择器毒化使 6 个验证场景在输入框 type 步骤集体超时，judge（验证失败归因并原地修复后重跑的判官）连续 6 轮收敛同一失败集、越过 _MAX_JUDGE_RERUNS=5 重跑硬上限冻结 blocked，且第一轮修复漏掉同型函数致 1.2 小时后二次修复才根除。
  - 证据：commit 92228d33（09-17 21:52，core/verify_contract.py）：quick-links-standalone-sync 连续 6 轮 judge 收敛同一失败集（29 场景 23 通过/6 失败，失败步骤逐轮一致），根因 origin 正则对 test_scenarios.json 全文替换、把 input[placeholder='https://example.com'] 选择器字面量改写成实例地址；commit df4fbb8c（09-17 23:02，core/pm_engine/verification/serving.py）：披露同型函数 _rewrite_scenario_port 同样对整份文本跑端口正则，自述「92228d33 的提交信息虽声明『只碰导航目标字段』，但该契约未施加到此函数」。
  - 调查评估：已核实两 commit 全文：92228d33 完整记录毒化机制（正则落进 CSS 属性选择器→选择器永不匹配 DOM→判官每轮归类 test-defect 并修、修了又被下轮全文改写毒化→死循环至硬上限冻结）；df4fbb8c 明确「契约未施加到端口兄弟函数」，修复后抽公共骨架 _rewrite_scenario_target_values 并加 4 项回归。根因：同一「场景文本改写」逻辑存在两份实现（rewrite_scenarios_origin 与 _rewrite_scenario_port），第一轮 root cause 修复未横向排查同型函数——提交信息虽提到「存量库中 add-info-aggregation-panel 等 spec 的断言选择器含同类内嵌 URL 形态，为潜在同型事故」，但未当场 grep 收齐。与存量关系：无独立 spec，属直接修复，df4fbb8c 已根治（两函数统一骨架）。结论：执行层失误，根因修复不彻底，代价为 6 轮 judge 重跑 + 冻结处置 + 二次修复。
  - 建议：修复「对同一文件做全文正则改写」类缺陷时先 grep 同型函数（rewrite_/改写 前缀）一次收齐再改；df4fbb8c 已落共享骨架，补充「全部改写函数必须走同一实现」的结构性测试防回退。

- **声明路径漂移致守卫缺件走异议闭环**
  - 影响：交付物守卫按失效路径 core/dashboard/data.py 对账缺件将 spec 置 blocked 待裁决（阻塞约 4 分钟即经异议闭环解除），暴露「spec 评审实测的绝对路径在实现期因同批前序重构落地而漂移」的时序脆弱，同类问题还令分支携带过期测试副本。
  - 证据：09-17T06:49:34Z ERROR「交付物守卫缺件异议 'fix-observability-gaps'（core/dashboard/data.py）— blocked 待裁决，run=impl-fix-observability-gaps-1789617176-a1」；commit 814afc6a（09-17 14:53）更正声明 data.py → data/timeline.py，注明前序 refactor-dashboard-data-module（把 data.py 拆为 data/ 包的 refactor spec）已落地、单文件不再存在，实现者提 deliverable-dispute 异议经人工确认成立。
  - 调查评估：已核实 814afc6a：spec 评审（09-15）实测 data.py 单文件 5333 行且 data/ 包尚不存在，但实现期间前序 refactor-dashboard-data-module 落地拆包使声明失效；spec 已有「实现前置确认（必做）」指引，实现者按指引提出异议、人工确认后更正解除——机制闭环良好，实际阻塞仅 4 分钟。同类时序漂移的另一实例：本 spec 的 1789628051 分支在 main 落地 37fc33de（runner.py 行数契约放宽 <4000）前分出、携带过期测试副本（≤3800）与合法增长至 3962 行的 runner.py 冲突，靠恢复与 main 一致的独立 commit 修复（d7bf6227）。根因：同批推进的 refactor 与依赖 spec 间的时序竞态，评审时点实测 ≠ 实现时点事实。与存量关系：spec 自身指引已缓解，无独立 spec 覆盖。结论：轻量执行失误，残余缺口小。
  - 建议：spec 评审登记交付物绝对路径时，对同批在飞的 refactor spec（拆包/拆文件）在声明段显式标注「若前序已落地按符号名定位」豁免，减少再走异议闭环。

- **中断 run 无结果致重试让位人工抢救**
  - 影响：一个 14 轮 implementer run 被 SIGTERM（Exit 143）杀死且无结果文件，自动重试因 spec 被人工冻结（frozen 字段，冻结后自动链让位）放弃，触发 All retries exhausted，既有实现改走 round2 分支人工抢救合并（03:03Z→03:52Z 约 49 分钟），中断 run 的成果与 token 消耗未落盘。
  - 证据：fenixd.log 18163-18170 行：03:03:18Z run impl-fix-robustness-edge-cases-1789613903-a1「14 rounds, median 10.9s」后「claude CLI failed: Exit code: 143，usage unobserved」；03:03:48Z「Giving up retry for 'fix-robustness-edge-cases': manually frozen」+「All retries exhausted」；ec9df3dc（09-17 11:52 本地）「merge: 抢救 fix-robustness-edge-cases 既有实现（round2 分支）」。
  - 调查评估：已核实（fenixd.log 18160-18190 行）：run 中断无 result 事件后，provider 瞬态重试（fix-provider-transient-backoff 机制的 1/3 次）检测到 spec 被人工冻结即让位——「spec 已被接管，放弃重派（fix-verdict-dedup-resynthesis D4）」；随后人工走 round2 分支把既有实现抢救回 main。kill 来源未完全核实（日志无 daemon 重启佐证，疑进程管理器终止）。根因：run 中断后结果文件缺失 + 人工冻结接管双重让位，自动链退出、断点成果丢失。与存量关系：结果文件硬门缺口已被在飞 spec fix-impl-resultfile-contract-gap（09-17 14:50 立项、16:12 实现 b87cc2ed「实现者双车道结果文件硬门契约注入+捞回泛化」）覆盖，修复动作已立项。结论：中断 run 的成果与预算损失 + 抢救成本，修复在飞待验证。
  - 建议：验证 fix-impl-resultfile-contract-gap 落地后同类中断是否仍丢失结果；如仍现 SIGTERM 无结果，补查 kill 来源（supervisor 超时 kill / daemon 重启信号路径）并考虑断点续跑。

### 可改进
- **监督超时配置漂移已 8 次报错未落地**
  - 影响：配置漂移使每次 implementer 派发产生一条 ERROR（fenixd.log 累计 8 次、自 09-15 15:49Z 跨 3 天，窗口内 3 次）且被 18600s 兜底静默掩盖，在飞修复 spec 未落地期间持续复现。
  - 证据：fenixd.log 13181/13218/14985/15018/15051 等共 8 条同文案 ERROR「supervision absolute_max_seconds(14400s) 低于 生效超时 15000s + 续期总额 2×1800s = 18600s，按 18600s 兜底生效（agent_type=implementer）」，窗口内 09-17 14:52/15:22/15:52 三条；spec/changes/evo-supervision-timeout-config-consistency/tasks.md 1.1-2.5 全部未勾选（未落地），spec 于 09-17 11:20 立项（commit 1c8360b7）。
  - 调查评估：已核实：该 ERROR 自 09-15 15:49Z 起共 8 次、横跨三个自省窗口，是存量配置漂移——absolute_max_seconds（agent 监督超时硬上限）14400s 低于生效 run_timeout（单 run 超时）15000s + 2×1800s 续期，liveness 兜底生效 18600s 使 run 不受影响，但每次 implementer 派发都产生 ERROR 噪音且兜底掩盖了配置错误；在飞 spec evo-supervision-timeout-config-consistency（六条自进化 spec 之一，立项于 09-17 11:20）正处理此问题（单一派生函数 + 启动/热更新自动对齐 + 持久化），tasks 未勾选、未落地。与存量关系：完全重叠、不新建 spec，属已立项未落地缺口。结论：落地前持续复现，建议优先推进或先手工止血。
  - 建议：推进 evo-supervision-timeout-config-consistency 落地；落地前可手工把 agents.timeout_supervision.absolute_max_seconds 从 14400 抬升到 ≥18600 消除每日 ERROR 噪音与兜底掩盖。

- **派发滞留竞态误报升级留未处理记录**
  - 影响：refactor-giant-classes 在 16:33Z 收到一条 dispatch_stalled 升级告警，实为 recovery watch（周期复查异常 spec 是否滞留的机制）与 blocked 状态写入前 4 秒的竞态误报，成为窗口内唯一未处理升级告警，需人工事后核销。
  - 证据：09-17T16:33:58Z「Recovery watch failed for 'refactor-giant-classes' — not recovered, escalating dispatch_stalled」；admin_disposition-admin-refactor-giant-classes-1789664978.json 记录第 4 点定性「16:33 那条 dispatch_stalled 是 recovery watch 复查机制在 blocked 写入前 4 秒的竞态产物，已被 blocked 事实覆盖」；同类误报修复先例 3fad3350（09-17 18:07，core/admin_monitor.py「修复依赖未满足的 ready spec 被假就绪巡检误报 dispatch_stalled」）。
  - 调查评估：已核实：admin 处置记录明确把 16:33 的 dispatch_stalled 定性为竞态产物并被随后写入的 blocked 事实覆盖，处置只处理 blocked_stuck（blocked 滞留告警）本体；已 pushed 的 evo-recovery-watch-transition-guard（恢复观察过渡守卫，09-14 立项）覆盖的是「成功收工与复查竞态」窗口，本次属「blocked 写入竞态」——触发源与 guard 不同。根因：recovery watch 的 stale 判定未与状态写入（blocked）串行化，复查瞬间与写入交错产生误报。与存量关系：无 spec 覆盖此变体。结论：低严重度改进，频度低（窗口内 1 次）但每次升级都留未处理记录、需人工核销。
  - 建议：在 recovery watch stale 升级前增加「复查当前 status 是否已偏离（如已 blocked/implementing/testing）」的前置检查（对齐 evo-recovery-watch-transition-guard 的 transition_defer 顺延范式），消除与状态写入的竞态误报。

- **verify-serving 存量目录人工清理（fix-verify-serving-disk-reclaim 登记）**
  - 背景：`.fenix/verify-serving/` 存量 19 个 serving worktree 合计约 30G，其中 18 个的 spec 仍存活于 `spec/changes/` 或 `spec/archive/`（按 D1 判据 1「归档等同存活」不会被自动回收），仅 1 个（`verify-draft-fixture-1788860224`）无主已被自动清扫。
  - 清理范围 MUST NOT 只限「spec 在 changes/archive 双双消失」的目录（现测仅 1 个，清理后 30G 基本不动）——**存量主体为 18 个 spec 仍在册目录内各 1.6G `node_modules`**，需按 D1 判据人工逐条核对。
  - 清理方式：**逐条核对后删除，勿用通配批量删**（按 fix-verify-cli-cwd-isolation 教训）：对每个 `<spec>-<ts>` 目录，先确认其 `servers.json` 无登记、`/proc` 无活进程指向、无在飞验证 run，再 `git worktree remove --force` + `git worktree prune`。清理前确认 `.fenix/config.yaml` 的 `verify.deps_mode` 已改为 `hardlink`（本次 SPEC 已改默认值，新建 worktree 单份仅 ~24M），防止存量模式下新建 worktree 再次膨胀。
