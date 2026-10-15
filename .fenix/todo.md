## 2026-10-13

### 知识真相源
- audit 疑点升级待人工（聚合）：10 条待人工仲裁（最长龄期 16 天），请人工按指纹在 .fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/decided_at/note），框架检查点自动消费后恢复自动复核

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
- **run 停滞遥测缺事件类型注记，33 次停滞无法区分工具执行与 API 等待**
  - 自进化：问题部分成立 / 建议部分合理 / — 不需要
  - 影响：4 个离群 run 合计 33 次停滞（stall，事件流相邻事件间隔超阈值）、最长单次 298.7 秒，因遥测只记间隔时长不记边界事件类型，审查无法裁决是长工具调用（全量回归等合法耗时）还是 provider 往返/重试浪费，结论只能停在形态层、根因未定。
  - 证据：数据摘要第六节深扫：impl-add-dsh-adapter-integration-1791884537-a1 stall=11 max_gap=262.6s；impl-add-fenix-dsh-bundle-1791871868-a1 stall=11 max_gap=298.7s；impl-add-harness-adapter-layer-1791863204-a1 stall=6 max_gap=199.7s；planner-judge-add-dsh-adapter-integration-1791894482-a1 stall=5 max_gap=288.0s（已核实其档案 244 事件、62 次 Bash 调用，20:28–21:03 本地为命令密集型评审，非空转）。
  - 调查评估：问题源：三个大型 spec 实现 run 与一个出题评审 run 的离群初筛暴露。已核实：全部停滞无中途 stderr、四个 run 均成功收尾；planner-judge 档案显示 Bash 密集型工作，推测大间隔多为长命令执行，但 impl 三个 run 无事件级证据可在两假说间裁决——按归因边界规则只写形态层、不预设根因。与存量工作关系：evo-add-run-metrics-lane-baseline 已建车道基线使离群可初筛，本缺口是停滞维度的遥测表达能力，属互补不重复。结论：小改动即可让每日自省从「形态层」升到「归因层」，避免每轮审查重复人工翻档案。
  - 建议：run 事件流落盘时为停滞区间标注边界事件类型（工具执行 vs API 往返），self-review 聚合按两类分列透出计数与最长间隔，使离群审查可直接区分合法长工具与等待浪费。

## 2026-10-15

### 浪费
- **并行出题三跑两弃：47 万 token 场景产物压线被隔离**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：add-harness-brand-projection 一个 spec 的验证场景出题（planner-plan）三跑仅一跑被采信：36 分钟、397,585+77,094 token 的已完成产物在完成线同秒被并行出题仲裁按「半成品」隔离弃用，另一跑 1373 秒、257 轮被取消后原样重派——出题环节约 90 分钟 planner 墙钟时间有效产出仅 1/3，其中约 47.5 万 token 与 23 分钟可判定为纯弃。
  - 证据：日志 04:39:07.616「并行出题产物已隔离（不被采信）…testing 等待并行出题超时，半成品隔离」、04:39:07.687「并行出题等待超时—已取消在飞 run 并隔离半成品，转串行重出」，与 run_metrics 里 planner-plan-add-harness-brand-projection-1791950590 的 success（duration 2158.874s、252 轮）同秒；04:39:10.128「并行出题标记已被消费侧接管（discarded），放弃 completed 登记」；后续 planner-plan-…-1791953455 terminal=cancelled（1373.42s、257 轮、0 token 入账），其取消时刻（05:13:49Z）恰为替代者 1791954828（success、1893.078s、391,474+93,892 token）的起跑时刻。
  - 调查评估：问题源：add-harness-brand-projection 验证链出题阶段（并行出题=双 planner 竞速生成验证场景、testing 阶段汇合采信其一）。已核实：join（汇合点）超时与 racer 完成同秒触发，完成的 252 轮产物按「半成品」隔离且完成登记被拒，随后串行重出（1791952747）又撞上秒挂风暴全灭，出题净空转；被取消的 1791953455 与替代者之间是「取消即串行重派」衔接，取消时机不与「兄弟产物被采信」对齐。根因按归因边界写到形态层：join 无「压线完成宽限」语义、racer 取消与采信事件不对齐，两点机制事实成立；是否叠加 dsh 车道出题本身过慢（本窗口 dsh 出题 15-36 分钟、200+ 轮 vs 组中位 25 秒）未在多假说间裁决，不出单因结论。与存量工作关系：并行出题仲裁已有运营侧教训（双 planner 竞速时僵尸方勿覆盖权威场景文件），但 join 宽限与取消对齐无在飞 spec 覆盖；秒挂风暴（另一条目）放大了本轮代价。结论：机制小改可消除大部分弃产物，值立项。
  - 建议：给并行出题 join 加完成宽限窗：超时触发时等待在飞 racer 完成或 N 秒宽限，压线完成即采信而非按半成品隔离；把另一 racer 的取消绑定到「采信事件」而非固定时钟——采信即取消、未采信不预取消。

