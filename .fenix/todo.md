最近两天的SPEC经历了许多曲折，速度慢，烧钱也多。你今晚自省时重点关注最近两天超过1个小时完成的SPEC，分析它们的耗时，除LLM网关延迟外，有什么是框架可改进的地方

## 2026-09-10

### 浪费
- **验证五连 blocked-env 空转暂停未硬生效**
  - 影响：第 3 轮实现合并（23:22）后验证连打 5 轮全 blocked-env，空转至次日 02:00（约 2.5h 墙钟、该窗口 .fenix/runs/ 无任何新验证 run 产物）；SPEC 全链 3 轮实现+1 次 plan+6 次 judge 累计 $163.84 / 158.7M tokens，收官停在 implemented（未验证）需人工处置
  - 证据：fenixd.log 16:10Z/16:12Z WARNING「第 1/2 次重验」、16:14Z/17:09Z/18:00Z ERROR「连续 3/4/5 轮全部 blocked-env，疑为 mock/SSE 推送环境故障，暂停自动重验」；STATE.md add-spec-status-modal-budget error 同文案、_cost_usd 163.836、_tokens_in 158688205
  - 调查评估：已核实：第 3 轮合并后验证重验轮次从 00:10 打到 02:00，三次 ERROR 判「暂停」后第 4/5 轮仍被拉起，暂停未硬生效；该窗口内无对应 judge run 文件，说明验证会话在 runner 层即被环境阻断（连转录都没产出）。根因：mock/SSE 推送环境故障未被前置探测，框架在已知环境失联下继续按重验节奏调度；B1 门禁（b04843ed 白屏降级 blocked-env）让环境性失败不再被静默放行——语义正确，但暴露的是环境本身未修复（内存记忆已载：浏览器 mock_api 忽略 status 参数、SSE 覆盖竞态）。与 fix-verify-verdict-visibility / add-verify-multi-kind-runner 的验证环境知识一致，无在飞 SPEC 覆盖「环境健康判定」。结论：环境性失败须与产品失败分流，硬暂停语义值得立项（见 improvements[0]）。
  - 建议：blocked-env 连续 ≥2 轮即硬暂停并升级 admin，暂停后禁止自动重验再次拉起（当前第 3 轮暂停后 4/5 轮仍被执行）；暂停期间不调度任何验证 run

- **瞬态错误致实现首轮中断重做**
  - 影响：首轮实现 23:03–00:06 共 63min（276 条 assistant 消息）因瞬态错误中断零产出，第二轮从零重做 40min/$17.90；SPEC 累计 $27.09 未含首轮成本，实际更高
  - 证据：impl-fix-verdict-retry-misattribution-1788966172-a1 末尾 records 为 interrupted/error/transient_retry 且无 result；fenixd.log 16:06:47Z「Transient error attempt 1 in-place retry 1/3 after 30s backoff」后 19 秒即 16:07:06Z「Recovering interrupted SPEC」；第二轮 impl-1788971827 39.9min/$17.90；git log 该 SPEC 仅 2c433e9d 一个实现提交
  - 调查评估：已核实：in-place retry 声明的瞬态重试未能救回会话——19 秒内转为 Recovering interrupted，进程级死亡导致首轮 63min 工作全丢（独立 worktree 未提交内容在第二轮全新 worktree 中不可见）；首轮成本未计入 STATE _cost_usd（27.09 = 第二轮 17.90 + plan 5.45 + judge 3.74，账实不符）。根因：run 级无 checkpoint/恢复协议，瞬态失败=整轮重做，且中断 run 成本漏账影响预算告警阈值判断。与 fix-provider-transient-backoff（活跃，未归档）互补：其仅覆盖 API 请求级 in-place 重试，未覆盖会话/进程级中断。结论：checkpoint 续跑 + 中断成本入账为系统能力缺口（见 improvements[2]）。
  - 建议：实现 run 按任务阶段周期落 checkpoint，瞬态中断后从 checkpoint 续跑而非新开 worktree 从零开始；无 result 的中断 run 成本计入 SPEC 的 _cost_usd/_tokens_in

