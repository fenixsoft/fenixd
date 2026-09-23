## 2026-09-21

### 失误
- **Evolution checkpoint 写坏 registry.py 触发重启风暴加剧**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：拒绝 · 删除：否
  - 影响：06:24:43 Evolution checkpoint failed: 'expected an indented block after function definition on line 167 (registry.py, line 168)'。evo analysis run 修改了 core/dashboard/registry.py 但留下了 Python 语法错误，导致后续 daemon 每次启动 import registry.py 时触发异常，且修改本身刷新了文件 mtime → 立即触发 stale 检测 → 又重启，与 #1 的重启风暴形成闭环。
  - 证据：fenixd.log 06:24:43 ERROR Evolution checkpoint failed: expected an indented block after function definition on line 167 (registry.py, line 168)。当前仓库 registry.py 第 167-168 行为 '@staticmethod' 定义（正常），说明语法错误已被后续提交修复（或 evo run 回滚）。git log -- core/dashboard/registry.py 窗口内无直接提交，错误来源为 evo analysis run 的运行时文件修改。
  - 调查评估：在处置 evo-self-review-runs-archive-stats/evo-merge-back-spec-dir-inflight-guard 的 implementer 阶段暴露。已核实 fenixd.log、当前 registry.py 内容与 _check_evolution_checkpoint 代码（fenixd.py:1640）。根因：evolution analysis run 有权修改 core/ 下的文件（如 registry.py）以推进自进化，但写入后未做 py_compile 校验即落盘，导致语法错误的代码被持久化。该错误直接加剧了 #1 的重启风暴——daemon 重启后 import registry.py → 成功（修复后）/失败（修复前）→ 不管哪种，文件 mtime 已变 → stale 触发。与 add-freeze-stop-inflight-agents 无直接关系，但与 evo 机制的可靠性缺口相关。结论：evo run 的写入缺少原子性校验，属于实现层面失误。
  - 建议：为 evo analysis run 增加写入后校验：在 _evolution_worker 中，run_evolution 返回成功后，对 evo run 修改过的 core/**/*.py 文件执行 py_compile 验证，失败则 git checkout 回滚并记录 WARNING；或将 evo run 的修改范围限制在 .fenix/ 目录内，不允许直接修改 core/ 源码。

## 2026-09-22

### 浪费
- **评审车道 Exit 1 连败 12 次，约 175 轮评审对话作废**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：47 分钟内 4 个 SPEC 的评审 run 连续失败 12 次，约 175 轮对话作废（含 3 次连一轮 API 往返都没建立的 0 轮空转），4 个 SPEC 的评审各被推迟 1.4 小时以上，其中 3 条打满 3 次重试上限并升级人工。
  - 证据：fenixd.log 12 条 ERROR「评审 run 执行失败: claude CLI failed: Exit code: 1」（03:33:24 起、04:20:24 止），轮数合计 175（如 run spec-review-add-code-review-auto-fix-1789958592 33 轮、run spec-review-fix-impl-code-review-writepath-1789958599 36 轮、run spec-review-add-timeline-gate-failure-display-1789958599 35 轮）；3 条 escalation「评审尝试已达上限（3）」（a927beb26c2e / 6decb74378bd / 1f5ac0ec4764）+ 1 条 critical 信号 daemon_errors 77fbd229557c（错误指纹 af71e31b 十分钟内复现 2 次）。
  - 调查评估：在处置 fix-impl-code-review-gate-readback / fix-impl-code-review-writepath / evo-stale-selfheal-restart-cooldown / add-timeline-gate-failure-display / add-code-review-auto-fix 五个 SPEC 的收尾评审时暴露。已核实：12 条 ERROR、各 run 轮数与 stall 比例、3 条 escalation、1 条 daemon_errors 信号均取自 .fenix/logs/fenixd.log 的脚本聚合；失败形态可辨——3 条 run 报「0 rounds（无 API 往返样本）」（spec-review-fix-impl-code-review-gate-readback-1789961604 / -1789961799 / spec-review-add-timeline-gate-failure-display-1789963414），其余 stall 占比异常高（run spec-review-add-code-review-auto-fix-1789958592 的 33 轮里 stalls>60s=19，即 57%；run spec-review-add-code-review-auto-fix-1789963498 的 6 轮里 4 次 stall，67%）；重试链最终由 attempt=3 之后的新 run 于 04:46–04:49 全部「评审通过 status=repaired」收口，说明非配置性死锁；窗口内 grep「熔断 / circuit / 退避」零命中，未发现 provider 熔断层记录。根因归属：CLI/API 往返侧瞬时不稳定（同一 Exit code + 0 轮样本 + 高 stall 占比），非本仓代码回归。与存量工作关系：spec/changes 活跃区的 fix-spec-review-blocking-dispatch 与 fix-fasttrack-recovery-resume-lane 修的是评审失败后的恢复/续跑路径，不覆盖「重试本身烧掉的轮数」；spec/archive/ 下无同题归档。残余缺口：重试无退避、五条评审挤在同一 47 分钟窗口内并发重试、互为放大器。结论：属瞬时故障，未见必须立项的系统性缺陷，仅「同批并发无退避」可收紧。
  - 建议：为 spec_review 重试加指数退避 + 同批并发上限（连败后每轮退避 60s×attempt），使瞬时故障不再以「12 次连败 ×175 轮」的形式集中烧预算；并把「0 轮失败」在 run 级指标里单列，避免与真失败同读。