### 失误
- （当日无）

### 可改进
- **dsh 车道延迟观测失明，停滞遥测对主车道结构性无效**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：窗口内全部 dsh 车道大 run（15 个，含 252-274 轮的出题/实现 run）API 往返配对恒为 0，「延迟观测疑似失明」告警 15 次——停滞/慢往返遥测对 dsh 车道结构性失效，今日深扫 6 个 dsh run 的 stall=0 是「看不见」而非「没停滞」；dsh 已成新 spec 默认车道（add-dashboard-embed-mode 全链亦 dsh），复发敞口是离群初筛在主车道上持续缺停滞维度，每轮自省都要人工翻档案补判。
  - 证据：WARNING「run planner-plan-add-harness-brand-projection-1791950590-a1: 延迟观测疑似失明（latency_rounds=0 但 assistant 轮次=252）——有模型轮次却配对不出任何 API 往返样本」（04:39:07Z）；同警告窗口内 15 次，覆盖 impl/planner/planner-judge/spec-review/admin 各型 dsh run（如 impl-…-1791950590-a1 246 轮、planner-plan-add-dashboard-embed-mode-1791971597-a1 224 轮）；日志投影管线 metrics 证 dsh 事件流在账（harness: dsh，thinking/tool_call/tool_result 均有计数），只是不参与配对；数据摘要第六节 6 个 dsh run 深扫全部 stall=0。
  - 调查评估：问题源：dsh harness 成为主车道后全量暴露（本窗口 4 个 spec 的 dsh run 均失明）。已核实：run_metrics 的延迟配对只识别 claude 形态事件流，dsh-events（dsh 车道自有事件流）的 tool_call/tool_result 不产生 API 往返样本，252 轮的大 run 也配不出一个样本，latency_stalls/p90 恒空。根因：系统性缺口——dsh 事件流未接入延迟配对，属遥测表达力缺口而非数据缺失。与存量工作关系：昨日可改进#2（停滞区间缺事件类型注记）是 claude 车道内的表达力问题，与本案是同一停滞遥测下游的两个独立缺口——只落注记不接 dsh 流，主车道停滞维度仍为空。结论：应与停滞遥测改进合并立项，避免二次返工。
  - 建议：run_metrics 延迟配对增加 dsh-events 事件形态识别（tool_call/tool_result 对、thinking 边界），使 stall/p90 对 dsh 车道生效；「失明」告警按（车道,事件形态）收敛为一次性免噪。


## 2026-10-16

