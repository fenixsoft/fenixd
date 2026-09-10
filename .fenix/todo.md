最近两天的SPEC经历了许多曲折，速度慢，烧钱也多。你今晚自省时重点关注最近两天超过1个小时完成的SPEC，分析它们的耗时，除LLM网关延迟外，有什么是框架可改进的地方



## 2026-09-11

### 浪费
- **blocked-env 重验风暴 11 轮**
  - 影响：单一 SPEC 连续 11 轮验证全部 blocked-env（16:10Z→23:39Z 约 9.5h），每轮仍空跑完整 27 场景批次；框架口径白烧 $24，SPEC 滞留 implemented 无进展近 10h，验证被迫推迟到次日 00:39 环境恢复后才通过。
  - 证据：.fenix/logs/fenixd.log：16:10:49「第 1/3 次重验」→16:14:30「连续 3 轮…暂停自动重验」→23:39:28「连续 11 轮」，_inconclusive_attempts 3→11；16:14:30「环境健全性门: 候选=18, 探针=健康, blocked-env=10」；16:37/17:07/00:07 多次「Recovery: re-triggering verify」；修复 commit 120a9ade 自述「暂停声明后仍每小时重验 9 轮（第 3→11 轮），白烧 $24」。
  - 调查评估：已核实（git show 120a9ade + fenixd.log）：暂停自第 3 轮（16:14Z）即声明，但 B6 recovery 的 implemented 分支只查 tester_run（暂停时恰被置 None），对 _inconclusive_attempts 暂停标记视而不见，仍每小时强推重验；且 root 探针判「健康」却 10 场景 blocked-env，说明探针未覆盖场景真实依赖的 mock API/SSE 面，环境故障未在批次前暴露。根因是「recovery 不读完整状态」的结构性缺陷（120a9ade 自注为 verified-gate「recovery 不读 error」同款变体），属系统性缺口而非一次性失误。该缺陷已由 120a9ade（09-10 08:31，implemented 分支 re-trigger 前查 _inconclusive_attempts>0 即跳过）修复，提交后窗口内未再出现同型连环重验；与 add-scenario-defect-triage-gate（缺陷分类改道）互补不重复。残余缺口：暂停不产生人工升级动作、环境恢复后无自动解冻信号，且风暴期间每轮仍全量跑 27 场景批次（健全性门失败未短路）。结论：损失已发生、修复已落地，本条为损失记录并给残余预防。
  - 建议：在 120a9ade 基础上补两段：①blocked-env 连续 ≥3 轮时健全性门失败即短路整批执行，不再空跑 27 场景；②环境自检通过事件作为自动解冻信号，恢复后自动重验并清 _inconclusive_attempts，暂停期间升级人工告警。

- **budget SPEC 三番重建约**
  - 影响：add-spec-status-modal-budget 从 spec 创建（09-09 04:28Z）到 verified（09-10 00:39Z）近 20h：3 次 spec 重建、3 轮实现合计 381min、7 次 judge 重试；框架口径累计 $119.37（三轮实现）+$22.55（replan）+$9.27（judge 重试）+$24（blocked-env 风暴）≈$151，为近期最大单点损耗。
  - 证据：spec 三连提交 f35979b6(12:28)/101753ca(18:15)/6aa7d6a0(21:45)；impl run 1788928128/1788948951/1788961506 时长 118.6/165.5/97.2min；judge 1788945507「场景文件缺陷 25 个」、1788947632「19 test-defect」、1788959262/1788960304 各 12-13 test-defect、1789000547 终验「0 bug 19 warning 全 flaky」；金额出自 add-scenario-defect-triage-gate proposal Why 段。
  - 调查评估：已核实：耗时由三层叠加——①环境/夹具前置缺陷：dashboard.yaml ignored 列表含已软删除项目 /root/scheduling-showcase，10 个 web 场景跨 5 轮 404/test-defect 未收敛（judge 1788945507 实证）；②judge 将 100% 场景缺陷申报 bug-found 打回 implementer，而框架 bug-found 路由不读 classification，两轮实现（$88+）被整轮耗在改场景文件（triage-gate proposal 实证）；③SSIM 视觉抖动 flaky 每轮 7-19 个且 DOM 全过，拉长每轮归因。根因属多环节系统性缺口，但大部分已被随后落地的 SPEC 覆盖：add-scenario-defect-triage-gate（静态扫描+bug-found 分类改道门，09-10 11:51 merge）、120a9ade（暂停语义）、b04843ed（白屏降级 blocked-env 不再静默放行）。残余缺口仅在「验证环境/夹具脏数据前置自检」与「SSIM flaky 治理」两处（见 improvements 两条）。结论：本 SPEC 是多条框架修复的直接触发源，损失已记录，防复发依赖残余两项。
  - 建议：以 add-scenario-defect-triage-gate 已落地的静态扫描为基底扩展：验证启动前对 registry/dashboard 配置的项目残留与 ignored 脏数据做预检（模式表扩展至环境配置面），从源头拦下同类「环境脏→整批场景失败→多轮打回」的循环。

