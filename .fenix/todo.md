## 2026-10-02

### 知识真相源
- audit 疑点升级待人工（聚合）：10 条待人工仲裁（最长龄期 6 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

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
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：上游 provider 瞬态窗口连续第 6 夜在本地 04:31 前后击杀在跑 code-fix 批（夜间批量修复 code-review 台账的车道），但本次零工作蒸发：整夜只死 1 个 run（此前每晚双 run 蒸发），另致 2 次全局派发冻结（Global transient break，全局瞬态熔断，各 600 秒合计 20 分钟）与全窗口 25 次 in-place retry（原地重试）；整条 code-fix 链最终交付 resolved=127 条台账修复。
  - 证据：run code-fix-1791058640（当夜在跑批）于 2026-10-03T20:32:40Z（本地 04:32）api_timeout 终局（单轮 API 请求超时/错误类终局签名）：142 轮 API 往返、255 turns、144 次工具调用，stderr 为 [claude-code:unrecognized_model]（网关拒模型行），死因为 API Error: Can't reach the API server（ENOTFOUND，DNS/连接失败）；4 秒后告警 93e461c553da（code_fix_switch_window_deferred 冷却武装信号）记录 300 秒冷却生效，告警 76d67a9b9df4（冷却解除信号）记录同链下一批实际推迟 977 秒；fenixd.log 行 44338 记「未提交现场已 salvage 提交到批分支……下批认领继承」（salvage 即未提交现场抢救提交）；23:33:15Z 链 rollup（整链收尾汇总）runs=10 resolved=127 ignored=1；两次全局熔断触发于 19:40:30Z 与 20:25:18Z，25 次原地重试 provider 均为 bigmodel.cn。
  - 调查评估：在 code-fix 夜间批与 evo 管线并行推进时暴露，是 2026-10-04#浪费#1（第 5 夜风暴）的延续：失败同刻（04:31±1 分）复发、根因仍是上游 bigmodel.cn 瞬态（今晚为连接类 ENOTFOUND 与拒模型 stderr 同现），非框架失误。已核实两条既有防线今晚首次同台实弹生效——evo-add-codefix-conn-error-cooldown（code-fix 连接类失败短冷却，merge 5dcf0666）武装并把下一批推迟 977 秒避开窗口，「每晚双 run 死亡」形态消失；evo-code-fix-api-timeout-salvage（api_timeout 终局的现场抢救）把 142 轮未提交现场提交进批分支由下批继承，整链无重做。结论：外部窗口仓内不可修，损失已收敛到「在跑 run 死亡一次、零蒸发」，不值得新立项；残余为每日仍烧一次在跑 run 的死亡-重启开销，以及 10-03 条建议的「同一 stderr 签名 + 同刻连发 ≥2 天」跨日聚合观测仍未落地。
  - 建议：落实跨日聚合只读观测（同一 stderr 签名 + 同刻连发 ≥2 天即聚合告警），把上游窗口显性化为可追踪信号；在跑 run 的单次死亡开销暂容忍，待窗口消失后复核冷却与 salvage 是否可退场。

### 失误
- （当日无）

