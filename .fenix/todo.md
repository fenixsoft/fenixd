## 2026-09-15

### 浪费
- **评审 402 判败 $8.54 作废**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：两次评审已产出合格结论却被判失败：单次耗 $6.24（2.9M input tokens/50 rounds）与 $2.30（1.03M/31 rounds），合计 $8.54 消耗作废；evo-item-retention-doc-tracking 的 approved 评审结论（无阻断缺陷）未消费，spec 15:45 重立后评审重来
  - 证据：run spec-review-evo-item-retention-doc-tracking-1789368468 转录尾部「API Error: 402 余额不足」+ error: Exit code 1，result 记录 total_cost_usd=6.239、input_tokens=2904252；run spec-review-evo-infra-failure-budget-exempt-1789368783 total_cost_usd=2.304、input_tokens=1027650；.fenix/spec-review/evo-item-retention-doc-tracking/.fenix-run-result.json 于 09-14 14:56 落盘 status=approved、5 findings 全 note（非阻断）
  - 调查评估：已核实（读两个 run 转录尾部 + 结果文件 + STATE 更新记录）。根因：框架以「CLI exit code」一票判定 run 成败，402 余额类错误穿透为 Exit 1；而评审主体已完成并落盘 approved 结论，判败后结果不消费、_review_attempts 递增至 3 次重试（重试同样失败），属「产物已具备却被退出码一票否决」的判定缺陷而非内容质量问题。与窗口末 04:36 merge 的 evo-verifier-result-single-source（d87c5401）聚焦 verifier 结果单源，未覆盖评审结果在异常退出码下的保留，无重复。结论：值得立项「run 失败判定先查已落盘产物、余额类错误不入内容重试」，复发敞口为单次 402 即抛掉整轮已付费评审。
  - 建议：评审/验证/实现 run 判定失败前先校验 .fenix-run-result.json 是否合法落盘（已落盘则按产物消费、退出码仅降级告警）；402/403/配额类 infra 错误单独分类，不计入 _review_attempts 内容重试

### 失误
- **spec-review 403 评审批量失败风暴**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：拒绝 · 删除：否
  - 影响：3 个 09-14 14:30 前后创建的 evo-* SPEC 评审 run 从 14:46 至 16:27 批量失败（含 0 rounds 快速失败十余次与 2 次 31/50 rounds 高消耗失败），评审阻塞 2-9.5 小时：evo-planner-port-alignment 19:34 被撤回（假归因）、evo-judge-rerun-stability 18:30 重立、evo-infra-failure-budget-exempt 23:53 重立，进程与 token 双重浪费
  - 证据：fenixd.log ERROR 样本 06:56:39Z-08:27:11Z（local 14:46-16:27）连续 10+ 条 spec_review/pm_engine 评审失败；admin_disposition-evo-planner-port-alignment-1789378552.json 根因写明「provider=xianyu model=deepseek-flash 被网关 403 拒绝，config 链首模型名与 xianyu 网关允许的 glm-5.3-flash 不符」；config.yaml mtime 2026-09-14 16:27:18 +0800 且 08:27:47Z hot-reload（修复点）；77bfee34 19:34「撤 evo-planner-port-alignment 假归因 SPEC」
  - 调查评估：已核实（admin 处置记录 + config mtime + hot-reload 日志 + 撤回/重立 commits）。属配置失误：spec-review 模型链首被设为网关不允许的模型组合，派发即 403；config.yaml 在 .gitignore 内无法 git 溯源引入者，且 1h40m 内无任何机制发现（见 improvements 熔断条目）。166min 期间 3 SPEC × 5 轮重试（30min 间隔）全数空转，直至 16:27 人工修正 config + 16:54 重启 daemon 后才恢复（16:57 sibling 35 rounds 全通实证）。另外这批 evo-* SPEC 由 planner 生成，evo-planner-port-alignment 最终被证假归因（77bfee34 撤回），SPEC 源头质量亦是诱因之一。结论：配置失误为主、无快速验证手段放大之；需要模型链派发前探活 + SPEC 假归因早期识别
  - 建议：为 spec-review 链增加派发前探活（provider/model 组合可测性自检）；对 planner 生成的 evo-* SPEC 评审失败做根因归集，403 失败不入内容重试而是直接标 infra 级并升级告警

