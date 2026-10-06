## 2026-10-02

### 知识真相源
- audit 疑点升级待人工（聚合）：10 条待人工仲裁（最长龄期 7 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

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

## 2026-10-06

### 浪费
- **04:31上游瞬态窗口第7夜复发，在跑批仍死1次但零蒸发**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：code-fix 夜间批 run code-fix-1791145182 启动 14 分钟后在窗口内死亡，161 轮 API 往返作废（未提交现场被 salvage 抢救继承、零重做），下一批推迟 1710 秒；这是连续第 7 夜同刻复发，整夜仅此 1 个失败 run，损失形态与第 6 夜持平。
  - 证据：run code-fix-1791145182 于 2026-10-04T20:33:41Z（本地 04:33:41）api_timeout 终局 Exit code 1，死因 ENOTFOUND（DNS/连接失败）；告警 1aa6c04cf536（code-fix 窗口冷却武装信号）记录 300 秒冷却生效，告警 04834fa8a000 记录下一批实际推迟 1710 秒，下一批 05:06 起恢复产出（git log 05:06-05:16 批量 fix 提交）；salvage 提交 e44a0858（「api-timeout-salvage: batch 2 run code-fix-1791145182」，本地 04:33）把未提交现场提交进批分支；告警 7a2c39d0ac78（daemon_errors 跨日同刻复发信号）记录「前次 2026-10-03T20:32:40Z，跨日差 24.02 小时（容差 ±5 分钟）」。
  - 调查评估：在 code-fix 夜间批推进时暴露，是 [2026-10-04#浪费#1]（第 5 夜）、[2026-10-05#浪费#1]（第 6 夜）的延续，同刻（04:31±2 分）第 7 次复发，根因仍是上游 provider 连接类瞬态（ENOTFOUND），非框架失误。已核实四点：(1) evo-add-codefix-conn-error-cooldown（code-fix 车道连接类失败短冷却，merge 5dcf0666）当晚武装成功并把下一批推迟 1710 秒避开窗口；(2) evo-code-fix-api-timeout-salvage（api_timeout 终局的未提交现场抢救）连续第 2 夜把现场提交进批分支由下批继承，整链零蒸发；(3) [2026-10-05#浪费#1] 建议的跨日聚合观测已由 evo-fix-crossday-recurrence-fingerprint-normalization 落地（merge e36fb0bf，本地 02:13，含「小数+单位」归一化与跨日记忆持久化），落地当晚即以「跨日差 24.02 小时」命中同一指纹，上游窗口正式显性化为可追踪信号；(4) 窗口内另有 9 个离群 run 带 API 停滞样本（最长 519.3 秒、均成功收尾，evo-add-api-stall-observability 已提供观测），同属上游瞬态面。结论：外部窗口仓内不可修，损失已连续两夜稳定在「每晚烧一次在跑 run（约 14 分钟/161 轮）+下一批推迟半小时」，防线链按设计工作，不值得新立项；按第 6 夜口径继续容忍单次死亡开销，待窗口消失后复核冷却与 salvage 退场。
  - 建议：维持冷却+salvage+跨日观测现状；顺带做一次只读对账：用系统日志（syslog/dmesg）核实该日断窗根因在本机网络侧（如接口每日定时掉 carrier）还是上游出口侧——若是本机侧的固定时刻断网，可把夜间批起点错峰到窗口之后，省掉每晚一次的死亡-重启开销。

### 失误
- （当日无）

### 可改进
- **孤儿处置生效核查认不出已生效动作，429信号滞留46小时连环升级3组**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：复发敞口：每个 global 类孤儿处置组终态后都会被升级「需人工介入」且无法自动收口，本窗口实测 4 小时余内 3 组连环升级（本地 06:58 / 10:17 / 11:12，1 组未处理），其中 10-03 的 429 冻结事件事实上早已解决、3 条信号记录却 handled=False 滞留约 46 小时，台账持续失真并持续吸引 admin 会话与人工注意力。
  - 证据：升级记录 5f2a40faa658、33ded63224d7、c17b04c9280b（daemon_errors 孤儿处置升级告警，分别对应处置组 admin-global-1791056118 / admin-global-1791144077 / admin-global-1791154704）结论同为「生效核查：fenixd.log 对账窗口内无解冻族 Transition 留痕」；而 429 解冻的 4 条留痕（「Transition: … blocked → …」，channel=manual 人工裁决通道）实测存在于 2026-10-03T19:40:21Z、已随轮转落入 fenixd.log.1（当前日志仅覆盖 10-04T18:54Z 起，且全文件 0 条 blocked→ 留痕）；core/admin_monitor.py 的 _read_recent_unfreeze_transitions 只读当前 fenixd.log 尾部 256KB（_TAIL_ERROR_READ_BYTES）且只认 blocked→X 手动解冻一种证据形态（_ORPHAN_UNFREEZE_TRANSITION_RE）。
  - 调查评估：在孤儿处置收敛机制（evo-add-admin-orphan-disposition-effect-check，merge e3843198，本地 10-05 02:38）首轮实弹时暴露，是 [2026-10-05#可改进#2] 落地后的残余缺口。已核实：机制按设计 fail-closed（宁可滞留升级、不假闭环）正常工作，但其 global 组（spec=global/None，如 429 冻结这类无单一 spec 对象的告警）唯一证据源存在两个结构性盲区——(a) 日志轮转盲区：429 处置组（run admin-global-1791056118）的解冻动作发生在 10-03T19:40:21Z，留痕已轮转进 fenixd.log.1，核查只扫当前文件尾部 256KB（本机约数小时日志量），对滞留超 1 天的组必然 0 证据；(b) 动作类型盲区：admin-global-1791144077 的实际生效动作是提交 spec 目录归档删除收尾解除 merge-back 阻塞（resolved 处置记录 ef184ed4a4b1），admin-global-1791154704 的是 code-review-fix 分支合并（10-04T23:20:56Z），两者都不产生 blocked→X 解冻留痕，核查同样判「无生效证据」。根因：证据源设计未考虑日志轮转与处置动作多样性，落地效果是「无限期 pending」变成「无限期 escalated」，[2026-10-05#可改进#2] 的台账收口目标未达成；而 3 条 open 信号（10-03T19:31-19:41Z 创建的 daemon_errors 同源告警）会继续被后续 global 组匹配，形成结构性复发。结论：确定性缺口、修法明确（代码与盲区均已定位），值得一次小专项。
  - 建议：起草 SPEC：global 组生效核查证据源扩展——日志对账覆盖轮转文件（fenixd.log.N 按对账窗口检索）；证据家族按处置动作类型扩展（解冻→Transition 留痕、merge-back 放行→分支合并日志、归档收尾→commit 存在）；允许从处置组记录引用的 spec 名回退读 STATE 真实状态（frozen/status）作旁证。人工侧可先按已核实事实（4 个 spec 已于 10-03T19:40:21Z 经 manual 通道解冻且现已全部 pushed）登记补记，收口这 3 条滞留信号。

- **验证场景注册夹具显式传 fixture=false，绕过 ADR-163 噪音过滤假告警上主面板**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：复发敞口：任一验证场景手写 add_project(fixture=False) 注册夹具，其 seed/对照告警（severity 可为 critical）即进入人工告警横幅与跨项目聚合，每轮验证污染人工甄别面；实测 add-alert-self-heal-marking 验证轮（2026-10-06 16:53）夹具 selfheal-scratch-verify 的 critical 对照锚点（SELFHEAL-PENDING-CTL-MARKER）上主面板，用户误判为真实告警并发起排查。
  - 证据：场景代码 .fenix/verify-progress/add-alert-self-heal-marking/test_scenarios.json 场景命令内显式 `reg.add_project(SROOT, name='selfheal-scratch-verify', fixture=False)`；ADR-163（spec/knowledge/adr/ADR-163-fixture-registry-flag-narrow-aggregation-filter.md）明定「噪音过滤收窄在缺省跨项目聚合分支，显式点名查询（?project=）零改动，验证场景依赖不回归」——fixture=True 对场景断言零影响，作者系误判（过度保守）；dashboard.yaml 该条目原值 fixture: false，2026-10-06 已人工改 true 止血（改后聚合面即清零，点名查询照常）。
  - 调查评估：在 add-alert-self-heal-marking 验证场景直写 admin_alerts.json 造对照锚点时暴露。已核实：机制本身无缺口（ADR-163 窄口径设计按工作），缺口是场景未走夹具供给脚本、未按 ADR-163 打标——直写 admin_alerts.json 不经四点信号摄取抑制，唯一降噪面就是聚合分支的 fixture 标记，传 False 等于主动关掉它。属规范遵循缺口而非代码缺陷，修法集中在场景模板与可选机械守卫，值得一次小专项。
  - 建议：起草小 SPEC：①验证场景模板/文档固化「场景注册夹具 MUST fixture=True（ADR-163：点名查询零改动）」；②机械守卫二选一——Registry.add_project 对 /tmp 扫描根外临时路径项目缺省强制 fixture=True（显式 override 才放行），或聚合/摄取层对 /tmp 路径项目按夹具兜底处理；③夹具复位脚本补写标记的既有机制（ADR-163 Consequences）确认覆盖此形态。


## 2026-10-07

### 浪费
- **04:30断网窗三杀（恶化）：静默窗守卫已合入但当晚未生效**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：本地凌晨 04:30 断网窗同时击杀三个在跑 run——code-fix 夜间批（夜间批量修复 code-review 台账的车道）第 3 批 443 turns/211 轮 API 往返、fenixd 自进化分析重试 239 turns、一条告警处置 admin 会话派出约 2 分钟即死——是追踪以来首次三车道同窗三杀，另有凌晨 02:16 一场 5 失败/600 秒风暴触发全局派发冻结 599 秒；整链仍零蒸发，code-fix 6 批最终交付 resolved=81 条台账修复，下一批仅推迟 673 秒。
  - 证据：内核日志实锤本机侧断窗：10-06 04:30:01 有线网卡 enp42s0 与无线 wlo1 同时 Lost carrier（链路中断），04:31:20 复降、04:31:22 恢复 1Gbps，与 code-fix-1791231027 死亡（fenixd.log 行 3161，20:31:22Z，api_timeout 即单轮 API 请求超时类终局，死因 ENOTFOUND 域名解析失败）秒级吻合，且同型 Link is Down 在 10-04/10-05 的 04:30:02 连日在场；告警 8f4e0ec5dade（code-fix 窗口冷却武装信号）记死因与 300 秒冷却，1eebbd93f8d7（冷却解除信号）记实际推迟 673 秒，链 rollup（整链收尾汇总）runs=6 resolved=81；告警 4c34b517a247（transient_break_storm 全局瞬断风暴信号）记 02:16 冻结 599 秒；工作区干净故按设计跳过 salvage（未提交现场抢救，fenixd.log 行 3162）。
  - 调查评估：在 code-fix 夜间批与 evo 管线并行推进时暴露，是 [2026-10-06#浪费#1] 的延续、同刻第 8 个追踪夜命中（框架处置记录 faebe707a254 于 10-05 早晨已定根因为「本地 04:30 网络断供窗口、当时已连续 8 天」，本夜为该口径第 9 天）。已核实三点：(1) 根因在本机网络侧而非上游 provider——syslog 显示双接口同时掉 carrier 约 81 秒，指向局域网上游设备（路由器/交换机）每日定时动作，昨日条目要求的 syslog 对账已完成；(2) 守卫时序脱节：evo-codefix-night-quiet-window（夜间静默窗投递守卫，缺省 04:15-04:45 窗内顺延投递）已于当晚 02:42 合入（merge 00b54c5e），但 daemon 跑旧代码至 18:29 才重启，当晚全程未生效——冷却解除后下一批 04:42 派出，若守卫在场属窗内派出本应顺延到 04:45 后；(3) 即便守卫在场也救不了本夜主形态：第 3 批 03:50 派出、04:31 在飞被杀，属「窗前派出、窗中在飞」，不在「派发时刻是否落窗内」的判定覆盖内。与存量工作关系：冷却（evo-add-codefix-conn-error-cooldown）与 api_timeout 现场抢救（evo-code-fix-api-timeout-salvage，本夜无未提交现场可抢）均按设计工作；admin 会话派发（daemon_errors 即日志错误聚合信号召唤）无断窗避让，往窗口里派即烧，且死后其处置组于 06:39 被 fail-closed 升级人工（告警 6cea21da2e0b）至今滞留。结论：外部窗口仓内不可修，防线链保持零蒸发，但损失从「每晚 1 run」扩为「3 run + 1 组孤儿升级滞留」。
  - 建议：维持冷却+salvage+跨日观测现状，等 10-07 夜静默窗守卫首个实战窗验证；对「窗前派出窗中在飞」盲区二选一立项：守卫升级为「预计跨窗」判定（派出时刻+同链近批均时长与 04:15-04:45 相交即顺延），或把夜间批起点错峰到断窗之后；给 admin 会话派发加瞬态冻结/断窗期避让；人工侧建议排查局域网设备每日 04:30 定时任务（双接口同掉指向上游设备而非本机网卡）。

- **自进化产物小节枚举校验整轮拒绝，396轮无修复回路**
  - 自进化：问题部分成立 / 建议部分合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：fenixd 项目的自进化分析 run evo-1791224502 跑满 396 turns 后，仅因输出第 6 条目的小节名 '流程' 不在枚举内被整轮拒绝作废，合法条目一并丢弃（按窗口内 impl/planner 车道中位单轮成本约 0.06-0.07 美元/turn 折算约 25 美元量级）；接力重试又死于断网窗，当日增量材料的自进化加工最终缺席。
  - 证据：fenixd.log 2026-10-05T19:59:34Z ERROR「自进化分析 run evo-1791224502 失败（水位不推进）: items[5].section 不在三值枚举内: '流程'」（水位不推进即自进化进度标记未前移、整轮不计入）；core/evolution.py:41 合法小节枚举 TODO_SECTIONS 仅（浪费/失误/可改进），:2206 产物校验对越界小节抛 ContractError 拒绝整份产物；.fenix/evolution/items.jsonl 中该 run 回收条目为 0 条，.fenix/evolution/state.json 的 fenixd 水位停在 evo-1791221198（01:26 完成的基线分析）；该 run 途中另有 13 次 API 停滞（最长 237.7 秒）。
  - 调查评估：在凌晨 evo 管线对当日新材料做二轮分析时暴露（02:21 启动，触发器未核实）。已核实：输入侧读 todo.md 时对未知小节是「跳过+WARNING」的宽口径（evolution.py:535-580），输出侧产物校验却是整轮 fail-closed——模型从 todo.md 的自由小节名（如「知识真相源」）泛化出 '流程' 即触雷；校验失败后无「带错误回问修复」回路，已归档的产物部分回收机制（evo-add-evolution-product-salvage）只覆盖流式截断的 .parts 形态、不覆盖「产物已写出但校验拒绝」形态，故合法 items[0-4] 一同陪葬，0513 接力又死窗后当日未再重试。与存量工作关系：无在飞 SPEC 覆盖此形态。结论：校验拒绝本身正确（不放坏数据入库），但「整批陪葬」是确定性缺口、修法明确，枚举幻觉概率性触发决定其必然复发。
  - 建议：起草小 SPEC：产物校验失败先走 1 次有界修复回问（把 ContractError 文本回喂令模型自改小节名，仍败再弃），或降级为「跳过非法条目、登记合法条目」的部分回收并与输入侧宽口径对齐；提示词同步补三值枚举的显式示例。

- **评审车道0轮秒败5连熔断30分钟，根因无stderr留痕**
  - 自进化：问题部分成立 / 建议部分合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：评审车道（spec-review，SPEC 评审 run）在本地 05:20-05:50 连续 5 次 0 轮秒败（CLI 启动即退 exit 1、无任何 API 往返），触发链路熔断停摆 30 分钟，evo-add-acceptance-deviation-reporting 的评审顺延约 1 小时；单次成本近零，但该致命形态是 10-03 风暴后二度出现，且失败 stderr 未留痕、根因不可归因。
  - 证据：告警 4b7b59085184（run_infra_failure 基础设施失败熔断信号，21:50:52Z）记「连续 infra 失败 5 次（阈值 3）已熔断、冷却 30 分钟」，样本错误为「claude CLI failed: Exit code: 1 | 0 rounds（无 API 往返样本）」；告警 dc23d55d482b（熔断冷却到期自动恢复信号）记 22:39:16Z 自恢复，其后评审链路正常交付（该 spec 当日 07:16 前后完成实现与验证入库）；内核日志在该时段无任何断网记录（排除本机网络侧）；10-03 同型风暴的人工收口记录（f63d10d2135b）已把该形态记为「spec_review 评审 run 集中秒败 Exit 1 0-rounds」。
  - 调查评估：在 evo-add-acceptance-deviation-reporting 评审推进时暴露。已核实：熔断与自动恢复按设计工作（阈值 3 触发、30 分钟冷却、到期自恢复）；根因未核实——本时段无网络断窗佐证，候选为 10-03 同型的网关拒模型致命形态（0-rounds+exit 1），但评审车道级 ERROR 行不带 stderr_tail（code-fix 车道同类错误会附 stderr 尾巴），归因须逐个翻原始 run 文件；且错误消息内嵌 SPEC 名导致指纹互不相同，daemon_errors 的同指纹聚合观测对该形态失效（10-03 靠三指纹合并召唤、本夜一条未召唤）。与存量工作关系：无在飞 SPEC 覆盖「评审车道秒败的 stderr 留痕与跨日聚合」。结论：损失小但二度复发且不可归因，属观测缺口而非机制缺口。
  - 建议：给 spec-review 等评审类车道的秒败补 stderr_tail 留痕（对齐 code-fix 车道形态）；把 0-rounds+exit 1 形态纳入 daemon_errors 聚合观测的指纹归一化（剥离错误消息中的 SPEC 名），使该形态可跨日追踪，与既有跨日同刻复发观测共用记忆。

### 失误
- （当日无）

### 可改进
- **散件WIP信号无注册处置选项，每复发重烧一个admin会话**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：复发敞口：主树散件 WIP 滞留信号（maintree_stray_wip_stale，主树 tracked 未提交改动超宽限无人认领）每次都烧一个 admin 会话从头裁决同一动作（核对归属→提交或 stash），本次实测约 11 分钟（run admin-fenixd-1791281576，10-06 18:12-18:24）；该信号型 10-02 以来已四度出现。
  - 证据：处置记录 4a1464085660 的 suggested_choice 字段原话「注册表（桶 2 八类）未覆盖 maintree_stray_wip_stale，建议新增：id=commit_stray_wip」；本次处置产出提交 f70426c4（.gitignore 补 .pytest_cache/ 忽略并去重）与 17da1761（摘除误入库的 gh device-id）；同型信号 10-02T23:19、10-03T17:09、10-03T18:46 各一条（f1ee2c37f892/20d405cf724d/1dc9c20961e2，均已 handled 即各烧过一次处置）。
  - 调查评估：在主树 .gitignore 散件改动滞留 30 分钟触发升级时暴露（改动来源不明，在飞实现车道分支 diff 零命中，疑交互会话遗留，未核实）。已核实：裁决选项注册表（adjudication choices，告警处置会话使用的标准动作桶）八个标准选项不含「直接提交散件 WIP」这一动作，admin 只能自由裁决——裁决本身正确高效（11 分钟收口、两个提交入库），缺口仅在每次重做同型诊断。与存量工作关系：信号的盘点来源（evo-add-maintree-stray-wip-sweep）与交互会话归因（evo-add-maintree-interactive-session-attribution）均已落地，但都不覆盖「注册处置选项」这一步。结论：确定性小缺口，登记一次选项即可把复发代价从「一个 admin 会话」降到近零。
  - 建议：起草小 SPEC：给裁决选项注册表新增 commit_stray_wip（核对归属后直接提交散件 WIP 并在处置记录附提交 hash），并让 maintree_stray_wip_stale 的 recommended_action（建议动作字段）直接带出该选项。

- **blocked_stuck信号主体已终态仍升级滞留3.5天**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：复发敞口：spec 级滞留信号不随主体终态收口——upgrade-narrative-to-investigation 的 blocked_stuck 信号（spec 卡 blocked 超阈值未处理的升级告警）在主体已转 pushed 后仍保持 escalated（已升级人工）/handled=False 状态挂 3.5 天，台账持续虚报一条需人工介入的升级，且会继续被后续同型匹配放大。
  - 证据：信号 a90ebc0e80a8（blocked_stuck，2026-10-03T17:26:21Z 创建，escalated=True、handled=False 至今）；STATE.md 中该 spec 已于 10-03T17:48 记 status: pushed（updated 字段在案）；刚落地的自愈机制 add-alert-self-heal-marking（merge 92d49f61，10-06 16:48）其 SELF_HEAL_SIGNAL_TYPES 注册表仅含 daemon_errors/run_infra_failure/self-evolution 三类，不含 blocked_stuck。
  - 调查评估：在 upgrade-narrative-to-investigation 评审受阻时触发信号、22 分钟后 spec 自行恢复 pushed，但信号生命周期无人消费。已核实：新落地的告警自愈闭环按设计只覆盖基础设施瞬态类信号，其判定锚是「签名安静」而非「主体对象已达终态」，对 blocked_stuck 这种主体已恢复的滞留信号不适用；既有信号卫生机制（tests/test_stuck_signal_hygiene.py 覆盖面）也未含主体终态收口。与存量工作关系：add-alert-self-heal-marking 形态最近邻且刚落地，扩展点现成。结论：台账可信度小缺口，修法集中单点（终态惰性收口通道）。
  - 建议：起草小 SPEC：AdminMonitor（告警与处置监控组件）周期盘点时对「主体 spec 已 pushed/archived 的 open 信号」补惰性收口（标记 handled 并注明主体终态时刻），或把 blocked_stuck 纳入自愈注册表、以主体终态为收口锚。