### 可改进
- **admin run动作已执行但终态未落账即死，处置滞留pending**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：复发敞口：admin run（告警处置会话）在「动作已执行、终态未落账」窗口死亡时，处置记录永久滞留 pending、告警滞留 partially-resolved，台账无法反映已处置事实，后续会话可能重做诊断或误判信号未处理；本轮 pending 处置已滞留 21 小时以上无消费。
  - 证据：run admin-global-1791056118（处置 429 冻结信号的全局 admin 会话）于 19:40:21Z 已执行三个被冻 spec 的解冻重派（channel=manual 人工裁决通道，note=重派评审（人工裁决），三 spec 现均已 pushed），但自身 19:44:56Z 死于 [claude-code:unrecognized_model]（共 36 轮）；其终态处置记录 827b4f2fe0c8 停在 result=partially-resolved、handled=False，摘要停留在「计划动作：……解冻重派评审，随后写最终处置记录」；占位记录 613d42266fdb（pending 处置，admin_run_id 指向已死 run）创建于 19:35:18Z，至今无任何后续日志。
  - 调查评估：在处置限流冻结信号时暴露，与已闭环的 2026-10-04#失误#1 互补但不同层——那题守「失败不得误记 resolved」（evo-fix-global-signal-choice-execution 已修，merge 2bca125c），本题是「成功来不及记账」：choice（处置动作）执行与终态落账非原子，run 进程死亡时无人代写。已核实：动作本身全部生效（STATE 三 spec 均 pushed），仅台账失真；AdminMonitor（告警与处置监控组件）有孤儿处置升级机制，但该记录滞留 21 小时仍 pending，升级未见闭环消费。与存量工作关系：evo-signal-preprobe-handled-writeback（已归档）管唤起前预探写回，evo-add-adjudication-alert-narrative（在飞）管告警叙事，均不覆盖孤儿处置收敛。结论：低频（需恰死在动作后落账前）但属台账可信度缺口，可小专项解决。
  - 建议：起草 SPEC：admin 收尾按 choice 粒度小步持久化（每执行一个动作即落一条处置事件）；AdminMonitor 收敛孤儿处置时核查「动作是否已实际生效」（如解冻已发生即补记 resolved 并注明补记），而非无限期滞留 pending。


## 2026-10-06