### 浪费
- **_run_agent 解包漏改 22 连崩，code-fix 链空转 12 小时**
  - 影响：维护五车道 run 一收尾即崩，code-fix 链自首崩到人工修复空转约 12 小时：25 个 code-fix run 与 1 个 admin run 崩溃弃置，有成本档案的 10 个合计 $129.05（单个 $10.1-14.7、API 时长 74-100 分钟），agent 已实际完成的修复全部弃置重修，95 条台账 0 核销；另有 1 个 run 死于账户级 429 限流、1 个 run（588 轮）死于重启排水 SIGTERM。
  - 证据：错误指纹「too many values to unpack (expected 4)」首现 10-14T21:27Z（本地 05:27，run code-fix-1792012044）、末现 10-15T09:33Z（本地 17:33）；修复 commit 63d952e74（本地 18:10）自述根因并给出 diff：dd78b1b82（evo-api-stall-signal-grading，本地 02:46）把 _run_agent（维护车道共用的 agent 进程封装）返回值从 4 元扩为 5 元，runner.py 三处调用点同步而 maintenance_runs.py 五处全部漏改；修复后链 rollup（链收尾汇总监算行）20:41 本地 resolved=66、21:27 本地 resolved=27，约 3 小时补核销 93 条。
  - 调查评估：问题源：code-review 台账的 code-fix 批量核销链（evolution/self_review/administrator/code-review 四条维护车道同款崩溃）。已核实：63d952e74 的 diff 确认五处调用点补第 5 元绑定、bin/dsh_acceptance.py 三处与 12 个测试文件的旧 4 元桩同步，并新增 tests/test_run_agent_call_site_arity.py——读源码语法树（AST）的契约测试，断言全部调用点解包宽度必须等于 _run_agent 返回宽度，任一侧漂移即红。根因：dd78b1b82 的 proposal 交付物只声明 runner.py/latency.py/self_review.py，改共享函数返回宽度时没有「全调用点清单核验」步骤，spec 验证的测试面也不覆盖维护车道调用点（须真实维护 run 跑到收尾才暴露）——且此为同族第二次（2026-09-05 曾 3→4 元同款崩溃，fenixd.log.3 可查），说明仅靠细心不可持续，家族复发面已被本次 AST 契约测试钉死。与存量工作关系：修改源头 spec evo-api-stall-signal-grading 的范围声明本身不含 maintenance_runs.py，属范围划定盲区而非执行走样；检测面缺口（22 次同指纹崩溃 12 小时零升级）单列为同日可改进条目，不在此重复。结论：损失确定性成立（成本档案在案），复发面已闭环，残余敞口仅检测面。
  - 建议：无需新 SPEC：63d952e74 已补齐五处调用点并以 AST 元数契约测试钉死同族复发；确认该契约测试进入后续触碰 agent_runner 的 spec 验证必跑面即可，检测面缺口见同日可改进条目。

### 失误
- （当日无）

