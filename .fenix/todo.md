## 2026-10-13

### 知识真相源
- audit 疑点升级待人工（聚合）：10 条待人工仲裁（最长龄期 15 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

### dsh 真实全链验收执行请求（dsh-primary-acceptance-switch，人工队列）
- **执行记录（2026-10-14，用户在本会话发起）**：车道级真实验收 **PASS**（第 6 轮；证据 `.fenix/verify-evidence/dsh-primary-acceptance-switch/dsh-acceptance-real-dshacc-20261014090932-41544c.{json,md}`，四车道 implementer 93s/verifier 68s/judge 8s/claude 基线 55s 全绿）。**daemon 全生命周期验收亦完成**：夹具项目 `/root/dsh-e2e-proj`（agent.harness=dsh）注册 `add-e2e-hello-note`，daemon 自主走完 spec-review(dsh, 191s/\$0.587)→planner(dsh, 136 事件)→implementer(dsh, a1 补丁回收并发互踩秒死后 attempt 环自动重试)→a2 实现并 cmp 逐字节校验→verify→merge-back→**done**，全程 6.5 分钟，交付物在主树。试错修出三缺陷已提交：`agent.dsh_api` 线协议渲染（03c50328）、argv 裸 headless 占任务槽（stdin prompt 丢失）、验收脚本 dsh_api 穿参+在飞谓词。遗留 finding 处置（2026-10-14，主 daemon 重启后修复，回归 run7 PASS）：①②已修——agent.dsh_api 落地 + config 线协议守卫告警（Anthropic 形态 baseurl 未配 dsh_api 时 WARNING 一次，进程级去重）；patch 回收改按龄（DSH_PATCH_RETENTION_SECONDS=3600，单槽互踩消除，a1 类秒死不再依赖 attempt 兜底）。③已修——验收脚本 --provider 按 name 选网关 + 自检列出全部候选并提示首个可能失效。④成本页接 dsh-events usage 属增强未动（投影层 usage 已实测可用）。回归证据：dsh-acceptance-real-dshacc-20261014095026-350656（四车道全绿）。

## 2026-10-14

### 失误
- **AGENTS.md 交付物误用软链载体，交付物守卫判缺件打回一轮返工**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：add-fenix-dsh-bundle 实现 run 因交付物守卫（落地产物核验闸门）判 AGENTS.md missing 而被挡，追加 1 轮原地修复（两个 commit）与复验，该 run 成本 22.23 美元（implementer 车道中位 5.40 美元的 4.1 倍），spec 合回被推至 17:40 才完成。
  - 证据：日志 2026-10-13T07:54:41Z [pm_engine]「交付物守卫触发 'add-fenix-dsh-bundle'（缺件 AGENTS.md（missing））」run=impl-add-fenix-dsh-bundle-1791871868-a1；修复 commit 1a7e1bf2（16:10「AGENTS.md 软链(120000)改同内容实体文件(100644)」）+ 4bffac0b（16:15 sha256 全等复核）；run_metrics cost_usd=22.23115。
  - 调查评估：问题源：add-fenix-dsh-bundle 实现收尾时暴露。已核实：git 中软链是 mode 120000 的特殊对象而非实体 blob，守卫按实体文件核验故判 missing——守卫行为正确，失误在实现侧交付物载体选型（SPEC/tasks 未写明载体形态要求，实现者默认选了软链）。当轮已完成修复与逐字节复核，属当轮闭环的执行失误、无残留。与存量工作关系：spec 内一次返工，无需新 SPEC 治理单点；残余敞口是「交付物载体形态」在 SPEC 模板与实现车道提示词中均无约定，同类选型歧义可在其他 spec 复现。结论：低频失误，一句模板约定即可消除。
  - 建议：在 SPEC 模板交付物清单或实现车道提示词中补一句「交付物须实体文件（git mode 100644），禁止软链（120000）载体」，消除载体选型歧义。

