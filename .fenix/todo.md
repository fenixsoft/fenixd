## 待办（人工登记 2026-09-24）

- [ ] code-review run 取消（cancel）终态不做产物抢救落账：2026-09-24 run code-review-1790230628 取消后 inserted=0/shards=0，101 文件 45 条发现留在 out 文件需手工 `_read_code_review_out`+`upsert_findings` 补账；error 路径有抢救（1b83c1c1）而 cancel 路径没有，应统一收场抢救。
- [ ] code-review 主车道 ocr scan 网络僵死无护栏：opencodereview scan（101 文件并发 4）2h20m 仅 49s CPU（0.5%，纯网络等待），agent 轮询等待且被处决后「重试重启 scan」而非按提示词「ocr 不可达降级继续」收口，最终靠人工 cancel 脱困；应对 scan 加 CPU/时长心跳判据 + 不可达降级收口（与 ocr 车道心跳方案 prio4 同族）。


## 2026-09-25

### 浪费
- **主树WIP重叠全天5次挡合回、2批弃现场、3次人工救场**
  - 影响：全天 5 个 implementer/code-fix 分支的合回（merge-back，把工作分支并回主树）被 WIP 重叠预检（主树存在与分支同文件的未提交改动时阻止合回的闸门）先后挡下，每次放行等待 20-47 分钟、累计约 2.1 小时；另 2 个 code-fix 修复批次因合回冲突「现场即弃」（丢弃整批工作现场、仅存档分支名）整批作废重跑，全天消耗 3 次显式人工收编提交救场。
  - 证据：daemon 日志 ERROR 时间线（本地时间）：10:37 告警 add-code-review-trigger-ack 被阻、10:49 add-code-review-concurrency-and-429-resilience（重叠 2 文件）、12:43 code-review-fix-1790223760、14:28 与 14:45 code-review-fix-1790230556 两次、17:11 code-review-fix-1790239507；放行均靠主树 WIP 被人工提交——5a5f6595（11:12 收编无主实验 WIP）、29d3945c（12:57 提交 batch 7）、c030d19a（17:21 admin 收编提交）、738cbf0d（15:05 质量页签 UI 修正顺带放行 14:28 那次）；另有 11:32 与 17:34 两次「code-fix 第 4/第 2 批合回冲突，现场即弃」日志。
  - 调查评估：在处置 code-review 台账修复批次与 add-code-review-concurrency-and-429-resilience 合回时暴露。已核实事实见上，与 admin_alerts 中 mergeback_wip_overlap、code_fix_wip_gate_deferred 告警交叉一致。根因是主树长期携带人工/实验未提交改动（dashboard 静态页、agent-env-overrides 实验），与 code-fix 提速后「高频小批、批批合回」的吞吐模式结构性冲突，不是单次执行失误。与存量工作关系：当日已落地两个对症 spec——evo-add-codefix-batch-wip-precheck（fc752705，选批前预检重叠则整批推迟）与 evo-add-wip-defer-merge-retry-consumer（5b1f0581，阻断落结构化载体后由 120 秒周期消费者自动合回、90min/6 次有界降级），18:32 后窗口内无新复发，但两修复均合回于 daemon（16:45 启动）之后、未重启未生效（见改进项），护栏目前空转。结论：该家族已被正确收口、无需新 SPEC，缺的是让修复生效加短期观察。
  - 建议：无需新 SPEC；先重启 daemon 让两个已合回护栏生效，观察 48 小时——若 mergeback_wip_overlap 告警清零、code_fix_wip_gate_deferred 能被周期消费者自动闭环即关闭本家族；若频繁走到 90min/6 次降级再立项收敛。

