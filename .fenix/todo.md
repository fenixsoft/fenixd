## 2026-10-02

### 知识真相源
- audit 疑点升级待人工（聚合）：10 条待人工仲裁（最长龄期 5 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

## 2026-10-04

### 浪费
- **（恶化）04:31 网关窗口第5夜复发并扩大为全车道瞬态风暴**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：上游 provider 瞬态致 3 次全局派发冻结（每次 600 秒，合计 30 分钟）加 2 次探测失败复冻；2 个重 run 蒸发（code-fix-1790965068 约 14 分钟 456 轮 977 turns、evo-1790965399 约 19 分钟 672 turns 348 次工具调用且产物仅回收 4/11、缺 7 条下轮重做），code-fix 车道连续第 5 夜在 04:31 窗口损失在跑批（本次 4 轮约 8 分钟）；窗口内失败 run 合计 14 个，多为 0-6 轮秒败、单次代价小。
  - 证据：Global transient break（全局瞬态熔断，5 次失败/600 秒即冻结全部新派发）触发于 UTC 18:32:21、20:31:23、20:48:48，探测复冻于 18:45:21 与 19:00:22；run evo-1790965399 于 19:06:58 UTC 报「水位不推进：产物部分恢复仅 4/11 条」（fenixd.log 行 40046-40049）；run code-fix-1790965068 于 19:04:02 UTC api_timeout 终局且工作区干净、按设计跳过 salvage 全弃；run code-fix-1790972696 于 20:32:27 UTC 死亡（exit 1 加 api_timeout=True），与既有条目 4 天记录的 UTC 20:31 窗口同刻，为连续第 5 夜；36 次 in-place retry（原地重试）样本 provider 均为 bigmodel.cn。
  - 调查评估：在 code-fix 夜间批与 8 个 evo spec 的出题/实现/评审并行推进时暴露。已核实：根因是上游 provider（bigmodel.cn）连接类瞬态，非框架失误；耐受机制按设计工作——36 次原地重试救回大部分在跑 run，进化产物部分回收 4/11 由已落地的 evo-add-evolution-product-salvage（自进化产物抢救，5/5 任务验证通过）完成，缺失 7 条由下轮幂等去重补齐、无永久丢失。与存量工作关系：10-03#可改进#1 对应的 evo-add-codefix-conn-error-cooldown 已于当晚合并（5dcf0666），但本窗口未见冷却武装痕迹（fix-progress.json 的 switch_cooldown_until 仍为 null、新 signal_type 告警 0 条），code-fix 下一批 20:41:57 才派出更可能由 20:31 的全局冻结代偿——冷却是否真能拦截本死因，归因未证实；另该 spec 非目标栏已声明 administrator/self-review/evolution 等兄弟车道同型盲点留待后续。结论：外部瞬态为主因、损失已被压到个位 run，不值得新立项；残余缺口是冷却触发的可观测性与分类词表对本死因（api_timeout 终局形态）的覆盖。
  - 建议：给 code-fix 车道冷却（_arm_switch_cooldown）补「触发/跳过」双侧日志留痕（现状仅写盘异常落 WARNING），下一个同刻窗口按日志归因验证拦截效果；同时复核连接类失败分类词表对 api_timeout 终局加工作区干净形态的命中，未命中则扩词表而非新增机制。


## 2026-10-05