- **stash pop 冲突再发 1 文件被丢弃**
  - 自进化：问题部分成立 / 建议部分合理 / ✓ 值得立项 · 处理：拒绝 · 删除：否
  - 影响：evo-item-retention-doc-tracking merge-back 时 1 个未提交文件（SuggestedImprovementsPanel.tsx）改动被丢弃（stash 保留可找回）；同信号 20:26 派发 Administrator 时触发 replace() 报错，自动处置失效；WIP 重叠预检命中 7 文件暴露主树残留并发改动
  - 证据：fenixd.log 9801 行 12:22:13Z（local 20:22）stash_pop_conflict 告警（conflict_files=[.../Settings/comments/SuggestedImprovementsPanel.tsx]、wip_overlap 7 文件、stash_kept=true）；9802 行 20:26「Administrator invocation failed: replace() argument 2 must be str, not dict」；fix-mergeback-stashpop-silent-loss 已于 09-09 归档（7fb43e50）——修复后 5 天仍发生同类冲突
  - 调查评估：已核实（告警记录 + 代码现场：prompt_builder.py:204 _fill_placeholders 中 {evidence} 值为 dict 未经序列化，_str_field 的 json.dumps 兜底直到 66f815db 09-15 04:36 才合入，故 20:26 报错时保护尚不存在）。双层问题：其一 merge-back 前主树有 7 个文件 in-flight 改动与分支重叠，stashpop 冲突机制（自愈+预检，fix-mergeback-stashpop-silent-loss 落地）能告警保留但无法避免丢弃，属该修复的残余缺口；其二 admin 派发链对该故障信号的处理因序列化 bug 挂掉，仅记 ERROR 无升级。两者均已达成事实修复（stash 保留可找回、（str_field 04:36 合入），但本次损失已发生。结论：merge-back 主树 WIP 残留是冲突源，需前置阻塞或自动收纳
  - 建议：merge-back 前对主树未提交改动做 WIP 扫描：与分支改动重叠时先阻塞并告警（或自动 stash + 标记待回收），从源头避免 pop 冲突；并排查故障信号派发失败为何未升级告警（见 improvements 对应条目）

### 可改进
- **评审失败无熔断空转 1h40m**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：本次 14:46-16:27 同型 infra 级失败（403 网关拒绝 + 402 余额不足 + 评审 budget exhausted）在 3 SPEC 上重复重试 5 轮约 15 个 run 全失败；窗口内另有 6 次评审 run 预算耗尽（含 spec-review-fix-recovery-branch-anchor-without-worktree-1789349356、spec-review-fix-blocked-freeze-classification-1789386350/1789388657 等）同型空转；41 条告警中无一指出「评审 API 批量失败」。复发敞口：每次同类 infra 失败以 10+ 空转 run 计
  - 证据：失败 run 清单（1789369017/9026/9028、1789370821/0823/0825、1789374079、1789374428、1789386350、1789388657 等）+ 30 分钟间隔重试模式（06:57→07:27→07:57→08:21→08:27Z 五轮）；admin_alerts.json 41 条信号中无评审失败类；修复仅靠 16:27 人工改 config
  - 调查评估：已核实（失败 run 时间轴 + 告警归类 + 修复动作归属人工）。根因：评审 run 失败既不做原因分级（内容质量 vs 基础设施）也不做熔断冷却，统一按 _review_attempts 机械重试直至 blocked。与进行中的 add-control-plane-silent-failure-guards（e01f6a39，专注 arity 静态守卫/测试替身保真/复位路径编程错误升级/orphaned-state）互补而非重复——该 SPEC 未覆盖「run 失败类型分级与熔断」。结论：立项价值高，收益为把 1h40m 级盲转压缩为分钟级告警。
  - 建议：为 run 执行失败增加三级落点：内容失败（含空白轮次正常重试）、infra 失败（403/402/预算耗尽/CLI 进程级——连续 ≥3 次即熔断该链路并落升级告警 + 冷却，恢复后自动重试）、判别失败（产物已落盘——直接消费，见 waste 条目）；失败分类进入 ADMIN 信号体系