- **新验证流程 planner 白烧 7.5 分钟**
  - 影响：planner 未生成有效场景（status=None），白烧 7.5min/$2.28，降级旧版 verifier 补跑 12.6min/$2.48 且报告由框架合成；新验证流程（planner 出题→judge）首次实战即失败
  - 证据：fenixd.log 15:39:18Z ERROR「Planner 未生成有效场景 'add-verdict-contract-singularity'（status=None，run=planner-plan-add-verdict-contract-singularity-1788967907-a1，白烧 7.5min）— 降级旧版 verifier」；run 1788967907 duration 7.1min cost $2.28；verify-add-verdict-contract-singularity-1788968358 12.6min/$2.48
  - 调查评估：已核实：add-verdict-contract-singularity 实现合并（23:31）后新验证流程 planner 出题返回 status=None，pm_engine 判白烧并降级旧版 verifier，最终验证报告为框架合成（验证报告闸门 WARNING 15:52:25Z）。根因：planner 出题失败无内联重试、无失败诊断即降级，属系统缺口而非一次性失误。与 add-planner-efficiency（活跃，路由地图/生成节流/延迟直方图）互补：其优化 planner 轮次与延迟，未覆盖「出题失败重试与降级留痕」。结论：低成本改进，值得直接落地。
  - 建议：planner 出题 status=None 时把失败原因内联进 prompt 重试一次，仍失败才降级；降级须在验证报告标注降级原因与代价

### 失误
- **跨轮场景写回缺陷拖出第三轮实现**
  - 影响：第 1 轮验证 27 场景 20 失败中 19 个为 test-defect（12 个跨轮已裁决场景原样写回未自建夹具），第 2 轮验证仍以场景缺陷失败，拖出第 3 轮实现 97min/$24.35 主要修场景文件；三轮实现累计 $119.37 + 出题 plan 144min/$22.55 产出即缺陷场景
  - 证据：verification-report.md（2026-09-09T10:15:51Z 合成）「12 个跨轮已裁决场景原样写回（行选择器未匹配/项目列表空，seed 未自建 registry 夹具）+ 7 个新增 test-defect，唯一真 bug 为 clamp_impl_run_budget 非整数强转」；commit 6faace7d「复核失败有效性并修复场景文件缺陷」；impl 三轮成本 31.15+63.87+24.35、plan 1788935322 143.8min/$22.55、round-2 三次 judge $9.27
  - 调查评估：已核实：round-1 验证把 20 个失败中 19 个归因为 test-defect，唯一产品 bug（clamp 非整数强转）第 2 轮 166min/$63.87 已修，但其验证（21:07/21:25/21:39 三次 judge，$9.27）仍失败，第 3 轮实现标题即「复核失败有效性并修复场景文件缺陷」——整轮消耗在框架自身出题缺陷上；出题 plan 单独烧掉 144min。根因：planner 出题跨轮写回已裁决场景时未重跑 seed 夹具、行选择器/antd 双汉字空格/弹窗遮罩等已知 test-defect 模式无 judge 前静态预检。与 fix-frozen-scenario-orphan-reservoir（已归档，写端 schema 门/加载净化/replan 消费硬门）互补但未覆盖「seed 自建校验」与「已知模式预检」。结论：场景静态自检前置可省一个实现轮 + 至少两轮 judge。
  - 建议：场景文件进 judge 前做静态自检：seed 步骤须自建 registry 夹具（禁止依赖跨轮残留）、行选择器存在性、antd 双汉字按钮空格等已知模式；检出缺陷直接归场景侧并就地修复，不占用实现尝试预算

- **实现预算闸门未收口 token 超限 58%**
  - 影响：100M token 预算第 2 轮结束即超（132.23M/134.77M 告警），第 3 轮仍启动续跑至 158.7M（超 58.7%）；实现尝试 used=3 用尽后 SPEC 悬停在 implemented（未验证）而非冻结 blocked，留人工处置尾巴
  - 证据：fenixd.log 13:04Z/13:23Z「token budget alert (warning) for 'add-spec-status-modal-budget': 132.23M/134.77M / 100M」；STATE.md _tokens_in 158688205、_impl_run_budget_used 3、status implemented + error「连续 5 轮…」；15:22:43Z state_machine ERROR「Invalid transition: blocked → implemented」
  - 调查评估：已核实：token 预算超限仅告警不阻断，第 3 轮照常启动；used=3 用尽后因末轮验证为 blocked-env（非 bug-found）状态机无收口路径，SPEC 停在 implemented 而非 blocked，且合并轮出现 blocked→implemented 非法迁移报错，状态漂移可见。根因：预算闸门缺 warning→pause→freeze 档位；blocked-env 终态无「预算用尽强制冻结」规则。与 add-spec-status-modal-budget 自身（本 SPEC 恰是实现次数预算功能）互为表里：次数预算已实现，token 预算硬停与终态收口仍是洞。结论：预算闸门加硬档位 + 环境性终态强制落 blocked 可立项。
  - 建议：token/实现预算提供 warning→pause→freeze 可配档位（超 100% 硬停）；验证终态为 blocked-env 且实现预算用尽时强制落 blocked 等 admin，杜绝 implemented 悬置

