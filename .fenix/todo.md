最近两天的SPEC经历了许多曲折，速度慢，烧钱也多。你今晚自省时重点关注最近两天超过1个小时完成的SPEC，分析它们的耗时，除LLM网关延迟外，有什么是框架可改进的地方

## 2026-09-08

### 浪费

- **autostash 栈 75 条只增不减**
  - 影响：pre-dispatch autostash 栈累积 75 条，最早一条 2026-08-25（13 天前），跨越多轮实现与重启仍无法清理。每条保留一份完整 diff 快照，占用 git 对象空间，且老条目可能引用已删除路径（如 v3/dist 重构前的路径）使 pop 自愈成本上升。窗口内新增 3 条（09-07 12:22/16:49、09-08 02:00），与窗口内 3 次冲突直接对应。
  - 证据：git stash list 75 条，stash@{0} 2026-09-08 02:00 至 stash@{74} 2026-08-25 10:28。reclaim_stale_autostash（worktree_manager.py:1437）每 60s 调用一次（fenixd.py:435），但要求主树干净且仅处理栈顶一条。当前主树有 20+ 未提交改动文件（git status 显示），导致 reclaim 持续返回 False，清理完全停滞。
  - 调查评估：核实：stash list 命令输出原始数据，reclaim 调用路径 fenixd.py:435 已核实。git status 确认主树脏。根因：reclaim 的主树干净条件（worktree_manager.py:1462）在活跃开发期无法满足；叠加每次 dispatch 新增一条 autostash，形成只增不减的堆积。与 2026-09-07 自省条目 #1 的修复关系：4f753ed 解决了无限循环（同条目重复 pop），但未解决存量堆积——该修复的 drop 路径仅在 pop 成功或自愈完成后触发，对于因主树脏无法被 reclaim 触达的条目无效。结论：这是系统性缺口，reclaim 机制在并发开发环境下实际失效。
  - 建议：为 reclaim 增加「批量清理模式」：在 spec 已 pushed 且对应 autostash 条目年龄 > 阈值（如 48h）时，不论主树状态，直接 drop 该条目并记录 WARNING（附 sha 和 diff 摘要）。同时在 daemon 启动时做一次全栈扫描，对所有已 pushed spec 对应的陈旧条目一次性清理，而非依赖 60s 增量回收。

## 2026-09-09

### 浪费
- **冻结场景验收失败三连发，planner 未消费反馈连环触发人工处置**
  - 影响：同一场景错误 3 轮重复（05:26「与上一轮一字不差」、07:14 扩至 8 错、08:46 再触发），引发至少 4 次 verify_env_blocked 升级 + 5 个 admin 处置 run（1788845201/1788851661/1788857194 等，其中 2 次处置中断再升级人工），add-verify-contract-autodraft 全程 20821s（5.8h）、impl 预算用满 6 轮。
  - 证据：pm_engine ERROR 05:26:41/07:14:20「场景验收错误与上一轮一字不差 — planner 未消费反馈，重跑属高风险重复」、08:46:33 冻结场景验收失败；admin_alerts.json 13:26/15:14/16:46 verify_env_blocked 升级与对应 disposition 记录；STATE.md total_duration: 20821、_impl_run_budget_used: 6。
  - 调查评估：已核实：ERROR 三条时间点与 admin 告警时间线交叉一致，错误主体均为 api-autodraft-existing-contract-overwrite-dispatched 缺 navigate 步骤，错误清单已内联进重跑 prompt 但 planner 输出原样复发。根因：场景重跑路径只做「错误清单内联注入」，没有校验 planner 新产物是否真正消费了上轮错误（无消费硬门），坏产物直接再进冻结验收，循环触发人工。与存量工作关系：add-judge-artifact-gate（89912400 已落地）只升级了产物存在性硬门，不覆盖产物内容对反馈的消费校验；add-verify-contract-autodraft 本体已 pushed，残余缺口在冻结场景重跑治理流程。结论：系统性缺口——反馈消费无校验导致重跑成本被重复支付，且每次失败都外溢为 admin 人工往返。
  - 建议：起草 SPEC：场景验收失败重跑前校验 planner 输出对上轮错误清单的逐条处置说明（缺失任一条则拒绝派发、直接升级人工），并在场景产物落盘侧加 schema 校验（孤儿条目 8 个「仅 id/description 无 kind/steps」三轮重复出现于 13:35/15:33/17:03，写入侧无结构门）。