- **验证误判 product-bug 逼出第 5 轮空转，人工止损取消 run**
  - 自进化：问题成立 / 建议部分合理 / — 不需要
  - 影响：该 SPEC 当轮跑了两遍各 22 场景的完整验证 + 6 轮 judge 重跑 + 一次 26 轮 Administrator run 失败 + 一次 33 轮 implementer run 被人工取消；截至 03:56 累计 input token 已达 80.01M/100M（80%）、累计成本 $76.79、实现预算用掉 5/6 轮。
  - 证据：02:40:42「judge 重跑硬上限 'add-freeze-stop-inflight-agents'（6 轮）— 冻结为 blocked，等待人工裁决」（escalation judge_rerun_cap 06da94324c53）；03:56:17 Planner 把场景 web-freeze-inflight-stopped-hint 强制重写为 failed (product-bug) 并「原地打回第 1 轮」、派发 used=5/6；04:22:23 人工取消信号 4a5fd9ef5ed6，reason=「该 spec 实现已由人工裁定合并，验证失败系陈旧产物/缓存假失败，停止第 5 轮空转」，被取消的 implementer run impl-add-freeze-stop-inflight-agents-1789962978-a1 已跑 33 轮。
  - 调查评估：在处置 add-freeze-stop-inflight-agents（冻结在飞 agent，状态 pushed）验收时暴露。已核实：02:38–04:25 的完整生命周期取自 fenixd.log——02:38:39 实现成功进入阶段 2 验证，02:40:42 judge 重跑达 6/5 上限冻结 blocked，02:57:53 blocked_stuck（critical）信号 8211d734bd0f 与配套 disposition 落账，03:34 重跑 22 场景验证，03:56:17 Planner 判定并打回第 1 轮，04:22:23 人工取消，04:24:52 人工裁定 spec_done → auto-approve → pushed（main + 分支均推送成功）。根因归属：验证裁决把「陈旧产物/跨轮缓存」造成的假失败判成 product-bug（同点日志尚有「跨轮缓存归因打标 … cached_from_previous_round」与「验证报告闸门：报告属上一轮残留（本轮裁决已变更），已重新合成覆盖」），属裁决层假阳性，由人工裁定推翻——一次性误判，非 SPEC 设计缺口。与存量工作关系：spec/archive/2026-09-19-evo-judge-rerun-stability 建立的正是这条重跑/缓存机制，本处是该机制的残余面；spec/changes 活跃区无同题 SPEC。残余缺口：judge 重跑上限触顶前没有「疑似陈旧产物」的自动降级或回读校验，代价全部由人工兜底。结论：单次误判且人工兜底有效，但「陈旧产物假失败 → 空转整轮」的敞口仍在。
  - 建议：在 judge 重跑上限触顶前增加「陈旧产物嫌疑」前置判据：同场景连续两轮结论翻转且带 cached_from_previous_round 标时，先做一次产物新鲜度回读校验（或直接降级为 inconclusive 转人工），不要直接判 product-bug 打回实现轮。

### 人工运维（SPEC 激活后执行，对应 spec 的 docs/help 文档）
- **add-impl-selfcheck-model-probe 合入后**：同步修改运行时 `.fenix/config.yaml`——各 agent 类型模型链摘除 `maomaoai + deepseek-v4.1-flash` 条目（近 48h 实测 12 次 unrecognized_model 秒死 run；详见 spec 交付的 docs/help/model-chain-ops.md）。改完 `fenixd` 30s 热更新自动生效。