### 可改进
- **daemon 旧代码悬空 8 小时触顶强制重启，空闲自愈被连轴 run 饿死**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：当日三批合回的框架修复（add-harness-adapter-layer 13:57、add-fenix-dsh-bundle 17:40、add-dsh-adapter-integration 21:33）延迟到 21:58:58 规划性重启才装载，悬空整 8 小时（28800 秒恰达 max_dangling_seconds 上限）；本次零实害（窗口内 0 失败 run），复发敞口是悬空期内全部车道按旧代码执行——在飞 SPEC 提案已记载 10-11 同根实害两起（收尾双提交 5 对、蒸馏产物滞留 21 小时）。
  - 证据：告警 7185ed947ac9（stale_code info 级首见，13:58 本地）→ 告警 b43d2021c459（stale_code_dangling_timeout 升级，21:58，原文「悬空 28800s > 时限 28800s」，动作 touch .fenix/restart_request）；进程核验：fenixd daemon 新进程 21:58:58 启动，升级后 57 秒内重启落地；归档告警显示同类升级历史上已 5 次（9-26～9-30），本次为第 6 次。
  - 调查评估：问题源：当日 42 个 run 连续执行、无 600 秒连续空闲窗（stale_code_selfheal.idle_confirm_seconds 缺省值），空闲确认型自愈全天饥饿，只能等 8 小时时限强转——机制链按设计工作（升级→restart_request→supervisor 秒级重启），但装载延迟未被缩短。已核实根因归属：非一次性失误，是「空闲确认」前提在高压日的结构性失效。与存量工作关系：在飞 spec evo-add-key-path-stale-code-preflight 正是此根因（提案引三周 70 次检测→装载配对中 12 次 ≥2 小时、最长 22.05 小时），本次是其问题陈述的新实例、且首次以满 8 小时时限触发的形态出现；升级告警滞留未处理（handled=False）由另一在飞 spec add-alert-self-heal-marking 的安静窗自愈闭环覆盖。结论：不重复立项，两在飞 SPEC 均应优先落地。
  - 建议：优先安排 evo-add-key-path-stale-code-preflight 验证合回，让关键路径（收尾提交/蒸馏派发/admin 处置）预检→restart_request 的分钟级装载通道投产；若短期无法落地，可评估下调 max_dangling_seconds（如 4 小时）缩小敞口，代价是更频繁的规划性重启排水。

- **run 停滞遥测缺事件类型注记，33 次停滞无法区分工具执行与 API 等待**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：4 个离群 run 合计 33 次停滞（stall，事件流相邻事件间隔超阈值）、最长单次 298.7 秒，因遥测只记间隔时长不记边界事件类型，审查无法裁决是长工具调用（全量回归等合法耗时）还是 provider 往返/重试浪费，结论只能停在形态层、根因未定。
  - 证据：数据摘要第六节深扫：impl-add-dsh-adapter-integration-1791884537-a1 stall=11 max_gap=262.6s；impl-add-fenix-dsh-bundle-1791871868-a1 stall=11 max_gap=298.7s；impl-add-harness-adapter-layer-1791863204-a1 stall=6 max_gap=199.7s；planner-judge-add-dsh-adapter-integration-1791894482-a1 stall=5 max_gap=288.0s（已核实其档案 244 事件、62 次 Bash 调用，20:28–21:03 本地为命令密集型评审，非空转）。
  - 调查评估：问题源：三个大型 spec 实现 run 与一个出题评审 run 的离群初筛暴露。已核实：全部停滞无中途 stderr、四个 run 均成功收尾；planner-judge 档案显示 Bash 密集型工作，推测大间隔多为长命令执行，但 impl 三个 run 无事件级证据可在两假说间裁决——按归因边界规则只写形态层、不预设根因。与存量工作关系：evo-add-run-metrics-lane-baseline 已建车道基线使离群可初筛，本缺口是停滞维度的遥测表达能力，属互补不重复。结论：小改动即可让每日自省从「形态层」升到「归因层」，避免每轮审查重复人工翻档案。
  - 建议：run 事件流落盘时为停滞区间标注边界事件类型（工具执行 vs API 往返），self-review 聚合按两类分列透出计数与最长间隔，使离群审查可直接区分合法长工具与等待浪费。


## 2026-10-15

