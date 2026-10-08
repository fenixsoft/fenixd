## 2026-10-02

### 知识真相源
- audit 疑点升级待人工（聚合）：10 条待人工仲裁（最长龄期 9 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

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

### 失误
- （当日无）

## 2026-10-07

### 失误
- （当日无）

## 2026-10-08

### 浪费
- **code-fix 回归失败6批重试耗尽现场即弃，烧掉当日车道35%成本**
  - 自进化：问题部分成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：当日 code-fix 车道（夜间批量修复 code-review 台账的车道）有 6 个批因修复引入回归、定向重试 3 轮耗尽仍失败被现场即弃，其中有成本记录的 3 个 run 合计 15.12 美元（单 run 4.06-6.53 美元，为车道中位 1.10 美元的 4-6 倍，单 run input tokens 最高 1269k），占当日车道总成本 43.67 美元的 35% 以上；其中两批达自动重试上限后跳过 13 条台账条目，这些条目延后约 12 小时才由最后一批兜底收尾。
  - 证据：日志 ERROR 聚合 6 条「定向重试 3 轮耗尽仍失败，现场即弃」（10-06T22:28Z 至 10-07T07:16Z，worktree 为 impl-code-review-fix-1791323559/1791326011/1791329611/1791340596/1791349413/1791353013）；告警 a99a3b5b21cb 与 7f71a053bf1b（code_fix_retry_budget_exhausted，失败批自动重试达上限停派待人工信号）分别登记 branch fenix/code-review-fix-1791329611 与 1791353013；窗口内 code_fix_regression_failed（批修复回归失败）信号 6 条；成本出自 .fenix/cost/code_fix_tokens.json（code-fix-1791340599 为 4.53 美元、1791349416 为 4.06 美元、1791353016 为 6.53 美元）。
  - 调查评估：在 code-fix 夜间链全天推进时暴露。已核实：6 批全部以「3 轮重试 0 收敛」收场，窗口内无一次回归失败重试成功的案例；失败现场按 add-code-fix-batch-failure-selfheal（失败批登记待人工+跳过条目+解除跳过通道）机制登记，机制按设计工作。台账对账：13 个被跳过条目（按 item_id 前缀核对 items.jsonl）已于 2026-10-07T11:41:32Z 全部终态（7 resolved + 6 ignored），与最后一批 merge 82e2c5b6 同刻——「待人工排查」实际被链的后续进展自然消化。根因分层：直接根因是模型修复质量（修 A 破 B 的回归）；系统性缺口在重试策略——fix-reg-failures-regression-*.json 记录显示回归失败清单 items 为空时 fallback_full=true（无法定位失败面、按全量重试），重试轮在不知道失败测试是哪些的情况下整批重跑，单 run turns 158-507（车道中位 42 的 4-12 倍）仍 0 收敛。与存量工作关系：add-codefix-parse-error-breaker（本窗口落地）熔断的是解析异常形态，add-regression-issues-rerun（10-07 归档）覆盖回归问题重跑，均不覆盖「回归失败重试无失败面定位」。结论：重试机制对回归失败形态无证据价值（当日 0/18 收敛），属可立项的策略缺口而非机制缺陷。
  - 建议：起草小 SPEC：code-fix 回归失败的定向重试改为失败面预检——重试前先重跑回归拿到具体失败测试清单（替换 fallback_full 全量重试），把失败测试与被修条目关联后定向修；同时统计该形态重试的历史成功率，若持续近零则把回归失败重试降为 1 轮即弃。

