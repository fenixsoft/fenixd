## 2026-10-02

### 知识真相源
- audit 疑点升级待人工（聚合）：10 条待人工仲裁（最长龄期 4 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

## 2026-10-03

### 浪费
- **code-fix 连续 4 天 04:31 双 run 死于网关拒模型，单批损失 28 分钟工作量**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：code-fix 车道（夜间批量修复 code-review 审查台账的维护车道）连续 4 天在每日本地 04:31 前后各报废 2 个 run，累计 8 个；最重的一次（run code-fix-1790884995）跑了 28 分 07 秒、368 轮 API 往返、789 turns、372 次工具调用（含 84 次 Edit），全部随弃树蒸发，同批条目由后续批次重做一遍；每天还额外烧一次 0 轮秒败派发。
  - 证据：fenixd.log 中 4 天失败时刻精确到秒复现（UTC 20:31:22.8 / 23.4 / 23.1 / 22.2）：09-28 run code-fix-1790627269（1 轮）与 code-fix-1790627486（0 轮）、09-29 code-fix-1790713696 与 1790713886、09-30 code-fix-1790800112 与 1790800286、10-01 code-fix-1790884995（368 轮）与 1790886686（0 轮），stderr_tail 均为 [claude-code:unrecognized_model]（模型网关拒绝 glm-5.3-flash 的报错），exit_code=1、api_timeout=True（单轮 API 请求超时/错误终局签名）；日志行 33221/36106/38182/38795。
  - 调查评估：已核实：失败 run 无分支留存（git branch 无 fenix/code-review-fix-1790884992/1790886683），worktree_manager 记「Cleaning up worktree ... (success=False)」；死亡时工作区干净，api_timeout 终局的 WIP salvage（未提交现场即时抢救提交，evo-code-fix-api-timeout-salvage 2.1）按设计跳过。损失边界已核实为重复算力而非发现丢失：台账 .fenix/code-review/items.jsonl 共 4082 条、open 为 0，被弃两批涉及文件的 10 条抽样 findings 已于 20:03/22:33 UTC 由同链其他批次解决。根因：失败时刻跨 4 天精确到秒复现、窗口仅约 100 秒（20:33:07 起的第 5 批即成功），判定为上游模型网关每日固定窗口短暂拒绝 glm-5.3-flash（具体根因未核实，无法从仓内取证）；run 本身无失误。与存量工作关系：add-provider-failover 的切换冷却与拒模型快切（provider_circuit.py）覆盖 spec/impl 车道，code-fix 车道本次未触发任何切换/冷却路径，车道按 api_timeout 签名走 salvage 后 4 秒即重派下一批、再次撞进同一窗口；active 区 add-provider-health-check 是人工一键健康检测，不覆盖自动耐受。结论：外部窗口 × 车道无耐受的系统性浪费，逐日复发中。
  - 建议：先加只读观测：对「同一 stderr 签名 + 同刻连发 ≥2 天」做跨日聚合告警，把上游窗口显性化；随后按改进条给 code-fix 车道接拒模型短冷却，避免窗口内重派。


## 2026-10-04

### 浪费
- **（恶化）04:31 网关窗口第5夜复发并扩大为全车道瞬态风暴**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：上游 provider 瞬态致 3 次全局派发冻结（每次 600 秒，合计 30 分钟）加 2 次探测失败复冻；2 个重 run 蒸发（code-fix-1790965068 约 14 分钟 456 轮 977 turns、evo-1790965399 约 19 分钟 672 turns 348 次工具调用且产物仅回收 4/11、缺 7 条下轮重做），code-fix 车道连续第 5 夜在 04:31 窗口损失在跑批（本次 4 轮约 8 分钟）；窗口内失败 run 合计 14 个，多为 0-6 轮秒败、单次代价小。
  - 证据：Global transient break（全局瞬态熔断，5 次失败/600 秒即冻结全部新派发）触发于 UTC 18:32:21、20:31:23、20:48:48，探测复冻于 18:45:21 与 19:00:22；run evo-1790965399 于 19:06:58 UTC 报「水位不推进：产物部分恢复仅 4/11 条」（fenixd.log 行 40046-40049）；run code-fix-1790965068 于 19:04:02 UTC api_timeout 终局且工作区干净、按设计跳过 salvage 全弃；run code-fix-1790972696 于 20:32:27 UTC 死亡（exit 1 加 api_timeout=True），与既有条目 4 天记录的 UTC 20:31 窗口同刻，为连续第 5 夜；36 次 in-place retry（原地重试）样本 provider 均为 bigmodel.cn。
  - 调查评估：在 code-fix 夜间批与 8 个 evo spec 的出题/实现/评审并行推进时暴露。已核实：根因是上游 provider（bigmodel.cn）连接类瞬态，非框架失误；耐受机制按设计工作——36 次原地重试救回大部分在跑 run，进化产物部分回收 4/11 由已落地的 evo-add-evolution-product-salvage（自进化产物抢救，5/5 任务验证通过）完成，缺失 7 条由下轮幂等去重补齐、无永久丢失。与存量工作关系：10-03#可改进#1 对应的 evo-add-codefix-conn-error-cooldown 已于当晚合并（5dcf0666），但本窗口未见冷却武装痕迹（fix-progress.json 的 switch_cooldown_until 仍为 null、新 signal_type 告警 0 条），code-fix 下一批 20:41:57 才派出更可能由 20:31 的全局冻结代偿——冷却是否真能拦截本死因，归因未证实；另该 spec 非目标栏已声明 administrator/self-review/evolution 等兄弟车道同型盲点留待后续。结论：外部瞬态为主因、损失已被压到个位 run，不值得新立项；残余缺口是冷却触发的可观测性与分类词表对本死因（api_timeout 终局形态）的覆盖。
  - 建议：给 code-fix 车道冷却（_arm_switch_cooldown）补「触发/跳过」双侧日志留痕（现状仅写盘异常落 WARNING），下一个同刻窗口按日志归因验证拦截效果；同时复核连接类失败分类词表对 api_timeout 终局加工作区干净形态的命中，未命中则扩词表而非新增机制。