## 2026-09-23

### 浪费
- **三次 daemon 重启 SIGTERM 杀在飞 run，约 41 分钟工作作废**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
  - 影响：三次在飞 run 被重启连带 SIGTERM：add-code-review-auto-fix 实现轮在飞 8 分钟（00:29:32→00:37:41Z）、fix-relocation-writeback-layer 实现轮在飞 12 分钟（01:03:11→01:14:52Z）、自进化分析轮在飞 21 分钟/235 轮（12:23:31→12:44:37Z），合计约 41 分钟对话作废、该 evo 周期水位未推进；两轮实现重派后正落进 provider 瞬断窗口，成为两场全局熔断的失败主体。
  - 证据：supervisor.log 三次「restart_request detected — SIGTERM daemon for restart」（00:37:38 / 01:14:48 / 12:44:33Z）后 3-4 秒内，fenixd.log 各有一条「Sent SIGTERM to running agent」：impl-add-code-review-auto-fix-1790034572-a1、impl-fix-relocation-writeback-layer-1790038991-a1、evo-1790079811（235 rounds, median 1.5s，随后 ERROR「自进化分析 run evo-1790079811 失败（水位不推进）: Exit code: 143」）；三次重启均无「陈旧自愈触发」日志，请求来自 restart_request 协议的其它写入方。
  - 调查评估：在处置 add-code-review-auto-fix 与 fix-relocation-writeback-layer 两 SPEC 的实现轮派发时暴露。已核实：三个 run 的起止时间由 run id epoch 与 SIGTERM/延迟日志交叉吻合；12:44:38Z 落了一条 self-evolution 升级告警（admin_alerts 内 handled=true），40 分钟后继任分析 run evo-1790081383 于 13:24:37Z 落地成功，确认该 evo 周期作废后由下一周期补救、两实现轮最终也各自完成（auto-fix 07:21Z pushed、relocation-writeback b59d46c7 05:14Z 合回）。根因：restart_request（supervisor 优雅重启协议的信号文件）触发的规划性重启，在旧代码上直接 SIGTERM 全部在飞 agent、无排水等待——正是 add-pipeline-throughput-governance D3（agents.run_drain_max_seconds 排水，缺省 60s + checkpoint 旗标广播）针对的缺陷面；该 SPEC 于窗口内 15:07Z 合入（9b9cdf7f），其后 17:46:36Z 的重启（陈旧自愈，即 daemon 检测磁盘代码较新后趁连续空闲自动重启的 selfheal，且新冷却机制在场）未再杀任何 run。结论：三例杀 run 全部发生在排水机制上线前，主缺口已由在飞 SPEC 闭合；残余是排水对 evo 分析车道与 execvp 改名孙进程的覆盖尚无实测回归钉住。
  - 建议：为 restart 排水补一条回归测试：构造在飞 evo 分析 run + implementer run 时 touch .fenix/restart_request，断言 run_drain_max_seconds（缺省 60s）内两 run 不被 SIGTERM、超时才有序终止，且进程表按 cwd/cmdline 能把 execvp 后改名形态（node/ocr 等）计入排水集合。