- **stuck 判定误报 5 连发待去重**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：fix-command-main-serve-scope 在 implementer 活跃期间于 15:11-15:31 连发 5 条 stuck 升级告警（major、全程 unhandled、噪音持续 20 分钟）；同日 evo-verifier-result-single-source 17:56 再触发 stuck 升级，admin 三步骤只读诊断确认「implementer 活跃正常收尾」纯误报（诊断耗时约 2h40m 的 run 资源）。复发敞口每例约 3-5 条告警 + 一次 admin run 处置
  - 证据：admin_alerts.json 5 条 fix-command-main-serve-scope stuck（id 51c737591057/9cd17fb52ba8/c3d747c8dbc0/8edf5f0d6aa9/e892bd9e39cc，created 15:11-15:31 local）；4e907587a129 disposition 记录「实际 implementer (a1-r1) 一直活跃运行并已正常收尾…信号为 admin_monitor 解析缺陷导致的误报」；8e510a87 09-15 02:22 已修 _spec_from_run_id -r<n> 瞬态重试后缀误报根因
  - 调查评估：已核实（告警记录 + disposition 文本 + 修复 commit）。根因：stuck 判定基于 STATE updated 时间戳 + run 进度，长任务（全量回归等）期间 updated 不刷新即误报；同 spec 已处置后未抑制后续重复告警（5 连发同一 updated 值）；8e510a87 只修了 run_id 后缀解析一个根因，时间戳盲区仍在。与 stuck baseline reset 机制（10509 行 extension 记录）部分互补但未覆盖处置后去重。结论：残余缺口明确，低成本高收益
  - 建议：stuck 判定叠加进程存活与 run 文件活跃度检查（对应 implementer PID 存活或 run 文件近期增长即非 stuck）；对同一 (spec, signal_type) 在处置 resolved 后静默期去重；将 a1/a2 人工只读诊断所依赖的信号（进程树/转录 mtime）收编为内置预检字段，减少人工诊断 run

- **admin 派发失败无升级告警**
  - 自进化：问题部分成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：20:26 stash_pop_conflict 信号（含 1 文件改动丢弃与 7 文件 WIP 冲突的善后指引）因提示词构造 replace() 报错无法派发 Administrator，自动处置缺失、仅落一行 ERROR；同类「派发期编程错误」在 add-control-plane-silent-failure-guards 覆盖前无升级通道。复发敞口：任一结构化信号字段（evidence dict 等）都可能复现
  - 证据：fenixd.log 9802 行 ERROR「Administrator invocation failed: replace() argument 2 must be str, not dict」（context.signal=stash_pop_conflict/evo-item-retention-doc-tracking）；prompt_builder.py:204 out.replace(key, val) 现场 + _str_field（json.dumps 兜底）直至 66f815db 04:36 才合入
  - 调查评估：已核实（报错日志 + 代码路径 + _str_field 引入 commit）。根因：_fill_placeholders 的 {evidence}/{recommendation} 注入依赖调用侧保证 str，stash_pop_conflict 等结构化 evidence dict 直接穿透到 str.replace；且 admin_monitor 的派发路径捕获异常后仅 logger.error，不升级告警。与 add-control-plane-silent-failure-guards 的 admin_reset_programming_error（3.1-3.5：只覆盖 _reset_env_blocked_after_disposition 复位路径编程错误升级）同源但覆盖点不同——派发路径是空白。结论：修复已随 66f815db 合入（事件后约 8h），但「派发失败升级告警」的机制缺口仍在
  - 建议：将 admin 派发失败纳入升级告警体系（沿用 add-control-plane-silent-failure-guards 的编程错误升级模式，覆盖派发链）；对 admin 提示词注入字段统一走 _str_field 序列化并加单测防回退