### 失误
- **全局告警误选 spec 处置动作，失败仍记 resolved**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：1 条 critical 级 daemon_errors 信号（告警 ce27a93f9dca，即 spec_review 评审 run 连败指纹 10 分钟内复现 2 次的升级信号）以未执行的动作收口：处置动作 retry_review（重派评审）执行失败，信号却回写 handled=true 与 result=resolved，处置台账与实际动作不符；本次无直接算力损失（底层评审已由 orphan ready 恢复自愈重派并通过），风险在处置记录可信度与同类信号的处置有效性。
  - 证据：2026-10-02T20:29:59Z admin_monitor 同秒双日志：「处置终态（result=resolved）已回写信号 handled=true（id=ce27a93f9dca，daemon_errors）」与「处置 choice 执行失败 choice_id=retry_review spec='global': spec not found: global」（fenixd.log 行 40820）；该告警记录 spec=null（全局指纹信号无关联 spec），处置方为 admin run admin-global-1790972103（35 轮、82 turns）。
  - 调查评估：在处置 spec_review 连败升级信号时暴露。已核实：retry_review 是 spec 作用域动作（需按 spec 名查状态机重派评审），而全局信号 spec=null 被占位为字符串 'global' 直接查证失败；终态回写不校验 choice 执行结果，动作失败与 resolved 并存，且告警记录 action_taken 与 result 字段均为 null、未留实际动作痕迹。根因归属：通道设计缺口而非 admin 会话单次失误——「全局信号 × spec 作用域 choice」组合无路由防护，任一全局告警选到此类动作都会复现。与存量工作关系：active 区 add-adjudication-alert-narrative（告警叙事）与 evo-signal-preprobe-handled-writeback（预探写回）均不覆盖处置路由。结论：低频（窗口内 8 条处置仅 1 次失败）但属通道正确性缺口，值得一次小专项。
  - 建议：execute_adjudication_choice 对 spec 为空或占位 'global' 的信号过滤 spec 作用域 choices（retry_review 等）或提供全局等价动作（如「自愈确认/继续观察」）；choice 执行失败时 MUST NOT 回写 resolved（改 failed 并保留信号待重审），并把 choice 执行结果写入告警 action_taken 字段留痕。

### 可改进
- **code-fix 合回冲突整批即弃，完工产物全重做**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：复发敞口：一整条链完工后毁于合回冲突即全量重做——本次实测 2 个 run、700 turns、350 次工具调用全弃（resolved=0、2 条台账条目被忽略后由新链重做），约 1 小时批处理算力双倍消耗；该类「合回冲突即弃」10 天内已第 4 次（09-23、09-24 两次、本次），按每 3-4 天一次的频度持续放血。
  - 证据：2026-10-02T21:29:32Z code-fix 第 1 批回归未通过定向重试，21:34:48 重试 run code-fix-1790976572 完成（25 轮），21:40:52 合并预演检出分支 fenix/code-review-fix-1790973716 与 main 在 core/state_machine.py 语义冲突，随即「现场即弃（branch/tip_sha 入档案）」并出链终局 rollup（runs=2 turns=700 tool_uses=350 resolved=0 ignored=2），21:41:57 新链释放失败档案重做；冲突前 1 小时内 main 侧同文件刚被 evo-fix-resume-base-branch-portability 落地推进（commit 749d3e88 及其合并 3a9ff694，UTC 20:56-20:57）。
  - 调查评估：在 code-fix 夜间批与 evo 管线夜间批量合回并行时暴露。已核实：合回冲突在 core/code_fix.py:4436-4465 属「真冲突」分支，按 selfheal D2 设计整批现场即弃（branch/tip_sha 入失败档案、条目带 fail_count 预算下轮自动重试），仅主树 WIP 预检阻断（wip_gate_blocked）走 defer 零预算路径；根因是链生命周期约 1 小时内基线前移，批完工才首次做合并预检，检出即全弃——而分支按 add-codefix-commit-first-contract 契约（已归档）本就逐条 commit，条目级回收在结构上可行。与存量工作关系：evo-merge-back-wip-overlap-gate（在飞、0/10 任务）只管主树未提交 WIP 重叠，不覆盖已提交内容冲突；evo-fix-resume-base-branch-portability 已统一基线分支解析，rebase 目标现成。结论：确定性缺口、复发频度稳定，值得立项。
  - 建议：起草 SPEC：合回冲突即弃前插入一次定向救回——分支 rebase 到当前基线（复用统一基线解析器）并重跑批回归，最多 1 次；rebase 仍冲突则按条目 commit 粒度 cherry-pick 回收非冲突条目（commit-first 契约已保证提交边界），仅冲突条目入失败档案计 fail_count，验收以「冲突即弃链的 turns 重复消耗下降」为准。