### 浪费
- **04:31上游瞬态窗口第6夜复发，在跑批仍死但首次零蒸发**
  - 影响：上游 provider 瞬态窗口连续第 6 夜在本地 04:31 前后击杀在跑 code-fix 批（夜间批量修复 code-review 台账的车道），但本次零工作蒸发：整夜只死 1 个 run（此前每晚双 run 蒸发），另致 2 次全局派发冻结（Global transient break，全局瞬态熔断，各 600 秒合计 20 分钟）与全窗口 25 次 in-place retry（原地重试）；整条 code-fix 链最终交付 resolved=127 条台账修复。
  - 证据：run code-fix-1791058640（当夜在跑批）于 2026-10-03T20:32:40Z（本地 04:32）api_timeout 终局（单轮 API 请求超时/错误类终局签名）：142 轮 API 往返、255 turns、144 次工具调用，stderr 为 [claude-code:unrecognized_model]（网关拒模型行），死因为 API Error: Can't reach the API server（ENOTFOUND，DNS/连接失败）；4 秒后告警 93e461c553da（code_fix_switch_window_deferred 冷却武装信号）记录 300 秒冷却生效，告警 76d67a9b9df4（冷却解除信号）记录同链下一批实际推迟 977 秒；fenixd.log 行 44338 记「未提交现场已 salvage 提交到批分支……下批认领继承」（salvage 即未提交现场抢救提交）；23:33:15Z 链 rollup（整链收尾汇总）runs=10 resolved=127 ignored=1；两次全局熔断触发于 19:40:30Z 与 20:25:18Z，25 次原地重试 provider 均为 bigmodel.cn。
  - 调查评估：在 code-fix 夜间批与 evo 管线并行推进时暴露，是 2026-10-04#浪费#1（第 5 夜风暴）的延续：失败同刻（04:31±1 分）复发、根因仍是上游 bigmodel.cn 瞬态（今晚为连接类 ENOTFOUND 与拒模型 stderr 同现），非框架失误。已核实两条既有防线今晚首次同台实弹生效——evo-add-codefix-conn-error-cooldown（code-fix 连接类失败短冷却，merge 5dcf0666）武装并把下一批推迟 977 秒避开窗口，「每晚双 run 死亡」形态消失；evo-code-fix-api-timeout-salvage（api_timeout 终局的现场抢救）把 142 轮未提交现场提交进批分支由下批继承，整链无重做。结论：外部窗口仓内不可修，损失已收敛到「在跑 run 死亡一次、零蒸发」，不值得新立项；残余为每日仍烧一次在跑 run 的死亡-重启开销，以及 10-03 条建议的「同一 stderr 签名 + 同刻连发 ≥2 天」跨日聚合观测仍未落地。
  - 建议：落实跨日聚合只读观测（同一 stderr 签名 + 同刻连发 ≥2 天即聚合告警），把上游窗口显性化为可追踪信号；在跑 run 的单次死亡开销暂容忍，待窗口消失后复核冷却与 salvage 是否可退场。

- **自进化run被后台任务600秒上限击杀，299 turns全重跑**
  - 影响：1 个自进化分析 run（189 轮 API 往返、299 turns、191 次工具调用）连同其派出的 3 个只读核查子代理的半成品全部作废，26 分钟后同任务整体重跑一遍（又耗 166 轮、299 turns），单次事件约双倍消耗一个完整分析。
  - 证据：run evo-1791048570（自进化复核 fenixd todo.md 三条既有条目）于 2026-10-03T17:43:35Z 报「自进化分析 run 失败（水位不推进）: 产物文件未写出」；其转录尾部 stderr 为「Background tasks still running after 600s; terminating. Set CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 to wait indefinitely.」（CLI 后台任务等待 600 秒上限强制终止），result 字段只是中期文案「已派出：3 个只读核查子代理……各子代理完成后我将逐条起草判定」；重跑 run evo-1791049605 于 18:09:17Z 落地完成（3 条目、接受 2、草稿 2）。
  - 调查评估：在自进化 agent（框架自进化复核者）复核 10-04 三条既有条目（网关风暴/告警误记/合回冲突）时暴露。已核实：agent 把核查拆给 3 个后台子代理后结束回合，CLI 按 600 秒后台等待上限强杀仍在跑的子代理，主 run 以中期消息充当 result 终局、产物 json 未写出；框架「水位不推进」探测（产物文件缺失即判失败并重派）正确兜底，重跑因子代理在时限内完成而成功。根因：自进化「派子代理-等待-汇总」工作流与 CLI 后台等待 600 秒上限硬冲突，属编排配置缺口而非模型失误。与存量工作关系：active 区 evo-add-api-stall-observability（API 停滞观测）与 evo-add-impl-run-budget-sizing（run 预算）均不覆盖该上限。结论：确定性缺口，凡子代理核查超 600 秒必复发，值得一次小专项。
  - 建议：给自进化等「派子代理等汇总」型 run 注入 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0（无限等待后台任务），或在进化提示词中约定子代理前台执行、分片结果即时落盘可续跑；并把「result 为中期文案且产物缺失」的失败归因直接指向该上限，省去下轮诊断。

### 失误
- （当日无）