- **verify_contract_missing 假信号 4 连发，自证工具 stop 顺序缺陷**
  - 影响：UI 手动触发 AI 起草验证契约 4 次均假失败（verify.yaml 已存在且有效），消耗至少 3 个 admin 自证 run（admin-fenixd-1788853515/1788858425/1788858678）+ 1 次人工定位修复 + 2 次 AdminMonitor 处置中转记录。
  - 证据：admin_alerts.json 15:43/17:02×2 verify_contract_missing 信号，16:17/17:11/17:13 处置记录均判定「.fenix/verify.yaml 已存在且合法有效」；commit b547eccb（09-08 16:16）修复 validate_contract command 形态 stop 在 probe_ready 之前执行导致探活必 Connection refused（exit 4）。
  - 调查评估：已核实：git show b547eccb 确认根因为自证工具 command 形态收口顺序错误（stop 先于探活），已由人工提交修复；告警时间线显示修复后 17:02 仍有信号触发（修复前的存量信号与路径未拦）。根因归属：执行层一次性失误（代码顺序）已修；但放大成本的是信号链路缺前置校验——触发前不检查 verify.yaml 是否已存在，假信号本可在信号层零成本拦截。与存量关系：add-verify-contract-autodraft-ui（05f58fa4 verify.yaml AI 生成按钮）新增该触发路径时未做存在性前置检查。结论：失误已闭环，残余缺口是信号前置校验。
  - 建议：verify_contract_missing 信号生成前先读 .fenix/verify.yaml，存在且通过 schema 校验则不出信号；Dashboard 侧按钮在 verify.yaml 有效时置灰。

- **verify-draft 两草稿一轮内归档-重建-再归档循环**
  - 影响：verify-draft-bad 与 verify-draft-fixture 各经历两轮完整 pipeline（15:48/16:07 首次归档 → 17:00/17:13 重建 spec → 17:22 二次归档），叠加 4 次 run 人工取消（11:33/11:43/16:14/16:20/17:23 中 3 次属 verify-draft）与 1 次全场景同因失败（15:41，5/5 Locator.wait_for 超时），单轮重复消耗约 2 轮验证 + 多次取消往返。
  - 证据：git log：2e12fd8a、b4ca7002（首次归档）、a6cebc23、5f230154（重建 spec）、552ed381、5c4e3d49（二次归档），spec/archive/ 下 verify-draft-bad/fixture 各两份归档目录；admin_alerts.json 15:41 verify_uniform_failure、16:14/16:20/17:23 run_cancelled。
  - 调查评估：已核实：归档目录双份与 commit 序列一致，取消告警时间点吻合。根因：验证草稿执行遇环境同因失败（5/5 超时，签名一致）后走「取消→重建→重跑」，而 verify_uniform_failure 信号已明确指向环境/场景问题而非草稿内容问题，识别正确却未短路重建循环。与存量关系：verify_uniform_failure 信号机制本身工作正常（正确归因），缺口在同因失败后的处置策略——没有阻止对环境性问题做内容性重建。结论：系统性缺口，重建循环属无产出消耗。
  - 建议：verify_uniform_failure（全场景同因）触发后冻结该草稿的自动/半自动重建路径，要求 admin 先裁决环境问题再放行重建；重建前展示上次同因失败证据避免盲目重跑。

### 失误
- **add-draft-promotion-gate 验证三连败冻结，token 烧至预算 81%**
  - 影响：单 spec 累计 input token 89.1M（预算 100M 的 81%，22:42 告警），impl 预算用 6 轮、验证失败 3 轮，14:42 冻结 blocked 等待人工；当日连带两次设计返工（bool→promote_mode 枚举、写侧合并 Bug）与 1 次 stash pop 冲突（08:59）。
  - 证据：STATE.md _tokens_in: 89.1M、_impl_run_budget_used: 6、error「验证失败第 2 轮，原地打回重修」；admin_alerts.json 22:42 token_budget 80% 告警 + verify_fail_escalation「验证连续失败 3 轮」+ 17:28 verdict_evidence_invalid blocked；commits 10938ab9（auto_promote_draft bool→枚举）、4908603f（promote_mode 写侧合并缺失修复）。
  - 调查评估：已核实：STATE 字段、三条 escalation 告警与 commit 内容均吻合。根因：①起草阶段设计评审不充分导致中途枚举化返工；②验证裁决证据分类校验连续失败（09:28 二次校验仍失败、17:28 再发），说明 spec 文本对证据格式契约表述不清，verifier 每轮以不同方式出错。与存量关系：add-draft-promotion-gate 本身是当日主体工作（4 次 merge、2 轮验证修复均在窗口内），无既有 SPEC 覆盖「验证失败轮次的失败原因结构化透传」。结论：高消耗主因是验证轮次翻滚——按 6 轮 impl 预算估算单轮约 15M token 量级，每多翻一轮即多付一次该量级。
  - 建议：起草 SPEC：验证失败 ≥2 轮的 spec，第三轮派发前强制把历轮失败原因 human-readable 摘要注入 prompt；预算 80% 告警触发时同步暂停自动重试，转人工确认是否继续。