### 失误
- **fast-track 结果文件缺 verification 段，154 轮 run 收尾作废重跑**
  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：拒绝 · 删除：否
  - 影响：add-code-fix-item-level-progress 的首个 fast-track run（实现+验证一体快车道）跑满 154 轮、消耗 9.4M input token 后，结果文件因缺 verification 段被硬校验判非法，成功状态作废并整轮重跑（第 2 轮 43 轮后 17:44Z 才合回 f19a252e）；该 SPEC 合计 10.9M input token / $10.02 / 预算 2/6，随后又被 17:46Z 重启打断收尾，至窗口末仍停 implemented。
  - 证据：17:25:37Z agent 侧「fast-track succeeded」（run impl-add-code-fix-item-level-progress-1790095299-a1，154 rounds，stalls>60s=6）同秒 ERROR「fast-track 硬校验失败 …结果文件非法（verification 段缺失或结构不完整）」（窗口内唯一一次）；17:25:38Z 原地重派（预算 used=2/6，复用 worktree），第二 run 17:44:04Z 收尾即合回；STATE 现值 status=implemented、error「Recovered from interrupted state: testing」、_cost_usd=10.02。
  - 调查评估：在处置 add-code-fix-item-level-progress 的 fast-track 收尾时暴露。已核实：两轮 run 的轮数、预算计数与时间线均出自 fenixd.log 与 STATE；代码侧成果经 worktree 复用保留，损失集中在重验收尾与约 19 分钟延迟。根因：长 run（154 轮、6 次 stall）收尾时实现侧未按契约写出 verification 段，硬校验门按设计拦下（门本身工作正常），但恢复动作只有「整轮重跑」一档，没有「定向补写结果文件」的廉价中间路径；随后 17:46:36Z 重启又把刚合回的 spec 打断在 testing 态（恢复器置 implemented）。结论：一次性收尾失误叠加恢复粒度过粗，非系统性缺陷；敞口是收尾文件 malform 概率随 run 时长上升，而重跑代价是全轮重验。
  - 建议：fast-track 硬校验拒绝时先走「定向补全」：复用 worktree 只派一个小 run 按 schema 补写/修复结果文件，校验通过即收口，连续 2 次补全失败再降级整轮重跑；并在实现侧收尾检查单中加「写完结果文件后自读回校验 verification 段存在」。

### 可改进
- **orphaned_state 探针误报 3 连发，每例烧一轮 admin 处置**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：拒绝 · 删除：否
  - 影响：已发生+复发敞口：窗口内 3 个 SPEC 在 testing 阶段被 orphaned_state（无活动 run 的孤儿态探测）误报 major 告警——12:13Z add-code-fix-manual-trigger、16:09Z add-pipeline-throughput-governance、17:05Z add-impl-selfcheck-model-probe——每例都触发一轮只读诊断 admin run 落处置记录（admin_alerts 中 orphaned_state disposition 共 6 条）；单次代价是一整个 admin LLM run 的 token 与时延，外加 major 告警进人工横幅的噪声。
  - 证据：admin_alerts.json 窗口内 orphaned_state signal/escalation 3 条 + disposition 6 条；17:05Z 处置记录自述「ocr join 停等 + 探针盲区/版本代差复合假孤儿，等车道硬超时自愈后 spec 自动 pushed」，并以 py-spy 取证到存活 ocr 子进程 PID 1833155/1833166（16:35:42Z 起）——探测器判「无活动 run / 无存活子进程」与进程表事实相反。
  - 调查评估：在处置 add-impl-selfcheck-model-probe 的验证停等时暴露（另两例同型）。已核实：三例均为误报、均以「等车道自愈」收口，未造成状态破坏，代价集中在诊断与告警消耗。根因：探测器的存活子进程枚举覆盖不了 execvp 后改名的形态（ocr 子进程现形为 node/ocr，不在探针子进程树内），叠加 daemon 版本代差（新加的心跳/超时字段在旧代码进程上不生效）；fix-ocr-lane-orphaned-state-misfire（14:35Z 合入，074084bb）修的是「嵌套 fingerprint 产物误判未绑定指纹/门在飞检测补全」变体，而 16:09Z 与 17:05Z 两例发生在其合入之后，属未被该 SPEC 覆盖的残余变体。结论：探测判据与代差兼容是系统性缺口，不修则每轮 ocr 长验证停等都会再烧一轮处置。
  - 建议：orphaned_state 存活判据扩展为进程表按项目 worktree 的 cwd/cmdline 匹配后代进程（覆盖 execvp 改名形态），并把「车道停等注记在场」作为显式豁免判据；探测前先比对心跳字段版本与 daemon 进程 lstart，版本代差期降级为 INFO 不升级告警。


## 2026-09-24

