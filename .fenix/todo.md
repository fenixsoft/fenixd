
## 2026-10-02
### 知识真相源
- audit 疑点升级待人工：contradiction（spec/knowledge/domains/dashboard-platform/v2-data-adapters.md × spec/knowledge/domains/dashboard-platform/v2-sdk-vendor.md）连续 2 轮复核无确定性判定，请人工仲裁；消费后删除 .fenix/knowledge_audit_findings.json 对应条目即恢复自动复核
- audit 疑点升级待人工：contradiction（spec/knowledge/domains/dashboard-platform/v2-data-adapters.md × spec/knowledge/domains/dashboard-platform/v2-legacy-coexist.md）连续 2 轮复核无确定性判定，请人工仲裁；消费后删除 .fenix/knowledge_audit_findings.json 对应条目即恢复自动复核
- audit 疑点升级待人工：contradiction（spec/knowledge/domains/dashboard-frontend/task-progress-phase-display.md × spec/knowledge/domains/implementer-lane/artifact-path-declaration.md）连续 2 轮复核无确定性判定，请人工仲裁；消费后删除 .fenix/knowledge_audit_findings.json 对应条目即恢复自动复核


## 2026-10-03

### 浪费
- **code-fix 连续 4 天 04:31 双 run 死于网关拒模型，单批损失 28 分钟工作量**
  - 影响：code-fix 车道（夜间批量修复 code-review 审查台账的维护车道）连续 4 天在每日本地 04:31 前后各报废 2 个 run，累计 8 个；最重的一次（run code-fix-1790884995）跑了 28 分 07 秒、368 轮 API 往返、789 turns、372 次工具调用（含 84 次 Edit），全部随弃树蒸发，同批条目由后续批次重做一遍；每天还额外烧一次 0 轮秒败派发。
  - 证据：fenixd.log 中 4 天失败时刻精确到秒复现（UTC 20:31:22.8 / 23.4 / 23.1 / 22.2）：09-28 run code-fix-1790627269（1 轮）与 code-fix-1790627486（0 轮）、09-29 code-fix-1790713696 与 1790713886、09-30 code-fix-1790800112 与 1790800286、10-01 code-fix-1790884995（368 轮）与 1790886686（0 轮），stderr_tail 均为 [claude-code:unrecognized_model]（模型网关拒绝 glm-5.3-flash 的报错），exit_code=1、api_timeout=True（单轮 API 请求超时/错误终局签名）；日志行 33221/36106/38182/38795。
  - 调查评估：已核实：失败 run 无分支留存（git branch 无 fenix/code-review-fix-1790884992/1790886683），worktree_manager 记「Cleaning up worktree ... (success=False)」；死亡时工作区干净，api_timeout 终局的 WIP salvage（未提交现场即时抢救提交，evo-code-fix-api-timeout-salvage 2.1）按设计跳过。损失边界已核实为重复算力而非发现丢失：台账 .fenix/code-review/items.jsonl 共 4082 条、open 为 0，被弃两批涉及文件的 10 条抽样 findings 已于 20:03/22:33 UTC 由同链其他批次解决。根因：失败时刻跨 4 天精确到秒复现、窗口仅约 100 秒（20:33:07 起的第 5 批即成功），判定为上游模型网关每日固定窗口短暂拒绝 glm-5.3-flash（具体根因未核实，无法从仓内取证）；run 本身无失误。与存量工作关系：add-provider-failover 的切换冷却与拒模型快切（provider_circuit.py）覆盖 spec/impl 车道，code-fix 车道本次未触发任何切换/冷却路径，车道按 api_timeout 签名走 salvage 后 4 秒即重派下一批、再次撞进同一窗口；active 区 add-provider-health-check 是人工一键健康检测，不覆盖自动耐受。结论：外部窗口 × 车道无耐受的系统性浪费，逐日复发中。
  - 建议：先加只读观测：对「同一 stderr 签名 + 同刻连发 ≥2 天」做跨日聚合告警，把上游窗口显性化；随后按改进条给 code-fix 车道接拒模型短冷却，避免窗口内重派。

### 失误
- **code-fix 提示词占位符漂移 10/11 run 命中，注入内容疑静默丢失**
  - 影响：窗口内 11 个 code-fix run 有 10 个（91%）派发即触发「提示词占位符未解析」警告（模板漂移检测：提示词里的 {xxx} 占位符没被填充值替换，意味着应注入的上下文可能整段缺失），残留键 8 组、累计全 log 76 次——每处残留都是一段静默丢失的注入内容，直接削弱修复批次拿到的指令完整性。
  - 证据：fenixd.log 窗口内 10 条 WARNING（19:47–22:59 UTC），如 run code-fix-1790884995 leftover=['{event}','{spec}']（日志行 38784）、code-fix-1790886686 leftover=['{e}','{signal_type}']（38802 行）；检测器在 core/agent_runner/prompt_builder.py:103-134（_fill_and_scan_placeholders，warning 不阻断派发）。
  - 调查评估：已核实：同一键组跨 run 确定性复现（{e}+{signal_type} 3 次、{event}+{spec} 2 次、{doc} 2 次）——复现集相同说明是模板与填充字典的系统性漂移，不是随机正文字面量；检测器只扣除本次 values 已知键、无白名单，故个别单例键（{saving}/{prefix}）仍可能是合法字面量误报。根因归属：多条独立 prompt 构建路径的模板与各自 values 字典长期失配、告警无人消费（连续多日在 log 里存在）——系统性缺口而非单次失误。调查受限点：警告只打印键名、不含模板名与调用点，prompt 全文不落盘，是否有真实内容丢失未能回溯核实（未核实）。与存量工作关系：active 区 add-codefix-affinity-batching、decouple-codefix-review-lanes、evo-code-fix-api-timeout-salvage 均不覆盖模板治理；code-review 台账修过该检测器周边防御（commit f48b4793，10-02 03:51），但 leftover 键清单治理无对应 SPEC。结论：值得一次小规模专项清淤。
  - 建议：两步走：先给警告补模板标识与调用点（一行级改动），按键聚类定位到具体模板，区分「真漂移补键」与「字面量加白名单」；再补一个渲染断言测试（每个模板 × 其填充字典全集渲染后 leftover 必须为空）防回潮。