### 失误
- **日汇总误报两个幻影失败：成功run被旧分类器全文扫词翻转**
  - 影响：当日 51 个 run 统计里的「失败 2」全为幻影，真实业务失败为 0，成功率被从实际满贯低估为 48/51；失真样本进入每日自省输入、误导回顾注意力，若未来治理自动化按该计数触发还会放大。
  - 证据：汇总列 impl-evo-fix-self-review-marker-match-window-1790242754-a1「marker=预算耗尽」、planner-plan-evo-fix-self-review-marker-match-window-1790243612-a1「marker=SPEC 内容缺失」（marker 即 run 终态文本命中的业务失败声明关键词），但两个 run 产物终态行均 subtype=success、is_error=False，开头分别是「收工自检 PASS」「规划完成……7 个场景已全部落盘」，触发词只在正文分别出现 41 处与 22 处（planner 正在编写引用「SPEC 内容缺失，无法实现」句式的测试场景）；daemon 日志 09:53:31Z 与 10:03:46Z 均记录 terminal=success，impl 分支已合回主树（933d48de 合并提交）、spec 当日走到 done。
  - 调查评估：在处置 evo-fix-self-review-marker-match-window（修 self-review 失败样本分类器误报的 spec）时暴露，且被误报的恰好是修它的两个 run。已核实：汇总的 marker= 输出形态只能出自旧版全文匹配——修复合回后 marker 只认 result 前 100 字符声明区、信号护栏排除终态邻近正文（core/self_review.py 的 _MARKER_DECLARATION_WINDOW 与 lines[:-1] 护栏），而两个 run 的声明区均无失败词。根因不是分类器新缺陷，而是修复合回（698a9a0d，17:52）后 daemon（16:45 启动）未重启，次日 02:26 聚合仍驻旧代码，与改进项同一根源。结论：重启后自愈，无需新修复 spec；长期可加「分类为 failed 但 daemon 终态为 success」的双源交叉守卫防再犯。
  - 建议：随 daemon 重启一并消除，次日核对日汇总失败样本应归零；可在聚合侧补一条廉价守卫：marker 命中但 run 终态记录为 success 时输出告警而非直接计失败。

### 可改进
- **7个护栏修复合回后悬空8小时：自愈重启等空闲饥饿**
  - 影响：复发敞口——昨日 17:52-20:39 合回的 7 个系统性修复（marker 声明窗口、选批 WIP 预检、规划性重启排水、worktree 撞名换名重试、stale 告警窗口去重、WIP 周期合回消费者、迟到结果终态丢弃）至今未在运行进程生效，同族事件单日实测代价约 2.1 小时合回停摆加 2 批弃现场加 3 次人工救场；悬空期已实际复发一次：20:23 worktree 分支撞名 ERROR 以与修复前完全相同的形态出现，而换名重试修复 18:18 已合回。
  - 证据：daemon 进程（pid 313888）2026-09-24 16:45:05 启动后未再重启（02:11 时 etime 9 小时 26 分），上述 7 个修复的合并提交均在 17:52-20:39；restart_history.jsonl 末条（16:44:09）self_triggered=false，即上次重启是外部/人工触发，stale_code_selfheal 虽 enabled=true 但未见自愈触发记录；stale_code 升级告警（daemon 进程持旧代码、自愈将在连续空闲后触发重启）当日仅 09:13 一对，其后约 17 小时代码基线再漂移无新告警。
  - 调查评估：在处置 evo-fix-worktree-name-collision-retry（20:23 复发取证）与次日日汇总幻影失败时暴露。已核实事实如上；根因是空闲自愈以「连续空闲」为前置，而当前负载形态（白天 code-fix 高频小批、夜间长跑 code-review）几乎不产生连续空闲窗口，告警又一次性标记 handled（语义即等空闲）后缺少按悬空时长升级的路径。与存量工作关系：evo-fix-planned-restart-drain-effectiveness（18:17 合回）已提供规划性重启加在飞排水（restart_request 触发 supervisor 优雅重启、在飞 run 宽限收尾）能力，恰适合不停业务换代码，但它自身也在未加载之列，形成「一次重启才能获得安全重启能力」的一次性门槛；evo-fix-stale-code-alert-window-dedup 的 60 分钟写入去重生效后催促频度还会进一步降低。结论：值得立一个小 SPEC 补「最长悬空时限」，落地前先人工重启一次清空全部积压。
  - 建议：立项小 SPEC：代码基线漂移超过 N 小时即不再等全空闲，改在 run 边界复用规划性排水执行安全重启，并把悬空超时升级为需人工知悉的告警；落地前由人工在低负载窗口 touch .fenix/restart_request 一次性加载全部积压修复。