### 浪费
- **审查车道三连败零产出，约65分钟审查全废**
  - 影响：仓库手动审查（对全仓 137 文件的代码审查车道）三连败零产出：三次 run 合计约 65 分钟、955 轮对话全部作废，台账改动为 inserted=0/updated=0/resolved=0，其中两次留有成本记录合计 $39.44（$21.54 与 $17.90），第三次以 Max turns 报错终止未留成本记录；用户被迫手动止损取消并当场立项根治，补救 SPEC 自身又消耗了出题 124 轮、实现 169 轮与一轮 admin 处置。
  - 证据：run code-review-1790154247（仓库审查 run，507 轮）09:04:07Z 起 09:33:02Z 止，终态 error「Max turns (1200) reached — turn extension budget exhausted (2/2)」，此前 09:23:19Z 有「Turn limit extended (1/2): step=200, new_cap=1000, evidence=tool_result traffic in last 60s」；run code-review-1790178542 与 code-review-1790180307 分别 258 轮/19.6 分钟、190 轮/16.8 分钟，均被「产物硬门拦截: manifest=137 — 审查产物缺失（repo-code-review-gate，审查结果 jsonl 逐文件落行的硬校验门）」拦下；16:36:52Z 用户取消记录 reason=「18分钟零落盘，async子代理模式机制性失效，止损并立项根治」（source=dashboard）。
  - 调查评估：在处置仓库手动审查车道（code-review 手动审查）的第三连败时暴露。已核实：三份 run 产物均在 .fenix/runs/archive/，前两次 exit 0 但 out-code-review-*.jsonl 不存在（产物硬门按设计拦下、避免零产出假成功），第三次把轮次上限两次扩到 1200 仍烧尽——扩轮凭据只是「近 60 秒有工具流量」，流量不等于进展。根因：审查 agent 采用异步子代理（async subagent）模式后把全部落盘推迟到收尾，子代理结果从未逐文件追加进结果 jsonl，属车道纪律缺陷而非 provider 故障。与存量工作关系：add-code-review-sharded-out（分片直写改造）正是当窗 16:47Z 立项、17:51Z 合回主树的根治 SPEC（分片直写聚合 15b18192、禁 async 等待收工契约 0e9d62d5、落盘纪律 85a2d281、事中零进度停滞告警 b7249e0d），但该 SPEC 窗口末仍处 testing 待验证；另 e1f1a57f（10:40Z）解除车道轮次上限（max_turns=None）并把 run_timeout 提至 604800 秒，连带触发 timeout_supervision.absolute_max_seconds 自动对齐（10:40:47Z 自愈持久化为 612000 秒）——止损今后完全依赖新落盘纪律与停滞告警。结论：根因已立项并在飞，损失为已发生的 conversion 成本；残余敞口是 SPEC 未过验证前车道再跑仍可能重演，且停滞告警只报不杀。
  - 建议：尽快走完 add-code-review-sharded-out 的验证收口再恢复手动审查车道；给 check_progress_stall（事中零进度停滞告警）补一个升级出口——同一 run 连续 2 次停滞告警即自动取消并记账，避免再次出现 507 轮烧到底。

- **code-fix两批合回撞主树未提交改动整批弃置**
  - 影响：code-fix 车道（自动修复审查台账条目的深夜车道）第 21、22 两批合回被整批弃置：约 2 小时车道产出作废、约 40 条台账修复（每批约 20 条）待重做，车道到 04:02:56Z 才恢复合回成功，中间约 2 小时用于止损与 defer 修复立项；第 21 批此前还多烧了一轮完整回归（01:25:12Z 首次回归未通过重试）。
  - 证据：01:38:25Z 与 02:09:04Z 各一条 ERROR「Merge-back blocked by WIP overlap precheck (policy=escalate)：2 main-tree tracked file(s) with uncommitted changes overlap branch …（QualityTab.tsx 等主树未提交改动与批次分支改动重叠）」+ 紧随的「code-fix 第 21/22 批合回冲突，现场即弃（branch/tip_sha 入档案）」；重叠脏文件与用户 UI 会话的未提交 WIP 同源（97730703「UI 会话 WIP 收尾提交」直到 02:52Z 才落主树，且当前 git status 中 QualityTab.tsx 仍为未提交态）。
  - 调查评估：在处置 code-review-fix 车道第 21/22 批合回时暴露。已核实：主树两个 dashboard 前端文件的未提交改动长时间滞留，与批次分支的修复路径重叠，escalate 政策当时只有「现场即弃」一档，已完成并通过回归的整批工作被丢弃。根因：人工/UI 会话与自动化车道共享主树工作区且互不知情（与 2026-09-23#浪费#2 的「已提交热修撞车道」同族，这次是「未提交 WIP」变体）。与存量工作关系：fix-codefix-wipgate-defer（合回 WIP 阻断分类 defer 路径与延迟合回台账）正是本事件 03:36Z 立项、04:26Z 合回 pushed 的针对性修复，其后第 1–9 批共 9 次合回零冲突，主缺口已闭合。结论：一次性环境冲突叠加上述政策缺口，修复已在飞落地；残余是 defer 的消费时机问题（见改进条「WIP阻断的延迟合回无周期消费者」）。
  - 建议：code-fix 选批前增加预检：主树 dirty 文件集合与候选批目标文件有重叠时整批推迟到 WIP 清理后再选，把冲突消在实现之前；人工侧 UI 会话触碰台账相关文件后及时提交或 stash，保持主树干净。