- **状态机非法跃迁尝试 testing → implemented**
  - 影响：单次被拒无实际损失，但反映 agent 侧对状态机合法路径认知缺失，复发将造成状态修复往返。
  - 证据：fenixd.log 05:48:26 [state_machine] Invalid transition: add-verify-contract-autodraft testing → implemented。
  - 调查评估：已核实：日志条目存在，跃迁被状态机正确拒绝（fail-safe 生效）。根因：agent 输出试图跳过 verified/pushed 中间态直接落 implemented。与存量关系：run-lifecycle-hardening 已覆盖状态机治理且本次拦截成功，属 agent 决策失误而非框架缺陷。结论：一次性失误，量级小，记录备查不立项。
  - 建议：若同类拒绝复发 ≥2 次，在 agent prompt 注入当前 spec 状态与合法跃迁表，拒绝信息附带合法路径提示。

### 可改进
- **run 悬空治理 spec 立项 14.5h 未派发，无终态 run 仍在累积（新增）**
  - 影响：add-runtime-run-sweeper（2026-09-07#浪费#1 的修复项）09-08 03:37 创建至窗口结束 implementer_run 仍为 null，期间窗口内 25 个 run 在跑/无终态；悬空 run 复发敞口延续——单次悬空代价参照 09-07 实测 11.8–12.5 小时直至重启清扫。
  - 证据：STATE.md add-runtime-run-sweeper status=implementing、implementer_run: null、start_after: 2026-09-08T18:00（18:00:13 才转 implementing，之后仍无派发记录）；本次数据摘要「在跑/无终态: 25」；df2b46d1 09-08 11:37 spec 落地提交。
  - 调查评估：已核实：STATE 字段与 admin_state_history.json（18:00:13 转 implementing）一致，至窗口结束未派发 implementer。根因：活跃 spec 3 个（含两个被冻结 blocked 的）与 max_concurrent: 3 的派发竞争，叠加 start_after 调度延迟，修复项自身被排队拖住。与存量关系：该 spec 正是 09-07#浪费#1 悬空问题的修复载体，其落地缓慢使原问题既不闭环也无法验证修复效果。结论：调度延迟为系统性现象，修复项被同域问题拖累形成闭环死锁风险，值得干预。
  - 建议：核实 start_after 到期后派发是否存在主树干净等附加前置条件；若无，将该 spec 优先级提至 4 尽快派发落地，落地前用 09-07 实测数字（悬空 11.8–12.5h）作为验证基线。

- **stash pop 冲突新增 1 次，autostash 栈增至 76 条（恶化）**
  - 影响：窗口内 08:59 add-draft-promotion-gate 再次 stash pop 冲突（test_dashboard_api.py），本地改动沉入 stash 待人工找回，单次代价参照 09-08 实测：1 次 admin 往返 + 1 份改动丢失风险；autostash 栈 75→76 条（新增 09-08 16:59 一条），最老条目 2026-08-25 已 14 天。
  - 证据：fenixd.log 08:59:20 [pm_engine] 'add-draft-promotion-gate' stash pop conflict: files=['tests/test_dashboard_api.py']；git stash list 实测 76 条，stash@{0} 2026-09-08 16:59:20，stash@{75} 2026-08-25 10:28:59。
  - 调查评估：已核实：stash 栈实测 +1（新增条目时间与 dispatch 记录吻合），冲突 ERROR 为 09-08#浪费#1 同型事件（并发分支改同一文件后 merge-back pop 冲突）。与存量关系：fix-mergeback-stashpop-silent-loss spec 已立项（09-08 09:21 创建）但 status=implementing、implementer_run: null，未落地——与 add-runtime-run-sweeper 同样陷于派发排队。09-08#浪费#2 的批量清理建议同样无 SPEC 载体落地。结论：两个既有条目均未闭环且当日各恶化一次（冲突 +1、栈 +1），缺口维持原判。
  - 建议：将 fix-mergeback-stashpop-silent-loss 与 autostash 批量清理合并排期优先派发；落地前降低并发实现分支对同一测试文件（tests/ 目录）的并行认领概率。