### 浪费
- **dsh 补丁互踩秒挂风暴 11 分钟，验证链被误判打回一轮**
  - 影响：add-harness-brand-projection 的 dsh 车道在 12:39-12:51（本地）连续秒挂（进程启动数秒内即死）11 分 18 秒：10 条车道 run、20+ 次进程秒死、20 条 ERROR（计数峰值「连续 18 次秒挂」），出题/验证/管理员车道全部零 token 空转；基础设施失败被误消费成验证拒绝，白烧一轮 implementer 复核 run（468.9 秒、98 轮、约 9.8 万 token）只为确认「打回系误判」，spec 合回推迟约 1.5 小时（原 ~12:40 应验证，实际 14:00 才合回）。
  - 证据：日志 2026-10-14T04:39:13Z 起 32 处 [Errno 2] No such file or directory: '/tmp/fenix-dsh-model-*.yml'（dsh 子进程启动时读不到刚写出的模型三要素补丁文件），ERROR「连续 18 次秒挂（阈值 3）— 进入 300s 冷却」；04:40:00 状态机 testing→bug-found、04:40:01「原地打回第 1 轮」，佐证该轮无实修的 commit b5140f0b（12:58，仅 tasks.md 3 行改动）；风暴终结于 04:50:26「陈旧自愈触发…touch restart_request」重启，04:58 起 dsh 车道连续成功。
  - 调查评估：问题源：add-harness-brand-projection（harness=dsh）验证链并发派发时暴露。已核实：core/agent_runner/harness/dsh_adapter.py:676 注释自证根因——旧版「单槽 unlink 上一份补丁」设计在全局 adapter 单例+多车道并发派发下互踩刚写未读的补丁（10-14 上午夹具 daemon 已实证同症）；修复（DSH_PATCH_RETENTION_SECONDS 按龄回收）由 dbbde7e1 于 09:50 落盘，但主 daemon（10-13 21:58 启动）悬空持旧代码 3 小时，12:39 验证链多车道并发（planner×7 / verifier×1 / implementer×1 / administrator×1）触发互踩；12:50:32 重启装载新代码后同路径不再复发，根因为确定性、非环境性。另核实两个放大器：秒挂冷却只声明门控 implementer/fast-track/repair 三车道，冷却生效的 04:45-04:50 期间调度器仍新派 5 个 planner run（1791953098/3127/3256/3316/3376）继续秒死；verifier 3 试全灭后被 fail-closed 语义推入 bug-found（见可改进条目）。与存量工作关系：悬空窗口正是在飞 spec evo-add-key-path-stale-code-preflight（关键路径派发前预检旧代码）的问题陈述，本事件是其新实例且首次造成实害；今日 12:50 陈旧自愈（空闲确认型）成功触发重启，说明昨日可改进#1 指出的「空闲自愈被连轴 run 饿死」在空闲窗口出现时机制本身有效。结论：根因已闭环（修复+重启），残余敞口是悬空窗口与两个机制缺口。
  - 建议：优先落地 evo-add-key-path-stale-code-preflight，让关键路径派发前的旧代码预检→分钟级重启通道投产，消除「修复在盘、进程持旧」的兑现窗口；秒挂冷却到期自动恢复前可复核一次 daemon 代码指纹，修复未装载则不重派。