### 失误
- **两 SPEC 首轮零提交被打回重派**
  - 影响：add-verdict-credibility-gate 首轮 run 1789001677（36.5min）与 add-impl-wip-checkpoint 首轮 run 1789002687（31.8min）双双因分支零提交被交付物守卫打回重派，合计约 68min 实现时间白耗 + 2 次 dispute-judge（164s/320s）+ 重派延迟，两 SPEC 整体耗时因此达到 2.1h / 1.4h。
  - 证据：守卫日志：01:31:39/01:44:02 置 blocked → 01:34:31/01:49:29「缺件 [core/verify_engine/screenshot_lab.py] / [tests/test_impl_wip_checkpoint.py] 重派（第 1 次）」；dispute-judge 1789003899「实现分支零实现提交，分支顶即 SPEC 立项提交」、1789004641「已写出文件且 pytest 15 passed，但全程未 commit，worktree 清理后全部丢失」。
  - 调查评估：已核实（守卫日志 + 两份 dispute 裁决 + run 转录）：两案均非「实现了但文件名对不上」的误判，守卫裁决经四层核实严谨成立。根因在 run 生命周期：credibility a1 转录末行（01:31:34）是实现完成、正要执行 git add 时 run 被切断，成果未上分支；wip a1 则是写毕未 commit 即终态，收口清理吞掉全部产物（dispute-judge 自注「正是本 SPEC 锚点 A 要防的问题，在自身实现轮上先发生」）。add-interrupt-recovery-preserve（09-05 落地）只覆盖「排水超时 terminate 在跑 run」，add-impl-wip-checkpoint 锚点（09-10 10:37 merge）只覆盖排水完成与 transient 退避两个锚点，二者均不含「run 正常终态但零提交」的保全与检测——属系统性残留缺口而非一次性失误。守卫虽兜住了「无据产物不合并且重派」，但时点在成果丢失之后。结论：每个零提交 run 以整轮重做（实测 32-36min/轮）为代价，值得修复。
  - 建议：对 run 终态增加两道检查：①分支相对 main 零新 commit 即判异常终态并携带原因透传（区分截断/忘记提交）；②正常终态但有未提交产物时先 stash/快照留档再清理 worktree。另把「最终必交付物清单」纳入实现者 prompt 的收尾自检段，防整轮漏交付。