### 浪费
- **04:31上游瞬态窗口第7夜复发，在跑批仍死1次但零蒸发**
  - 影响：code-fix 夜间批 run code-fix-1791145182 启动 14 分钟后在窗口内死亡，161 轮 API 往返作废（未提交现场被 salvage 抢救继承、零重做），下一批推迟 1710 秒；这是连续第 7 夜同刻复发，整夜仅此 1 个失败 run，损失形态与第 6 夜持平。
  - 证据：run code-fix-1791145182 于 2026-10-04T20:33:41Z（本地 04:33:41）api_timeout 终局 Exit code 1，死因 ENOTFOUND（DNS/连接失败）；告警 1aa6c04cf536（code-fix 窗口冷却武装信号）记录 300 秒冷却生效，告警 04834fa8a000 记录下一批实际推迟 1710 秒，下一批 05:06 起恢复产出（git log 05:06-05:16 批量 fix 提交）；salvage 提交 e44a0858（「api-timeout-salvage: batch 2 run code-fix-1791145182」，本地 04:33）把未提交现场提交进批分支；告警 7a2c39d0ac78（daemon_errors 跨日同刻复发信号）记录「前次 2026-10-03T20:32:40Z，跨日差 24.02 小时（容差 ±5 分钟）」。
  - 调查评估：在 code-fix 夜间批推进时暴露，是 [2026-10-04#浪费#1]（第 5 夜）、[2026-10-05#浪费#1]（第 6 夜）的延续，同刻（04:31±2 分）第 7 次复发，根因仍是上游 provider 连接类瞬态（ENOTFOUND），非框架失误。已核实四点：(1) evo-add-codefix-conn-error-cooldown（code-fix 车道连接类失败短冷却，merge 5dcf0666）当晚武装成功并把下一批推迟 1710 秒避开窗口；(2) evo-code-fix-api-timeout-salvage（api_timeout 终局的未提交现场抢救）连续第 2 夜把现场提交进批分支由下批继承，整链零蒸发；(3) [2026-10-05#浪费#1] 建议的跨日聚合观测已由 evo-fix-crossday-recurrence-fingerprint-normalization 落地（merge e36fb0bf，本地 02:13，含「小数+单位」归一化与跨日记忆持久化），落地当晚即以「跨日差 24.02 小时」命中同一指纹，上游窗口正式显性化为可追踪信号；(4) 窗口内另有 9 个离群 run 带 API 停滞样本（最长 519.3 秒、均成功收尾，evo-add-api-stall-observability 已提供观测），同属上游瞬态面。结论：外部窗口仓内不可修，损失已连续两夜稳定在「每晚烧一次在跑 run（约 14 分钟/161 轮）+下一批推迟半小时」，防线链按设计工作，不值得新立项；按第 6 夜口径继续容忍单次死亡开销，待窗口消失后复核冷却与 salvage 退场。
  - 建议：维持冷却+salvage+跨日观测现状；顺带做一次只读对账：用系统日志（syslog/dmesg）核实该日断窗根因在本机网络侧（如接口每日定时掉 carrier）还是上游出口侧——若是本机侧的固定时刻断网，可把夜间批起点错峰到窗口之后，省掉每晚一次的死亡-重启开销。

### 失误
- （当日无）

### 可改进
- **孤儿处置生效核查认不出已生效动作，429信号滞留46小时连环升级3组**
  - 影响：复发敞口：每个 global 类孤儿处置组终态后都会被升级「需人工介入」且无法自动收口，本窗口实测 4 小时余内 3 组连环升级（本地 06:58 / 10:17 / 11:12，1 组未处理），其中 10-03 的 429 冻结事件事实上早已解决、3 条信号记录却 handled=False 滞留约 46 小时，台账持续失真并持续吸引 admin 会话与人工注意力。
  - 证据：升级记录 5f2a40faa658、33ded63224d7、c17b04c9280b（daemon_errors 孤儿处置升级告警，分别对应处置组 admin-global-1791056118 / admin-global-1791144077 / admin-global-1791154704）结论同为「生效核查：fenixd.log 对账窗口内无解冻族 Transition 留痕」；而 429 解冻的 4 条留痕（「Transition: … blocked → …」，channel=manual 人工裁决通道）实测存在于 2026-10-03T19:40:21Z、已随轮转落入 fenixd.log.1（当前日志仅覆盖 10-04T18:54Z 起，且全文件 0 条 blocked→ 留痕）；core/admin_monitor.py 的 _read_recent_unfreeze_transitions 只读当前 fenixd.log 尾部 256KB（_TAIL_ERROR_READ_BYTES）且只认 blocked→X 手动解冻一种证据形态（_ORPHAN_UNFREEZE_TRANSITION_RE）。
  - 调查评估：在孤儿处置收敛机制（evo-add-admin-orphan-disposition-effect-check，merge e3843198，本地 10-05 02:38）首轮实弹时暴露，是 [2026-10-05#可改进#2] 落地后的残余缺口。已核实：机制按设计 fail-closed（宁可滞留升级、不假闭环）正常工作，但其 global 组（spec=global/None，如 429 冻结这类无单一 spec 对象的告警）唯一证据源存在两个结构性盲区——(a) 日志轮转盲区：429 处置组（run admin-global-1791056118）的解冻动作发生在 10-03T19:40:21Z，留痕已轮转进 fenixd.log.1，核查只扫当前文件尾部 256KB（本机约数小时日志量），对滞留超 1 天的组必然 0 证据；(b) 动作类型盲区：admin-global-1791144077 的实际生效动作是提交 spec 目录归档删除收尾解除 merge-back 阻塞（resolved 处置记录 ef184ed4a4b1），admin-global-1791154704 的是 code-review-fix 分支合并（10-04T23:20:56Z），两者都不产生 blocked→X 解冻留痕，核查同样判「无生效证据」。根因：证据源设计未考虑日志轮转与处置动作多样性，落地效果是「无限期 pending」变成「无限期 escalated」，[2026-10-05#可改进#2] 的台账收口目标未达成；而 3 条 open 信号（10-03T19:31-19:41Z 创建的 daemon_errors 同源告警）会继续被后续 global 组匹配，形成结构性复发。结论：确定性缺口、修法明确（代码与盲区均已定位），值得一次小专项。
  - 建议：起草 SPEC：global 组生效核查证据源扩展——日志对账覆盖轮转文件（fenixd.log.N 按对账窗口检索）；证据家族按处置动作类型扩展（解冻→Transition 留痕、merge-back 放行→分支合并日志、归档收尾→commit 存在）；允许从处置组记录引用的 spec 名回退读 STATE 真实状态（frozen/status）作旁证。人工侧可先按已核实事实（4 个 spec 已于 10-03T19:40:21Z 经 manual 通道解冻且现已全部 pushed）登记补记，收口这 3 条滞留信号。

- **evo merge-back撞在飞归档编辑，熔断停机15分钟烧admin会话收尾**
  - 影响：复发敞口：任一 spec 归档/编辑未提交期间，其他 spec 的 merge-back（实现分支合回主树）必被 git 拒绝并烧完 60 秒×3 轮顺延后熔断停机、等人工，须 admin 会话收尾；本次实测阻塞 15 分钟（本地 03:41-03:56）、消耗 42+12 轮两个 admin run，并产生 3 条同指纹 ERROR 触发 daemon_errors 告警（同指纹错误聚合信号）。
  - 证据：worktree_manager（工作树与合并管理组件）于 2026-10-04T19:41:23Z / 19:42:23Z / 19:43:24Z 三次 merge 失败（error: Your local changes … would be overwritten by merge: spec/changes/fix-knowledge-backfill-reconstruction/ 共 6 个文件）；pm_engine 19:43:24Z 报「merge-back 顺延超限（spec 目录在飞编辑）——已停止自动重试，等待人工提交 spec 目录后重新放行」；告警 75b55ecf7a5e（mergeback_spec_dir_inflight_stuck 信号）记录 retry_count=3；admin run admin-evo-add-todo-marker-commit-on-write-1791143080（42 轮，03:44:40-04:01:17，区间覆盖提交时刻）落收尾提交 ae3fe764（03:55:39「提交 fix-knowledge-backfill-reconstruction 归档删除收尾」），merge-back 88a7b37 于 03:56 成功。
  - 调查评估：在 evo-add-todo-marker-commit-on-write 的 merge-back 与 fix-knowledge-backfill-reconstruction 的归档收尾并发时暴露。已核实：主树滞留的归档半程状态（knowledge distill 蒸馏入库已由 03b4abe5 于 03:50 提交、spec 目录删除却未提交）挡住了与己无关的 evo 分支合并——git merge 对工作区脏文件一律拒绝，pm_engine 顺延 3 轮即熔断等人工，全链无自愈手段；归档收尾为何中断（被杀/异常退出）未核实。与存量工作关系：code-fix 车道已有 evo-add-codefix-mergeback-conflict-salvage（真冲突整批救回，STATE pushed）但只覆盖内容冲突、不覆盖本形态（主树在飞编辑占位）；同型信号（mergeback_wip_overlap / mergeback_wip_defer_stuck / mergeback_spec_dir_inflight_stuck，均为主树脏文件挡 merge-back 家族）过去数周已多次发生（add-archive-state-migration、add-timelib-consolidation-layer、add-dashboard-paging-and-etag 等各有数条告警记录在案），属结构性并发协调缺口而非一次性失误。结论：单次代价一个 admin 会话（42+12 轮）加 15 分钟合回延迟，频次周级别，值得一次小专项把「必烧 admin 会话」降为自动放行。
  - 建议：起草 SPEC：merge-back 顺延熔断前先做只读自愈评估——在飞编辑若为「归档/蒸馏类半程收尾」（spec 目录删除已 staged 且蒸馏已入库），由框架代为补提交收尾后重放 merge-back；或把归档流程的「目录删除提交」与 distill 入库合并为单原子 commit，消除半程窗口。两者取其一即可覆盖本形态。