- **并行出题三跑两弃：47 万 token 场景产物压线被隔离**
  - 影响：add-harness-brand-projection 一个 spec 的验证场景出题（planner-plan）三跑仅一跑被采信：36 分钟、397,585+77,094 token 的已完成产物在完成线同秒被并行出题仲裁按「半成品」隔离弃用，另一跑 1373 秒、257 轮被取消后原样重派——出题环节约 90 分钟 planner 墙钟时间有效产出仅 1/3，其中约 47.5 万 token 与 23 分钟可判定为纯弃。
  - 证据：日志 04:39:07.616「并行出题产物已隔离（不被采信）…testing 等待并行出题超时，半成品隔离」、04:39:07.687「并行出题等待超时—已取消在飞 run 并隔离半成品，转串行重出」，与 run_metrics 里 planner-plan-add-harness-brand-projection-1791950590 的 success（duration 2158.874s、252 轮）同秒；04:39:10.128「并行出题标记已被消费侧接管（discarded），放弃 completed 登记」；后续 planner-plan-…-1791953455 terminal=cancelled（1373.42s、257 轮、0 token 入账），其取消时刻（05:13:49Z）恰为替代者 1791954828（success、1893.078s、391,474+93,892 token）的起跑时刻。
  - 调查评估：问题源：add-harness-brand-projection 验证链出题阶段（并行出题=双 planner 竞速生成验证场景、testing 阶段汇合采信其一）。已核实：join（汇合点）超时与 racer 完成同秒触发，完成的 252 轮产物按「半成品」隔离且完成登记被拒，随后串行重出（1791952747）又撞上秒挂风暴全灭，出题净空转；被取消的 1791953455 与替代者之间是「取消即串行重派」衔接，取消时机不与「兄弟产物被采信」对齐。根因按归因边界写到形态层：join 无「压线完成宽限」语义、racer 取消与采信事件不对齐，两点机制事实成立；是否叠加 dsh 车道出题本身过慢（本窗口 dsh 出题 15-36 分钟、200+ 轮 vs 组中位 25 秒）未在多假说间裁决，不出单因结论。与存量工作关系：并行出题仲裁已有运营侧教训（双 planner 竞速时僵尸方勿覆盖权威场景文件），但 join 宽限与取消对齐无在飞 spec 覆盖；秒挂风暴（另一条目）放大了本轮代价。结论：机制小改可消除大部分弃产物，值立项。
  - 建议：给并行出题 join 加完成宽限窗：超时触发时等待在飞 racer 完成或 N 秒宽限，压线完成即采信而非按半成品隔离；把另一 racer 的取消绑定到「采信事件」而非固定时钟——采信即取消、未采信不预取消。

### 失误
- （当日无）

### 可改进
- **秒挂冷却漏门控出题与验证车道，冷却期内仍空烧 5 个派发**
  - 影响：复发敞口：任何 CLI/进程启动类基础设施故障再现场景下，300 秒秒挂冷却只暂停 implementer/fast-track/repair 三车道，出题/验证/管理员派发不受门控——本次风暴冷却生效的 5 分钟内仍空烧 5 个 planner 派发（各约 25 秒、3 次进程秒死、0 token），并把连续秒挂计数推到 18；同类事件单次代价约 5-10 个无效派发轮次加相应日志告警噪声。
  - 证据：ERROR 文案自证门控面：「连续 N 次秒挂（阈值 3）— 进入 300s 冷却，期间 implementer/fast-track/repair 派发被跳过」；计数 04:45:15→04:50:01 连续爬升 3→18，期间 run_metrics 另有 5 个独立 planner 派发失败行（planner-plan-add-harness-brand-projection-1791953098/3127/3256/3316/3376，各 duration≈25s、0 token），直到 04:50:26 才见「秒挂冷却到期，恢复调度」；风暴期失败的 10 条车道 run 中 planner×7、verifier×1、administrator×1 均不在门控面内。
  - 调查评估：问题源：10-14 秒挂风暴（见浪费条目）暴露。已核实：冷却按三车道白名单门控，而本次故障主要烧的恰是白名单外的出题/验证车道，冷却语义对本次故障基本失效。根因：系统性缺口——熔断按车道白名单而非按故障面（同一 spec 的秒挂应全车道暂停）。与存量工作关系：秒挂冷却为既有机制（阈值 3、300s），无在飞 spec 调整其覆盖面；与已落地的 evo-verify-infra-retry-lane（只收口验证 prepare 短路路径的 infra-retry，见下条）互补不重复。结论：小改动、高确定性收益，值立项。
  - 建议：把秒挂冷却门控面从三车道白名单改为「同 spec 全车道暂停派发」（至少纳入 planner/verifier/administrator），冷却到期恢复时复诵一次故障指纹，未消失则冷却翻倍，避免到期即重进故障循环。