### 失误
- **日报聚合误判成功run为预算耗尽失败**
  - 影响：今日日报把一个完全成功的实现 run（exit 0、分支 ffe278ea 已合回主树、spec 已 pushed）误计为失败样本（marker=预算耗尽），失败数虚增（报 2 实为 1）；复发敞口：任何实现了预算治理类功能的 run，其收工摘要几乎必然复述「预算耗尽」一词（本次实拍原句「预算耗尽发一次性 warning」），每个相关 SPEC 都会再误报一次。
  - 证据：run impl-fix-codefix-wipgate-defer-1790135672-a2（fix-codefix-wipgate-defer 的实现 run，100 轮、$5.69）产物末行为 {"is_error":"False","subtype":"success","result":"收工自检 PASS（exit 0）…"}，但 1382 字符的成功摘要里含「预算耗尽发一次性 warning」；core/self_review.py:277 对 result 全文做 _business_fail_marker 子串匹配，而 _BUSINESS_FAIL_PATTERNS（self_review.py:204 起）含裸词「预算耗尽」。
  - 调查评估：在核对今日数据摘要的失败样本时暴露（本条为只读复核，未跑任何修复）。已核实：_classify_run 对 type=result 的终态不区分 is_error 一律做全文子串匹配，护栏 _signal_evidence 更是对全部事件行逐行扫描同一批词，功能词汇与失败声明词同形即误判。根因：分类器把「agent 自述摘要里的功能术语」当成「失败声明」，缺少终态成功前提或语句形态约束，属系统性误判而非一次性手误。与存量工作关系：evo-self-review-runs-archive-stats（归档）建立的是这套 run 统计的覆盖面，未覆盖匹配语义；spec/changes 活跃区无同题 SPEC。结论：修复成本极低且当天已产生错误输出，值得尽快立项。
  - 建议：对 type=result 且 is_error=False/subtype=success 的终态跳过 marker 降级（或仅在摘要前 100 字符内匹配「预算耗尽，…」等失败声明形态）；_signal_evidence 限定只在 error 终态行内匹配；补一条「成功摘要含功能词不降级」的回归用例。

### 可改进
- **并行派发同秒撞名，worktree创建连败四次**
  - 影响：已发生 4 次+复发敞口：ready 态并行派发实现与出题落在同一秒时两者生成同名分支，后到者 worktree 创建必败，窗口内 4 次派发尝试失败（每次烧掉 1 次实现尝试配额、约 5 秒重派延迟，并多拉起一个 worktree 与 dev-server）；并行出题已是就绪态默认路径，撞名概率随派发并发上升。
  - 证据：四组同签名日志：01:00:25Z（fix-fasttrack-implemented-deadstate-1790125225）、03:54:32Z（fix-codefix-wipgate-defer-1790135672）、11:30:00Z（add-codefix-batch-parallel-1790163000）、17:00:26Z（add-code-review-sharded-out-1790182826），每组均为两条间隔不足 100ms 的「Creating worktree: 同一路径同一分支」+ 一条「fatal: a branch named … already exists」+ 紧随的「Running implementer (attempt 2/3)」换新纪元后缀成功（如 …-1790135672 失败后 …-1790135677 成功）。
  - 调查评估：在处置上述四个 SPEC 的派发失败时暴露。已核实：worktree/分支名模板为 <prefix>-<spec>-<int(time.time())>，并行出题（planner-plan 与实现并行生成验证场景的机制）与实现派发同秒触发时必然同名，先到者建分支、后到者 worktree add -b 即败；无重名捕获重试、无 per-spec 命名串行化，当前靠 attempt 重试自愈。根因：命名未掺入 attempt 级唯一量，属系统性竞态而非偶发外部故障。与存量工作关系：evo-spec-concurrency-flight-guard（活跃区）管的是同 spec 重复派发的飞行守卫，不覆盖命名冲突维度。结论：修复成本一行级（重名即换名重试或复用既有分支），性价比高。
  - 建议：worktree 创建捕获「already exists」后就地换名重试（epoch+1 或加 attempt 后缀），或分支名掺入 run attempt uuid；亦可先探测同名分支无 worktree 挂载时直接复用；补一条「并行出题+实现同秒派发不撞名」回归测试。