### 可改进
- **验证前置环境健康探针缺失**
  - 影响：复发敞口：同一环境故障窗口内两个 SPEC 受害——add-spec-status-modal-budget 五连 blocked-env 空转约 2.5h 墙钟，fix-verdict-retry-misattribution 因「env 失败场景不得判 verified」被洗白门禁拦截而 blocked（01:57）；B1 门禁收紧后环境性失败不再被静默放行，单次复发的验证空转代价以本轮实测为参照（验证轮无 run 产物但吞噬墙钟与调度）
  - 证据：fenixd.log 17:57:21Z「verified 洗白门禁拦截 'fix-verdict-retry-misattribution': env 失败场景不得判 verified（须升级 admin 处置）」+「验证环境阻塞第 1 轮，自动呼叫 Administrator」；同窗口 add-spec-status-modal-budget 五连 blocked-env；b04843ed「B1 白屏降级 blocked-env——首帧 8s 超时不再静默放行」
  - 调查评估：已核实：17:57:21Z 洗白门禁正确拦截 env 失败场景（fail-closed 语义，fix-verdict-read-failclosed 落地），但同一时段的两个 SPEC 都因环境而非产品被卡——环境故障是共同根因；serving_registry 只登记 serving 实例不做健康检查（16:17Z/17:17Z「harvested … without in-flight spec」）。根因：框架缺验证前置环境健康判定，把环境故障当验证轮次反复消耗。与 add-verify-multi-kind-runner / fix-verify-verdict-visibility 环境知识一致，无在飞 SPEC 覆盖。结论：mock/SSE 连通性探针 + 环境性失败分流语义可立项，直接治本。
  - 建议：验证轮前探测 mock server / SSE 推送连通性（可复用 playwright-cli 自检脚本），不健康即跳过 judge 直判 blocked-env 并升级 admin；同时修复浏览器 mock_api 无法模拟 status/SSE 推送的环境缺口

- **验证场景全量重跑无增量裁剪**
  - 影响：复发敞口：6 次 judge 全部全量 27 场景（单次 4.9–31.3min、$1.46–6.00，累计 $21.92），三轮实现每轮内部验证往返亦全量回归；按变更影响面裁剪场景子集预计省 50-60% 验证 token 与墙钟（以本轮单轮 judge 时长为参照）
  - 证据：planner-judge-add-spec-status-modal-budget-1788944150/1788945507/1788947632/1788959262/1788960304/1788961185 六轮全量 27 场景（duration 4.9–31.3min）；三轮实现 95.1/166.2/96.8min 均含全量回归
  - 调查评估：已核实：同一批 27 个场景在三个实现轮与六次 judge 中反复全量执行，且第 2/3 轮验证场景与第 1 轮几乎相同（跨轮写回，见 mistakes[0]），验证成本与实现轮次成正比放大。根因：验证无「变更影响面」裁剪，实现侧改动点（如 core/pm_engine/budget.py）本可只跑 CLI/单测类场景子集。与 add-planner-efficiency 路由地图互补：地图省 planner 逐轮 grep 取证，本项省场景执行量。结论：按变更文件域映射场景子集、终轮才全量的增量验证值得立项。
  - 建议：验证按本轮实现变更文件域映射场景子集（改核心逻辑只跑 CLI/单测类场景，改 dashboard 才跑 web 场景），仅终轮/验收轮做全量；增量缺映射时降级全量并在报告标注

- **run 级 checkpoint 恢复与中断成本入账缺失**
  - 影响：复发敞口：瞬态失败即整轮重做，本轮 fix-verdict-retry-misattribution 首轮 63min 全丢、重做 40min/$17.90（waste[1] 实测）；且中断 run 成本未计入 _cost_usd，SPEC 级成本核算与预算告警阈值因此失真
  - 证据：waste[1] 全部证据；STATE.md fix-verdict-retry-misattribution _cost_usd 27.088（=第二轮 17.90+plan 5.45+judge 3.74，首轮缺失）；fix-provider-transient-backoff 仍在 spec/changes/ 活跃未归档
  - 调查评估：已核实：fix-provider-transient-backoff 的 in-place retry 只覆盖 API 请求级瞬态，本次实证在进程/会话级中断时失效（retry 声明 19 秒后即 Recovering）；run 无阶段 checkpoint，中断即从零重做，成本也无归集。根因：run 生命周期缺 checkpoint/恢复协议与中断成本核算。与 fix-provider-transient-backoff（活跃）互补不重复：其解决请求级重试，本项解决会话级恢复与账实。结论：implementer 阶段 checkpoint + 无 result run 成本入账作为系统能力可立项。
  - 建议：为 implementer run 定义阶段 checkpoint 协议（每完成一任务阶段落盘工作树快照/任务进度），瞬态中断后续跑同一 worktree 而非新开；成本核算把无 result 的中断 run 计入 SPEC 的 _cost_usd 与 _tokens_in