- **验证 agent 基础设施死亡被误消费成验证拒绝打回**
  - 影响：复发敞口：验证车道 agent 基础设施死亡（0 轮、0 token、秒挂/文件缺失类）会因 verdict（验证裁决）缺失被 fail-closed 推导直接判 bug-found 并原地打回——本次实害为多烧一轮 implementer 复核 run（468.9 秒、约 9.8 万 token）加一整轮验证周期；同类事件单次代价即一轮无效修复 run 加验证链重跑，按本轮实测约 15-20 分钟墙钟。
  - 证据：04:40:00 状态机「Transition: testing → bug-found」，error 原文「Verifier agent failed: All 3 attempts failed. Last error: [Errno 2] …fenix-dsh-model-….yml」，04:40:01「原地打回第 1 轮…重置为 implementing 并注入修复任务」；core/verify_report.py:326-333 终局推导为 fail-closed——verdict 缺失/未知取值一律判 bug-found；b5140f0b（12:58）结论「打回系验证链基础设施秒挂误判（无失败场景）」。
  - 调查评估：问题源：10-14 秒风暴中 verifier 车道 3 试全灭后的裁决消费环节。已核实：agent 层基础设施死亡产生不出任何 verdict，而 fail-closed 语义让缺失 verdict 与真实验证不通过共用同一出口（bug-found→打回）；已落地的 evo-verify-infra-retry-lane（10-06 pushed）其 proposal 明确只收口 prepare/fail-fast 短路路径、Out-of-Scope 不触后置分类，故本路径属其覆盖面外的残余缺口，非重复建设。根因：系统性缺口——runner 层失败形态（0 assistant 轮+启动期错误指纹）未在进入 verdict 推导前分流。与存量工作关系：与 evo-verify-infra-retry-lane 互补（它管验证环境预检失败，本条管验证 agent 本体死亡），可直接复用其 infra 台账限次语义；与 evo-add-review-failure-attribution（失败归因留痕）互补。结论：语义边界清晰，值立项。
  - 建议：runner 层失败（0 assistant 轮或启动期错误指纹如 ENOENT/即退 exit 1）不进 verdict 推导，改走 infra 台账限次重派（复用 evo-verify-infra-retry-lane 台账语义），超限置验证暂挂而非 bug-found，留 admin 通道处置。

- **dsh 车道延迟观测失明，停滞遥测对主车道结构性无效**
  - 影响：窗口内全部 dsh 车道大 run（15 个，含 252-274 轮的出题/实现 run）API 往返配对恒为 0，「延迟观测疑似失明」告警 15 次——停滞/慢往返遥测对 dsh 车道结构性失效，今日深扫 6 个 dsh run 的 stall=0 是「看不见」而非「没停滞」；dsh 已成新 spec 默认车道（add-dashboard-embed-mode 全链亦 dsh），复发敞口是离群初筛在主车道上持续缺停滞维度，每轮自省都要人工翻档案补判。
  - 证据：WARNING「run planner-plan-add-harness-brand-projection-1791950590-a1: 延迟观测疑似失明（latency_rounds=0 但 assistant 轮次=252）——有模型轮次却配对不出任何 API 往返样本」（04:39:07Z）；同警告窗口内 15 次，覆盖 impl/planner/planner-judge/spec-review/admin 各型 dsh run（如 impl-…-1791950590-a1 246 轮、planner-plan-add-dashboard-embed-mode-1791971597-a1 224 轮）；日志投影管线 metrics 证 dsh 事件流在账（harness: dsh，thinking/tool_call/tool_result 均有计数），只是不参与配对；数据摘要第六节 6 个 dsh run 深扫全部 stall=0。
  - 调查评估：问题源：dsh harness 成为主车道后全量暴露（本窗口 4 个 spec 的 dsh run 均失明）。已核实：run_metrics 的延迟配对只识别 claude 形态事件流，dsh-events（dsh 车道自有事件流）的 tool_call/tool_result 不产生 API 往返样本，252 轮的大 run 也配不出一个样本，latency_stalls/p90 恒空。根因：系统性缺口——dsh 事件流未接入延迟配对，属遥测表达力缺口而非数据缺失。与存量工作关系：昨日可改进#2（停滞区间缺事件类型注记）是 claude 车道内的表达力问题，与本案是同一停滞遥测下游的两个独立缺口——只落注记不接 dsh 流，主车道停滞维度仍为空。结论：应与停滞遥测改进合并立项，避免二次返工。
  - 建议：run_metrics 延迟配对增加 dsh-events 事件形态识别（tool_call/tool_result 对、thinking 边界），使 stall/p90 对 dsh 车道生效；「失明」告警按（车道,事件形态）收敛为一次性免噪。