### 可改进
- **评审重试无退避，429风暴18秒烧光3次预算冻住3个spec**
  - 影响：复发敞口：上游瞬态（限流/断连/拒模型）撞上批量评审窗口时，每个 spec 的 3 次评审重试会在约 20 秒内全灭并触发冻结，随后需一次 admin run（告警处置会话，本轮 36 轮）人工解冻；本轮实测 8 个 spec 同时晋升、19:31-19:39 共 34 条评审失败日志、3 个自进化 spec 被冻（evo-add-attribution-dedup-cascade-exemption、evo-fix-v2-devserver-fallback-attribution、evo-fix-verify-parallel-override-type）。
  - 证据：pm_engine（编排引擎）于 19:31:04-09Z 五秒内把 8 个 spec Auto-promoting（自动晋升）drafted→reviewing 并同时派评审；evo-fix-verify-parallel-override-type 三连败时刻为 19:31:12.6/16.8/26.0Z（attempt 1→2→3，重派间隔仅 4.2 秒/9.2 秒，0-1 轮即死）；处置记录 827b4f2fe0c8（本轮 admin run 的终态诊断）核实失败转录 api_error_status=429「您的账户已达到速率限制」（bigmodel.cn 1302）；STATE 冻结标记却套「用户指令冻结」模板；19:40:21Z 经人工裁决通道（channel=manual）解冻重派后 19:47:10Z 评审通过。
  - 调查评估：在 8 个自进化 spec 批量晋升评审时撞上账户级限流暴露。已核实：spec_review 的失败重试是失败即重派、无退避，且把供给类瞬态失败与评审质量失败同权计入 3 次预算，瞬时风暴必然烧光预算误触发冻结；冻结 error 前缀「用户指令冻结」与真实根因无关，误导诊断（admin 需先解包指纹才发现 429）。根因归属：评审车道缺少对限流类失败的分类与节奏控制，系统性缺口而非单次失误。与存量工作关系：evo-add-code-review-ratelimit-resume（全仓审查车道 429 分类+300 秒冷却+剃余重派，STATE 已 pushed）与 evo-add-codefix-conn-error-cooldown（code-fix 车道连接类短冷却，已 pushed）都在兄弟车道落地了同型防护，spec_review 车道独缺。结论：确定性缺口、有现成模式可复用，值得立项。
  - 建议：起草 SPEC：spec_review 对限流/连接类失败（429、ENOTFOUND、拒模型等瞬态签名，复用 classify_ratelimit_error 分类词表）不计入 3 次评审预算，改走带退避的短冷却重试；批量晋升评审时对并发派发做错峰；冻结标记区分「评审质量不达标」与「供给瞬态」两类前缀，避免「用户指令冻结」误导后续诊断。

- **admin run动作已执行但终态未落账即死，处置滞留pending**
  - 影响：复发敞口：admin run（告警处置会话）在「动作已执行、终态未落账」窗口死亡时，处置记录永久滞留 pending、告警滞留 partially-resolved，台账无法反映已处置事实，后续会话可能重做诊断或误判信号未处理；本轮 pending 处置已滞留 21 小时以上无消费。
  - 证据：run admin-global-1791056118（处置 429 冻结信号的全局 admin 会话）于 19:40:21Z 已执行三个被冻 spec 的解冻重派（channel=manual 人工裁决通道，note=重派评审（人工裁决），三 spec 现均已 pushed），但自身 19:44:56Z 死于 [claude-code:unrecognized_model]（共 36 轮）；其终态处置记录 827b4f2fe0c8 停在 result=partially-resolved、handled=False，摘要停留在「计划动作：……解冻重派评审，随后写最终处置记录」；占位记录 613d42266fdb（pending 处置，admin_run_id 指向已死 run）创建于 19:35:18Z，至今无任何后续日志。
  - 调查评估：在处置限流冻结信号时暴露，与已闭环的 2026-10-04#失误#1 互补但不同层——那题守「失败不得误记 resolved」（evo-fix-global-signal-choice-execution 已修，merge 2bca125c），本题是「成功来不及记账」：choice（处置动作）执行与终态落账非原子，run 进程死亡时无人代写。已核实：动作本身全部生效（STATE 三 spec 均 pushed），仅台账失真；AdminMonitor（告警与处置监控组件）有孤儿处置升级机制，但该记录滞留 21 小时仍 pending，升级未见闭环消费。与存量工作关系：evo-signal-preprobe-handled-writeback（已归档）管唤起前预探写回，evo-add-adjudication-alert-narrative（在飞）管告警叙事，均不覆盖孤儿处置收敛。结论：低频（需恰死在动作后落账前）但属台账可信度缺口，可小专项解决。
  - 建议：起草 SPEC：admin 收尾按 choice 粒度小步持久化（每执行一个动作即落一条处置事件）；AdminMonitor 收敛孤儿处置时核查「动作是否已实际生效」（如解冻已发生即补记 resolved 并注明补记），而非无限期滞留 pending。