### 可改进
- **环境健全性门仅探根 HTTP**
  - 影响：复发敞口：环境故障期间健全性门探针仍报「健康」而 10 场景 blocked-env（当日实测），环境真实故障无法在批次执行前暴露，每轮仍空跑 27 场景全量批次（约 1.5-2min），故障期逐轮重复消耗。
  - 证据：16:14:30「环境健全性门: 候选=18, 探针=健康, blocked-env=10 — HTTP 探测 http://127.0.0.1:43453: 连通」；风暴 11 轮中该现象反复出现；B1（b04843ed）上线后白屏场景由静默放行改为 blocked-env，暴露此前被掩盖的环境性失败。
  - 调查评估：已核实：健康门只做根可达性探测，未覆盖场景实际依赖的 mock API 与 SSE 推送面，故出现「根 HTTP 通 + 场景全断」并存的矛盾诊断（记忆中的 mock_api 无 status 字段、列表端点被 SSE 覆盖竞态同属该依赖面）。B1 上线使环境性失败由被掩盖转为显式 blocked-env，风暴正是该面故障的集中暴露。根因在验证环境契约缺少「场景依赖面多探针」定义；add-verify-multi-kind-runner 的 sse_connect 属场景内执行步骤、与预检探针互补不重复，add-scenario-defect-triage-gate 管场景文件、不涉环境依赖面。结论：多探针健全性门是环境故障早暴露、防整批空跑的可行立项点。
  - 建议：立项 SPEC：健全性门扩展为多探针——按场景集依赖的 API 端点/SSE 面逐一探测，任一不健康即短路整批执行并输出含各级探针明细的诊断块，供 pm_engine 判定 blocked-env 或待环境恢复，取代单一根 HTTP 探测。

- **视觉 SSIM flaky 每轮 7-19 场景**
  - 影响：复发敞口：每轮 27 场景中 7-19 个仅截图 SSIM 失败（0.68-0.93 低于阈值）而 DOM/功能断言全过，6 轮 judge 均需重新归因，终验仍带 19 warning 入库；同类时序敏感 SPEC 将持续承受此归因 token 与验证时长。
  - 证据：judge 1788945507/1788947632/1788959262/1788960304/1788961185/1789000547 六轮 flaky 计数 1/8/7/6/8/19，全部标注「视觉 SSIM 时序抖动、DOM 断言通过、无 console error」；终验 1789000547「verified，19 warning 全 flaky」。
  - 调查评估：已核实：flaky 集中在弹窗/菜单/状态位等截图时序敏感 web 场景，属拍照未 settle 的视觉校验噪声而非功能缺陷；框架已有跨轮指纹比对复用既往判定（终验「跨轮已裁决 8 场景原样写回」），但首轮仍需全量执行+逐场景归因，每轮 7-19 个 warning 显著拉长 judge 档期。现有 SPEC 链（triage 分类/守卫/暂停语义）均不涉截图稳健性，无重叠。结论：verify_engine 视觉校验稳健性（settle 等待/自动重拍/阈值校准）是独立、可量化、修复面明确的立项点。
  - 建议：立项 verify_engine 视觉校验稳健性 SPEC：截图前按场景类型增加 settle 等待、SSIM 低于阈值自动重拍（限次）、按弹窗/列表/整体页分类校准阈值，目标把每轮 flaky 噪声压到 <3 并缩短首轮判定时长。

- **run 终态零提交缺保全与异常检测**
  - 影响：复发敞口：run 结束判定不校验「分支相对 main 是否有新 commit」，也不对工作区未提交产物做保全，收口清理即全丢；本次两案合计 68min 首轮实现白耗，每次复发的单轮代价为整轮重做（实测 32-36min）。
  - 证据：credibility a1 转录末行 01:31:34 为中断的 git add 工具调用、01:31:39 守卫随即打回；wip a1 转录 280/337 行有 pytest 15 passed 但全程无 commit；两份 dispute-judge 裁决均确认「分支零提交、产物随 worktree 清理丢失」。
  - 调查评估：已核实：两 run 均为「正常终态却零提交」，产物在守卫打回后随 worktree 清理全部丢失。既有机制覆盖边界已核实：interrupt-recovery-preserve 只覆盖「排水超时 terminate 在跑 run」（前置条件 branch ahead>0），wip-checkpoint 锚点 A/B 只覆盖排水完成与 transient 退避两个生命周期点，均未覆盖「run 自然终态但有未提交产物」——本次正是该盲区实证。守卫兜底有效但时点滞后于成果丢失，属『先损失后告警』。结论：run 终态统一保全+零提交异常检测是明确可立项的系统性缺口，与既有两 SPEC 互补不重复。
  - 建议：立项/扩项 SPEC：run 生命周期收口路径统一增加「有未提交产物→stash/快照留档并取证」「零提交→异常终态并携带原因」双检查，配合守卫打回信息把缺件清单直接回灌重派 run，消除整轮重做。