### 可改进
- **慢速同指纹崩溃环无熔断，22 连崩 12 小时零升级信号**
  - 影响：复发敞口：凡「run 全长执行完毕后在框架侧收尾崩溃」的故障（共享契约漂移、结果解析变更等）再现场景，链路将按本次实测每约 30 分钟烧一个 $10-15 的全长 run、持续到人工带外介入（本次 12 小时、$129+），全程无任何车道暂停或 admin 升级信号。
  - 证据：25 个同指纹崩溃横跨本地 05:27-17:33、间隔约 25-35 分钟；窗口内 admin 信号仅 5 条（夜间静默窗结束、主树散件 WIP 滞留、commit_stray_wip 处置失败、code_fix_wip_gate_deferred、daemon_errors），无一指向该崩溃环；信号 cd6294033b0a（daemon_errors——daemon 日志同指纹 ERROR 聚合升级信号，critical）的描述自证升级门槛为「同指纹 ≥2 次且最近两次间隔 ≤5 分钟」，其指纹 ade5f4e8 命中的是 11:46Z worktree_manager 的 WIP-overlap 同秒双日志，而非解包崩溃；既有秒挂冷却（连续进程秒死后暂停派发的熔断）按派发即死计数，收尾崩溃不进计数。
  - 调查评估：问题源：同一浪费事件的检测面。已核实：解包崩溃只产生 [code-fix]/[admin] ERROR 行，未产生任何信号；daemon_errors 升级规则的间隔门槛（≤5 分钟）与本次崩溃节奏（25-35 分钟）结构性错配——它能抓 11:46Z 的突发双日志，抓不住慢速滴漏；修复全程人工带外完成：主树散件 WIP 盘点信号 08d0c1319acc（major，已升级）首见本地 12:26、清单含 maintenance_runs.py 与 tests/test_admin_disposition_failure_context.py（正是 18:10 修复 commit 的触碰文件，指向人工彼时已着手修复），13:01 自动收编尝试因清单陈旧失败，18:10 修复落地后经 planned restart 排水装载。根因按形态层写：崩溃环未落入任何既有熔断器的死亡分类（秒挂冷却管派发即死、add-codefix-parse-error-breaker 管回归 parse_error、evo-add-codefix-anomaly-redispatch-budget 管失败批重派预算），链路也缺少「烧了 N 个 run 却零核销」的健康视角——daemon_errors 为何未对解包指纹计数升级（阈值/组件覆盖/节流）未核实，多假说并存，不影响形态结论。与存量工作关系：上述三个已实现 spec 的死亡分类均不含本形态，今日闭环的秒挂冷却全车道门控扩的是车道面不是死亡形态面，无重复立项。结论：形态明确、可起草，值立项。
  - 建议：给维护车道加两条止损线：①同错误指纹跨 run 滚动计数（如 2 小时内 ≥3 次）即暂停该车道派发并升级 admin 信号，复用秒挂冷却的 spec 作用域门控与到期复诵翻倍语义，恢复前要求指纹消失；②链级健康信号——同链连续 ≥3 个 run 正常烧完却 resolved=0（非秒挂形态）时升级，使「空转零核销」不再依赖人工看板发现。

- **审查 run 收尾 api_error，抢救后覆盖缺口悬置 20 小时**
  - 影响：一轮周期审查 run 花 $82.98、API 时长 5.5 小时后死在收尾（terminal_reason=api_error、Exit 1），靠 error 收场抢救（error 终态时把已产出的审查 shards 结果落账）保住 30 shards、95 条发现并标「部分覆盖待核销」，此后至窗口结束约 20 小时无第二次成功审查补齐覆盖，未覆盖面的发现延迟到下一轮周期。
  - 证据：run code-review-1791997425 档案：total_cost_usd=82.983、duration_api_ms=19842 秒、terminal_reason=api_error；日志 10-14T20:32Z「error 收场抢救落账: shards=30 inserted=95 updated=0」「部分覆盖待核销」；该行之后至窗口末（10-16 00:03 本地）无第二条「周期审查完成」记录；数据摘要第六节显示该 run 44 次 API 停滞、累计 3756.2 秒、最长 152.5 秒。
  - 调查评估：问题源：code-review 周期审查链（夜间全量审查）。已核实：抢救落账按设计工作，台账 95 条当日即被 code-fix 链消费（修复后 rollup 合计 resolved=93），本次实际损失有限——主要是收尾阶段综合产出丢失与覆盖缺口悬置。归因边界：44 次停滞合计 62.6 分钟无法区分长工具执行与 API 等待（停滞遥测无边界事件类型注记，即 2026-10-14#可改进#2 的既有缺口，不重复立项）；收尾 api_error 的具体根因（provider 错误/限流/进程被杀）档案仅有 Exit code 1，证据不足以裁决，不作单因结论。与存量工作关系：error 收场抢救机制已存在且有效；「部分覆盖待核销」目前只是台账注记，无信号、无续审安排。结论：单次损失小，但 $80+ 量级大 run 以 api_error 收场一旦抢救也失败即为全损，值得加一层廉价的可见性与续审兜底；先观测，若连续两轮同形态收尾失败则立项。
  - 建议：给「部分覆盖待核销」加一条 admin INFO 信号并在下轮审查提示词中携带未覆盖 shards 清单；周期审查连续两轮收尾失败时，按 infra 台账限次语义只对未覆盖 shards 派发续审，避免整轮重烧。