- **评审车道0轮秒败一夜两轮熔断，昨日仅记一轮（恶化）**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：spec-review 链路（SPEC 评审车道）在 10-07 凌晨实际发生两轮 0 轮秒败熔断（CLI 启动即退、无任何 API 往返，各冷却停摆 30 分钟）：本地 03:04 六连败与 05:50 五连败，evo-code-review-vendored-scope 的评审推进两度中断——昨日条目只记了 05:50 一轮，漏计 03:04 一轮；两轮均自恢复，该 spec 评审与验证当日仍完成交付。
  - 证据：告警 dffdb062f8eb（run_infra_failure 升级，created 10-06T19:04:25Z 即本地 03:04）记「spec-review 链路连续 infra 失败 6 次（阈值 3）已熔断冷却 30 分钟」，样本错误「claude CLI failed: Exit code: 1 | 0 rounds（无 API 往返样本）」；昨日条目引用的告警 4b7b59085184 created 21:50:52Z 即本地 05:50，记同型 5 连败熔断；两条升级告警均已自动收口（dffdb062f8eb handled_at 10-07T04:30:53Z）；ERROR 样本 19:04:25Z「评审 run 执行失败: evo-code-review-vendored-scope」。
  - 调查评估：在 evo-code-review-vendored-scope 评审推进时暴露，是 [2026-10-07#浪费#3]（评审车道0轮秒败5连熔断30分钟）的同日补充：同形态一夜两轮，说明不是孤立抖动而是该车道当夜持续存在的致命形态。已核实：两轮熔断与到期自恢复均按设计工作；单次失败根因仍无 stderr 留痕（0 rounds 形态拿不到 stderr 尾巴），但修复已在窗口内落地——evo-add-review-failure-attribution（评审失败归因）与 evo-fix-spec-review-infra-attribution-bridge（评审基础设施失败归因桥）均已 pushed，正对「秒败不可归因」缺口。结论：修复已落地，本条仅为损失账单补全并纠正「一夜一轮」的认知，无需新动作。
  - 建议：无需新动作；下一窗口按已落地的归因增强复核该形态能否拿到 stderr 并归因到具体根因（如网关拒模型）。

- **瞬态风暴叠加致实现链4次折损，337事件工作量作废**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：evo-add-review-failure-attribution（评审失败归因）的实现链在 10-07 凌晨风暴（本地 02:16-02:22 全局瞬态熔断窗）中连续折损 4 个 attempt：首个 attempt 337 个事件的工作量作废、两次原地重试各 12 事件秒败被取代、第 4 次直接 Exit 1，第 5 个 attempt 才以 0.64 美元完成交付；昨日三杀条目未含此链损失。
  - 证据：runs 档案 .fenix/runs/archive/impl-evo-add-review-failure-attribution-1791309158- 系列：a1 终态 superseded（2026-10-06T18:20:50Z，337 事件）、a1-r1 superseded（18:21:26Z）、a1-r2 superseded（18:22:30Z，恰为全局熔断触发刻）、a1-r3 终态 error Exit code 1（即数据摘要失败样本）、a2-r1 end_turn 成功 total_cost_usd 0.64029；编排救回痕迹与之吻合（三条 in-place retry 即原地重试，30s/60s/120s 退避，provider 均为 bigmodel.cn）。
  - 调查评估：在 evo-add-review-failure-attribution 实现推进时暴露，是 [2026-10-07#浪费#1]（04:30断网窗三杀）同夜的第四个受害者——昨日记了 code-fix 批、evo 分析重试、admin 会话三杀，未记此链。已核实：4 次折损全部源于上游 bigmodel.cn 瞬态（transient error 触发原地重试 3 轮退避救回失败，18:22:30Z 全局瞬态熔断冻结新派发，r3 随后秒败 Exit 1），编排层（fix-provider-transient-backoff）按设计工作，非框架失误；风暴本身已由既有条目追踪。结论：外部瞬态面已知、防线按设计工作，本条仅补全当日损失账单，无需新立项。
  - 建议：无需新动作；该损失并入 04:30 断窗追踪条目的既有账单口径即可。

### 失误
- **昨日自省误判静默窗守卫未生效，告警留痕证明首窗已拦截**
  - 自进化：问题不成立 / 建议部分合理 / — 不需要
  - 影响：[2026-10-07#浪费#1] 断言夜间静默窗守卫「当晚全程未生效」，实际告警留痕显示守卫在 10-07 凌晨首个实战窗（04:15-04:45）已在场并拦截了窗内批投递；错误结论会误导后续追踪（下一个断窗夜会拿「守卫未经实战验证」的假前提做判断），好在未导致错误动作或错误立项。
  - 证据：告警 343479a29677（code_fix_night_quiet_window，静默窗投递闸信号，created 10-06T20:29:19Z 即本地 04:29:19）记「批投递进入每日夜间静默窗，窗内暂停启动新批，下一可投递时刻 04:45」；告警 1d4a92a937f6（created 21:08:00Z 即本地 05:08）记「静默窗结束，恢复同链下一批投递」；merge 00b54c5e（evo-codefix-night-quiet-window 合入）的 git 提交时间为 2026-10-06 02:42:20 +0800，而非 10-07 凌晨。
  - 调查评估：复核昨日条目推理链时发现时间线误读：条目把「冷却解除后下一批 04:42 派出」当成守卫缺席的证据（推理为「若守卫在场属窗内派出本应顺延到 04:45 后」），但静默窗告警证明 04:29 与 04:42 的投递实际都被闸住、05:08 才恢复——04:42 那次并未真实派出。误读根源有二：把 merge 时间 10-06 02:42 误置到「当晚（10-06 深夜）」语境，以及把冷却推迟秒数（告警 1eebbd93f8d7 记 673 秒）当成了实际投递时刻。已核实的自洽时间线：10-06 02:42 合入 → daemon 10-06 18:29（本地）重启装载新代码 → 10-07 04:29 首窗拦截窗内投递。昨日条目的另一半判断（「窗前派出、窗中在飞」不在投递闸覆盖内）仍然正确，且已由 evo-add-night-window-inflight-guard（在飞跨窗守卫，已 pushed）补上。结论：自省分析的时间戳核对失误，属自省产出的质量缺口；机制生效类判断必须先检索该机制的信号族告警留痕。
  - 建议：以本条更正 [2026-10-07#浪费#1] 中「当晚全程未生效」的结论（守卫首窗已实战生效、成功拦截窗内投递）；自省条目凡涉及「机制是否生效」判断，先完成该机制信号族的告警留痕对账再下结论。

- **dashboard误点停整链无确认防护，本次损失近零属链尾侥幸**
  - 自进化：问题部分成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：用户在 dashboard 误点「停整个修复链」，取消了 10-07 本地 20:24 启动的 code-fix-1791375870（链内仅剩 1 批的收尾批，刚完成 provider 标记即被取消，本次无工作量损失）；损失近零属侥幸——若误点撞上夜间在飞重批（参考 10-04 夜批 456 轮 API 往返量级），按取消路径不做 WIP checkpoint（未提交现场存档）的设计将整批作废。
  - 证据：告警 13377b6e2004（run_cancelled，run 取消信号，created 10-07T12:29:49Z 即本地 20:29）记「人工取消 run 'code-fix-1791375870'——reason='用户误点，停整个修复链', by=dashboard」，其 recommended_action 明示「取消路径不做 WIP checkpoint……attempt 的未提交工作将随 cleanup(success=False) 丢弃」；runs 档案 code-fix-1791375870.jsonl 仅 17 事件（首事件 provider_marker、末事件 cancelled）；该链台账已清零（items.jsonl 当前 0 条 open），取消未造成交付缺口。
  - 调查评估：用户在 dashboard 操作时误触链级取消。已核实损失近零的三要素：run 刚启动（17 事件）、chain_len=1（链只剩此批）、台账 0 open（无待修条目）。但暴露的系统性面是真的：dashboard 把「停单个 run」与「停整个修复链」放在可误点的距离内且链级无二次确认，而链级取消的代价模型最重（不做 WIP checkpoint、整链后续批全部不再投递）。与存量工作关系：fix-dashboard-resident-takeover、add-push-restart-dashboard-hook 等 dashboard 类 spec 均已落地但未覆盖取消操作的人机防护。结论：一次性用户失误叠加无防护设计，值得一个轻量 UI 守卫专项。
  - 建议：dashboard 链级取消加二次确认（弹窗列明链内剩余批数与在飞 run）；「停单个 run」与「停整个链」分列或加危险标识；链级取消路径考虑补 WIP checkpoint 以对齐 freeze/超时路径的现场保全。

## [code-fix] 失败批已达自动重试上限，待人工排查（add-code-fix-batch-failure-selfheal）


## 2026-10-09

### 浪费
- **回归遭自毒化测试拖累，同批8条目连烧10run 5.6小时**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：code-fix 车道（夜间批量修复 code-review 台账的车道）同一组 8 个条目在 10-08 白天连烧 10 个 run、合计 12.84 美元、占用车道 5.6 小时（10:06-15:40）零收敛，其中熔断前 7 轮定向重试全部空转；8 条目延后到晚间批（20:45-22:21）才由人工根治测试后修复收口。
  - 证据：告警 07a39cc42d5a、7d5491693dd9、164873bc01b8（code_fix_regression_failed 批修复回归失败信号，12:18/14:40/15:40）与 f5752da81f14、7e431ab4f5c7（code_fix_retry_budget_exhausted 重试达上限停派信号，15:40）指向 branch fenix/code-review-fix-1791424850、1791433426、1791442427，失败用例摘要均为「status=timeout/parse_error（无失败用例明细）」；成本出自 .fenix/cost/code_fix_tokens.json（10 个 run：2.80+0.62+0.74+0.80+2.40+0.65+0.92+0.61+2.64+0.66=12.84 美元）；根治提交 844a3312（10-08 16:35，fix: test_run_stop_loss 进程级全局 Popen 补丁异常安全复原）自述「2026-10-08 code-fix 回归自毒化死循环根治：两个判停用例把全局 subprocess.Popen 换成 sleep(60) fake，复原不在 try/finally，被 pytest-timeout 10s SIGALRM 打断时 fake 泄漏，其后 85+ 用例连坐超时、1800s 撞死（total=0 零明细）」；8 个条目（557b3726aad6 等）于 2026-10-08T13:13:11Z 全部 resolved（items.jsonl，resolution=code-fix-auto），与晚间合回 83d08c78、be5d2f1b 同刻。
  - 调查评估：在 code-fix 车道消化 10-08 凌晨例行扫描（code-review-1791396245）新增条目时暴露，是 [2026-10-08#浪费#1]（前窗 6 批回归失败现场即弃）的延续且当窗再度发生 3 批，故按恶化重述。已核实事实：(1) 可回收的回归失败明细文件（fix-reg-failures-regression-*.json，即批修复失败时留存的失败清单档）10-08 午间 8 份全部 items 为空、fallback_full 为 true——回归（合回前跑全量 pytest 套件的门禁）撞 1800 秒墙钟时 total=0，定向重试（失败批自动重试轮）在拿不到失败测试清单的情况下整批盲跑；每轮 impl 约 10 分钟加回归 30 分钟超时，与 10 个 run 的时间戳节奏逐一吻合。(2) 根因不在模型修复质量而在测试自毒化：test_run_stop_loss（09-28 f4d38f96 引入）泄漏全局 Popen fake，844a3312 于 16:35 根治，晚间批随即全过。(3) 防线按设计但触发偏晚：回归异常熔断（连续多次零失败面即停止自动重派的收口，add-codefix-parse-error-breaker 与 evo-add-codefix-anomaly-redispatch-budget，后者于当日 02:14 a26dbe88 合入）在第 3 批才收口（告警 7e431ab4f5c7 原文「零失败面整批重派无证据价值，已停止自动重派」），前两批各烧满 3 轮。(4) 残余：20:56 仍有一次零面明细（fix-reg-failures-regression-1791463749，items 空），该批最终在合回时限内收敛，说明 1800 秒全量回归墙钟处于余量边缘、零面形态还会零星出现。与存量工作关系：昨日条目建议的「失败面预检重跑」对本形态无效（重跑同样撞死，见 mistakes 条），实际落地的是 anomaly 预算=1 的熔断方向，方向正确；self-review 的 run 级统计把 3 个失败批记为 0 失败 run（失败只见于 ERROR 聚合与告警），对账时须以后者为准。结论：损失主因是一次性测试缺陷叠加重试策略对零面形态收敛过慢，熔断方向已落地，残余为调参问题。
  - 建议：零失败面（timeout/total=0）回归首记即按 anomaly 预算 1 收口（当轮 0-1 轮重试即停），不再等「连续 2 次」计数在第三批才熔断——本次 7 轮空转中 6 轮可省；回归 total=0 时在明细档留存末段慢测试进度（如最后完成的用例名/耗时 top）便于直接定位毒化源；复核 1800 秒墙钟在全量套件当前规模下的余量，必要时分片跑。

- **出题竞态双输：胜者run悬挂57分钟，串行重出已合并spec**
  - 自进化：问题部分成立 / 建议不合理 / — 不需要
  - 影响：evo-add-codefix-failure-registration-closeout（失败批登记核销机制 spec）的出题链出现双输竞态：已交付 plan 的 planner run 悬挂 57 分钟后被取消，串行重出花 3.08 美元、58 分钟给一个 15 分钟前就已合并的 spec 重出题，重出产物纯浪费。
  - 证据：告警 33f5ce86deb1（run_cancelled，run 取消信号，10-08 02:26）记「base_run_id=planner-plan-evo-add-codefix-failure-registration-closeout-1791396563; attempts=1; reason=并行出题等待超时，取消后转串行重出; by=parallel-plan-lane」；run 档案 planner-plan-…-1791396563-a1.jsonl（483KB，末事件 cancelled）与 planner-plan-…-1791397578-a1.jsonl（700KB，末事件 result success，total_cost_usd=3.077，mtime 02:44）；该 spec 合并于 07592e49（10-08 02:11:14），早于取消（02:26）与串行重出完成（02:44）；被取消 run 的产物实际已被消费——04:18 重启时清理的 impl worktree 即 impl-evo-add-codefix-failure-registration-closeout-1791396563。
  - 调查评估：在复核 evo-add-codefix-failure-registration-closeout 交付链时暴露（该 spec 是对 [2026-10-08#可改进#1] 的修复）。已核实时间线：planner-plan-1791396563 约 01:29 启动、其 plan-ready（出题产物就绪文件）被消费并派生 impl、spec 于 02:11 合并；该 planner run 本体未随交付退出，parallel-plan（并行出题：两条 planner 车道同题竞速）的等待计时器于 02:26 超时将其取消并转串行重出；串行重出 run（1791397578）01:46 启动、02:44 才以成功终态收场——对已合并 spec 重出题。损失为取消 run 约 57 分钟悬挂墙钟加串行重出 3.08 美元与 58 分钟，无产物损坏（权威方案未被覆盖，仲裁按既有竞态约定消化了僵尸方）。与存量工作关系：并行出题仲裁竞态有既有处置经验（plan-ready 已存在即僵尸方勿覆盖），但「串行重出前不查 spec 是否已 implemented/merged」与「planner 落盘产物后悬挂不退出」两个缺口均未覆盖；evo-add-run-cancel-wip-checkpoint（取消路径 WIP checkpoint，7dfc426e 当日 02:02 合并）不覆盖 planner 车道取消（该告警建议文案仍明示取消路径不做 checkpoint，本例无现场可保、损失在重复重出本身）。结论：低频但确定性的编排浪费，修法明确，值得并入出题链竞态专项而非单独立项。
  - 建议：parallel-plan 转串行重出前先查目标 spec 状态，已 implemented/pushed/合并即直接弃单；planner run 落盘 plan-ready 后应收口退出（或由并行车道在消费产物后主动收割），避免悬挂到等待超时才被取消。

### 失误
- **昨日自省把零面回归归因模型质量，10-07明细证实全系零失败面**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：复发敞口：[2026-10-08#浪费#1] 写下「直接根因是模型修复质量（修 A 破 B 的回归）」并建议「失败面预检重跑」，但可回收的 9 份 10-07 回归失败明细全部为 items 空、fallback_full 为 true 的零失败面形态，与今日证实的测试自毒化形态完全一致；若按昨日建议立项预检重跑，对 timeout 形态无效（重跑同样 1800 秒撞死），将烧掉一个 spec 预算却不解决问题。
  - 证据：fix-reg-failures-regression-1791347773/1791350169/1791350657/1791351045/1791351558/1791354250/1791355016/1791356185/1791357031.json（10-07T04:42Z-07:16Z 的 9 份回归失败明细档）全部 items=[]、fallback_full=true；根治提交 844a3312（10-08 16:35）自述该日回归死循环系 test_run_stop_loss 自毒化（全局 Popen fake 泄漏致 1800s 撞死 total=0），10-08 午间 8 份明细同形态；昨日条目自己已注明「回归失败清单 items 为空时 fallback_full=true（无法定位失败面）」，却在结论给出确定性归因。
  - 调查评估：在为本窗回归死循环条目做对账时发现。已核实：零失败面（回归 total=0 拿不到失败测试清单）形态在 10-07 与 10-08 两窗全部可回收明细中 17 份无一例外；10-08 的根因已由 844a3312 实锤为测试自毒化，10-07 同形态是否同根因未直接核实（毒化测试自 09-28 f4d38f96 在场，推断成立但不写死）。根因归属：自省分析在证据不足以区分「模型改坏代码」与「测试自身毒化」时给出了倾向性确定性归因——明细 items 为空恰恰说明当时不掌握任何失败面证据。与存量工作关系：幸运的是 evo lane 未走预检方向，实际落地的 evo-add-codefix-anomaly-redispatch-budget（零面形态预算 1 即熔断，a26dbe88 合并）方向与根因无关、天然正确，故本次错误归因未造成实际浪费。结论：自省条目在「无法定位失败面」事实在场时，结论必须退到「根因未定、两假说并存」，不得给出单因叙事；已按此口径更正本窗 waste 条目的表述。
  - 建议：自省条目凡结论涉及根因归因，必须逐项对照当日可回收证据（明细档/告警/日志），证据只覆盖形态时结论只写到形态层；对既有错误归因，在本条更正 [2026-10-08#浪费#1] 的「模型修复质量」结论（当日真实根因为测试自毒化，844a3312）。

### 可改进
- **失败批登记遭带外解除后成孤儿块，核销机制按记录驱动够不着**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：复发敞口：带外解除（人工按 todo 登记指引执行 release_failed_batch，即失败批跳过的人工解除接口）会整批删除 fix-failed.json（失败批注册表）记录，而核销机制 consume_resolved_failed_batches（被跳过条目全部终态即回写登记的对账器）按注册表记录驱动——记录已删，对应 todo.md 登记块永远无人核销；本窗实例：1791442427 批登记的 8 个条目已于 21:13 全部 resolved，登记块至 10-09 00:11 仍原样挂着「保持 open」，人工照其排查将白查一遍已终态条目（上次同类排查实测成本约为一个专项会话）。
  - 证据：留痕文件 .fenix/code-review/fix-failed-release.jsonl 唯一一行：released_at=2026-10-08T12:41:45Z、released_records=1、item_ids 全 8 条（带外 python3 -c 直调不经 daemon logger，fenixd.log 中 release_failed_batch 调用 0 行，与 closeout spec 1.3 的设计一致）；fix-failed.json 现仅存 3 条 9 月老记录（已于 08:48 核销），1791442427 记录已不在册；items.jsonl 中 557b3726aad6 等 8 条 resolved_at=2026-10-08T13:13:11Z；todo.md 登记块（记录时间 2026-10-08T07:40:32Z）无任何核销注记。
  - 调查评估：在验证 evo-add-codefix-failure-registration-closeout（失败批登记核销，07592e49 当日 02:11 合并）实战效果时发现。已核实：机制本身工作正常——08:48:18 首次实战即核销 3 条遗留登记（日志「code-fix 失败登记核销：3 条登记的被跳过条目已全部终态，已收口对应告警与 todo 登记」，注册表三条记录 consumed_at=2026-10-08T00:48:17Z）；缺口在新登记的 Consuming 前置条件被带外解除截断：release 路径删记录、核销路径按记录找 todo 块，两路径对「已解除但未核销」的登记块无交接。根因归属：closeout spec 的设计盲区（release 与 consume 两条生命周期终点未对齐），非执行失误。与存量工作关系：add-code-fix-batch-failure-selfheal（登记/跳过/解除三件套）与 closeout（核销回路）合起来仍缺「解除即同步核销登记块」一环。结论：确定性小缺口，修法明确，值得一次小专项或并入 closeout 的后续修订。
  - 建议：release_failed_batch 在删除注册表记录的同一锁内同步核销/注记 todo.md 对应登记块（注明解除时刻与留痕文件行）；或改为解除时打 consumed 标记而非删除记录，让既有核销对账自然收口；并在 fix-failed-release.jsonl 留痕行补充 todo 块处理结果字段。

- **主树散件归因同指纹每分钟重复打info，占当前日志37%**
  - 自进化：问题成立 / 建议合理 / — 不需要
  - 影响：观测噪音：主树散件 WIP（主树流水线外 tracked 未提交改动）被归因到活交互会话后，周期盘点每分钟重复打印同一条 info 留痕，本窗约 1200 行；当前 fenixd.log 共 13227 行中 4899 行（37%）为同一文案，自 10-05 02:54 起每小时约 60 行连续不断，抬高日志检索与轮转成本，且盖淡其他组件信号。
  - 证据：fenixd.log 按小时聚合：10-08 全天每小时 43-60 行（如 05-23 时均约 60 行/时），窗口内（10-08 00:26 起）合计约 1200 行，文案恒为「主树散件 WIP 归因到主树活交互会话，降级 info 留痕（不派 major 不触发 admin 代查）: spec/knowledge/adr/index.md, spec/knowledge/domains/worktree-vc/_domain.md, …」——文件清单与 git status 未提交集合全程未变。
  - 调查评估：在核对本窗 admin 告警（maintree_stray_wip_stale，主树散件 WIP 滞留信号，告警 27e2826cff8c 于 00:56 major 升级、其 commit_stray_wip 一键提交选项 01:05 正确拒绝空提交）的处置链时发现。已核实：归因机制本身工作正确且刚完成升级——evo-add-maintree-interactive-session-attribution（主树散件归因到活交互会话，04:18 stale_code 陈旧代码自愈重启后装载）把本会误升级的散件降级为 info 留痕，设计要点已由本窗沉淀的 ADR-258（主树散件盘点为只读观察者车道，占用归因单源复用 identify_wip_occupant）固化；噪音纯粹是「指纹未变仍逐次打印」的留痕策略问题（分钟级巡检 cadence 本身符合 maintree-stray-wip-sweep 知识的分钟级检出设计）。根因归属：机制缺去重，非新缺陷。与存量工作关系：信号侧已有「同指纹一次性告警」惯例，日志侧无对应惯例。结论：低风险体验型缺口，一行去重守卫可解，不值得独立立项，可搭车其他 admin/观察者车道改动顺带修。
  - 建议：盘点留痕按指纹去重：指纹未变只在首见与变化（清单增减/归因变更）时打印，恢复打印时附持续时长；或降为每 N 分钟心跳一次汇总。