- **WIP阻断的延迟合回无周期消费者，解锁靠人工**
  - 影响：已发生+复发敞口：add-code-review-sharded-out 合回被 WIP 重叠闸门（合回前预检主树未提交改动与分支改动是否重叠的保护闸）阻断后，spec 卡在 implementing+error 约 18 分钟（17:33:48Z→17:51:29Z），烧掉一条 major 信号与一轮 admin 处置 run（admin-add-code-review-sharded-out-1790185077，48 轮、约 17 分钟）才解锁；每次主树 WIP 与分支重叠都重演同代价。
  - 证据：17:33:48Z 信号 mergeback_wip_overlap（SPEC 合回被主树 WIP 重叠闸门阻塞、策略=block、主树零污染）；17:54:49Z 处置记录（result=resolved）诊断原文：「queue.py wip_gate_blocked 分支 early-return 不排 merge-only 重试定时器，_merge_retry_pending 无周期消费者，恢复期 re-merge（_repair_awaiting_remerge）仅 daemon boot 消费——须人工」；core/admin_monitor.py 对 _repair_awaiting_remerge 载体的豁免注释同样写明「该通路是时间点事件……有待后续 SPEC 补」。
  - 调查评估：在处置 add-code-review-sharded-out 的合回阻断时暴露（Administrator 只读诊断后人工完成合并）。已核实：fix-codefix-wipgate-defer（pushed）落了 defer 分类与延迟合回台账，但 defer 载体的唯一消费者是 daemon 启动恢复期——正常运行态下 WIP 清理后无人重试合并，orphaned_state 探测（无活动 run 的孤儿态探测）对这类有意等待载体只能豁免报错、不能驱动收敛。根因：闸门与台账齐备、缺一个「WIP 清了就自动合回」的周期消费者，属设计接缝缺口。与存量工作关系：evo-merge-back-wip-overlap-gate（归档）建闸门、fix-codefix-wipgate-defer（pushed）建 defer 路径，本条是两者的补全而非重复。结论：清晰度足以直接起草，且能消掉一类高频 admin 召唤。
  - 建议：给 _merge_retry_pending 加周期消费者（主循环或 admin 巡检每 N 分钟复查重叠文件是否已干净，干净即自动 merge-only 重试并设重试上限），在 orphaned_state 探测前先触发该检查，使自动合回成为默认路径、admin 只处理真冲突。

- **stale_code陈旧代码告警同因一日13连发**
  - 影响：噪音类：窗口内 stale_code（daemon 进程持旧代码、待空闲自愈重启的检测）升级告警 13 连发（19:46:40Z 至 17:51:03Z，约每 40–100 分钟一条），全部 warning 级、同文同因、自动处置；无直接损失，但持续占据告警横幅，稀释真实 major 信号的注意力。
  - 证据：.fenix/admin_alerts.json 窗口内 13 条 kind=escalation、signal=stale_code、handled=true、描述逐字相同（「daemon 进程持旧代码，自愈将在连续空闲后触发重启」）；当日 code-fix 批次约每 40 分钟落一次主树提交，daemon 长期处于「刚变陈旧又找不到空闲重启」的循环，每轮巡检重复成条。
  - 调查评估：在核对窗口告警分布时暴露（13 条升级告警全部为该信号）。已核实：evo-alert-noise-governance（09-23 pushed）给 daemon_errors 落了指纹级重启冷却与孪生指纹合并，但 stale_code 不在其治理面内，同因重复升级无冷却。根因：告警生命周期按「每次检测即成条」运行，未对「同因未变化、处置动作不变（继续等空闲）」的去重场景收敛。与存量工作关系：是 evo-alert-noise-governance 的自然延伸（同一治理思路补一个信号面），非重复立项。结论：小体量高确定性，可并入下一次告警治理或作为独立小 SPEC。
  - 建议：对 stale_code 增加同因冷却：持旧期间同一 daemon 生命周期只升级告警一次，或 60 分钟窗口内去重、仅当「已找到空闲并排期重启」状态变化时再报；历史条目折叠进一条聚合记录供回查。