### 可改进
- **code-fix 车道缺拒模型短冷却，秒败派发 4 秒后撞同一窗口**
  - 影响：复发敞口：按近 4 天实测，每开放一个此类上游窗口即白烧 2 个 run（一个带真实工作量的在跑批次 + 一个 0 轮秒败派发），10-01 单次实测代价为 28 分钟 agent 时间、368 轮 API 往返加同批条目整批重做（27.1 轮/条 × 该批条数）。
  - 证据：第 3 批 run code-fix-1790884995 于 UTC 20:31:22 死后，worktree_manager 20:31:23 即建第 4 批工作树、20:31:26 派发（run code-fix-1790886686），20:33:04 同因秒死；20:33:07 的第 5 批（run code-fix-1790886787）正常完成（229 轮、resolved 20/20）——可推窗口约 100 秒，而重派间隔仅 4 秒。
  - 调查评估：已核实：拒绝签名（stderr [claude-code:unrecognized_model] + exit 1 + api_timeout=True）在 spec/impl 车道已有成熟处置——provider_circuit.py 的 SWITCH_ERROR_TEXT_PATTERNS 驱动链前进 + PROVIDER_SWITCH_COOLDOWN_SECONDS=300 跳过冷却，且 add-impl-selfcheck-model-probe 已把 unrecognized_model 从瞬态重试中收窄为「原地切下一模型」；但 core/code_fix.py 全文无 provider 逻辑，本次两条失败未触发任何切换/冷却日志，车道只按 api_timeout 签名走了 salvage 分支（evo-code-fix-api-timeout-salvage，管「现场保住」不管「别再撞窗」）——两 spec 互补、无重复，残余缺口是「车道级推迟重派」。另注意 unrecognized_model 的 stderr 行对 glm/deepseek 链是每 run 必有的定噪行（CLI_STDERR_NOISE_TEXT_PATTERNS），签名识别需带 exit_code/api_error 组合条件，不能裸匹配。结论：可立项，范围小（分类挂接 + 冷却复用）。
  - 建议：起草 SPEC：code-fix 车道失败分类接入切换类错误识别（组合条件：unrecognized_model 行 + exit 1），命中时同链下一批推迟至少一个 switch 冷却（复用 300s 常量语义）而非立即重派；同 SPEC 内落跨日同刻指纹告警（见浪费条建议），验收以「窗口内重派为 0」为准。

- **知识审计 escalated 积压 10 条无人工消费，矛盾规则长期并存**
  - 影响：无新增算力损失（复核轮次封顶 2 后不再重审）；风险是敞口——escalated（复核 2 轮仍无确定性判定、升级待人工仲裁的审计疑点）已积 10 条、最早 2026-09-30 挂起至今 3 天无人仲裁，矛盾中的知识规则持续并存，任何消费相关页面的 agent 都可能按冲突口径行事，且 todo.md 每日重述稀释人工注意力。
  - 证据：.fenix/knowledge_audit_findings.json 共 13 条（10 escalated + 3 suspected）；todo 既有 3 条（2026-10-02#知识真相源#1-3）对应 findings d04dd5120731（task-progress-phase-display × artifact-path-declaration 矛盾）、712c4b3deb6d（v2-data-adapters × v2-legacy-coexist）、aefd0f80f550（v2-data-adapters × v2-sdk-vendor），first_seen 均为 2026-09-30、review_rounds=2、updated_at 2026-10-02；knowledge_audit_state.json 显示审计每日运行（last_audit_date=2026-10-03）。
  - 调查评估：闭环判定：3 条历史条目在 findings.json 中仍为 escalated、未被消费（updated_at 停在 10-02、无 verdict），不判 resolved，继续留 todo。根因：升级通道的唯一消费者是人工，但框架侧无积压聚合、无龄期可见性、条目散着每日重述——不是审计判定能力问题，是消费通路缺设计。与存量工作关系：active 区 evo-add-knowledge-audit-finding-ledger 建的是疑点台账机制本身，不含升级后积压的治理，属互补缺口。结论：低优先但值得顺手治理，否则积压只增不减。
  - 建议：升级条目加聚合出口：todo 侧单条汇总（N 条待仲裁 + 最长龄期）替代逐条重述；超龄条目自动在涉事知识页面顶部注记「已知分歧待仲裁」，让消费方至少不盲信；人工仲裁入口收敛为一个清单文件。
